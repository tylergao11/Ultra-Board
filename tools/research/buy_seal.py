"""Buy-day review using saved static judgements and observed market facts.

Preparation refreshes only event facts and the independently derived peer list.
Trading decisions never reclassify a stock or calculate an exit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from html import escape
from datetime import datetime
from pathlib import Path

from .batch import (_select_records, _trading_dates, _competitor_candidates,
                    _trade_market, _source_values, _write_json, _read_json,
                    _record_facts, _current_static_decision, dynamic_request, opening_day_result)
from .derive import Resolver, _match_row
from .system import ResearchStore, SHANGHAI


def fetch_crosscheck(store, day, directory, pool='limit_up'):
    """Preserve a dated independent pool to resolve missing interval timestamps."""
    from .network import request_bytes
    datetime.strptime(day, '%Y-%m-%d')
    if pool not in ('limit_up', 'limit_up_broken'):
        raise ValueError('unsupported pool')
    url=f'https://flash-api.xuangubao.com.cn/api/pool/detail?pool_name={pool}&date={day}'
    document=json.loads(request_bytes(url,timeout=30))
    if document.get('code') != 20000 or not isinstance(document.get('data'),list):
        raise ValueError('invalid dated pool response')
    for row in document['data']:
        for field in ('first_limit_up','last_limit_up','first_break_limit_up','last_break_limit_up'):
            if row.get(field) and datetime.fromtimestamp(row[field],SHANGHAI).date().isoformat()!=day:
                raise ValueError('pool contains wrong-date event')
    path=directory/'sources'/f'xgb-{pool}-{day}.json'
    _write_json(path,{'url':url,'response':document})
    return path,document['data']


def passed(raw):
    return raw.get('补涨判断') == '非补涨' and raw.get('压制判断', '').startswith('无')


def request(key, updates):
    digest = hashlib.sha256(json.dumps(updates, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]
    return dict(request_id=f'buy-prerequisites-{key}-{digest}', record_key=key,
                kind='static', updates=updates)


def prepare(store, keys, directory):
    """Update peer facts without redoing or replacing static judgements."""
    c = store.connect()
    result = {'records': [], 'errors': [], 'event_repairs': []}
    try:
        dates = _trading_dates(c)
        static_rules = _read_json(store.root/'data/store/rules/static_rules.json')['rules']
        resolver = Resolver(c, static_rules, {})
        peer_years = static_rules.get('潜在竞争对手参数', {}).get('适用年份', [])
        rows = _select_records(c, None, None, keys)
        for row in rows:
            key = row['legacy_record_key']; raw = json.loads(row['raw_json'])
            day = row['event_date']
            if not day:
                # Only complete an unfinished event from already saved observations.
                market = _trade_market(c, row['stock_id'], row['focus_date'], 20)
                for quote in market['following']:
                    if quote.get('limit_up') and quote.get('low') is not None and quote['low'] < quote['limit_up']:
                        day = quote['day']
                        updates = {'首开日期': day, '首开日期核验来源': quote['sources']}
                        with store.immediate(c):
                            c.execute("UPDATE first_open_events SET event_date=?,event_status='occurred' WHERE id=? AND event_date IS NULL",
                                      (day, row['first_open_event_id']))
                            store.write_research(request(key, updates), c)
                        result['event_repairs'].append({'record_key': key, 'date': day})
                        break
            if not passed(raw):
                continue
            if not day:
                result['errors'].append({'record_key': key, 'error': '未找到首开日'})
                continue
            if int(day[:4]) not in peer_years:
                continue
            try:
                pool = _competitor_candidates(c, dates, row['stock_id'], row['focus_date'], day)
                # Position is the last actual closing board height, including a suspended stock.
                prev = c.execute("SELECT board_height FROM daily_market WHERE stock_id=? AND trade_date<=? AND source_type='kaipanla_limit_pool' ORDER BY trade_date DESC LIMIT 1",
                                 (row['stock_id'], pool['date'])).fetchone()
                if not prev or pool['candidate_height'] != prev[0]:
                    raise ValueError('前日身位与候选身位不一致')
                checks = [_match_row(m, pool['date'], raw['唯一主炒作属性'], resolver) for m in pool['members']]
                hits = [v for v in checks if v['命中']]
                updates = {'首开潜在竞争对手事实清单': hits, '首开潜在竞争对手候选全集': pool,
                           '首开竞争属性核验明细': checks}
                with store.immediate(c):
                    store.write_research(request(key, updates), c)
                result['records'].append({'record_key': key, 'peers': [v['股票代码'] for v in hits]})
            except (ValueError, KeyError) as exc:
                result['errors'].append({'record_key': key, 'error': str(exc)})
        _write_json(directory/'prerequisites.json', result)
        return result
    finally:
        c.close()


def seconds(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value/1000, SHANGHAI).strftime('%H:%M:%S.%f')
    h, m, s = str(value).split(':')
    return int(h)*3600 + int(m)*60 + float(s)


def clock(value):
    if value is None:
        return None
    h = int(value//3600); m = int(value%3600//60); s = value%60
    return f'{h:02d}:{m:02d}:{s:06.3f}'


def morning_buy(observation):
    """Apply the current session rule to observed, not inferred final, times."""
    o = observation
    if o['buy'] is not True:
        return o['buy'], o['reason']
    if o['one'] and o.get('broken') is not None and not 34200 <= o['broken'] <= 41400:
        return False, '非上午首次开板'
    if o.get('time') is None:
        window = o.get('time_window')
        if window and len(window) == 2 and 34200 <= window[0] <= window[1] <= 41400:
            return True, '上午首次回封（时间区间核验）' if o['one'] else '上午首次上板（时间区间核验）'
        return None, '首次实际买点时间待核'
    if not 34200 <= o['time'] <= 41400:
        return False, '非上午首次回封' if o['one'] else '非上午首次上板'
    # A verified morning reseal necessarily follows a morning opening break.
    return True, '上午首次回封' if o['one'] else '上午首次上板'


def observe(market):
    """Keep unknown times unknown; opening itself is normalized to 09:30."""
    e = market.get('event') or {}
    result = dict(day=market.get('event_date'), one=None, touch=None, broken=None,
                  reseal=None, count=None, complete=False, buy=None, reason=None,
                  time=None, sealed=None, sources=e.get('sources', []))
    if any(e.get(k) is None for k in ('open', 'high', 'low', 'close', 'limit_up')):
        result['reason'] = '行情字段不完整'; return result
    up = e['limit_up']; result['one'] = e['open'] == up
    result['sealed'] = e['close'] == up
    events = e.get('events', [])
    intervals = []
    for ev in events:
        if ev['event_type'] == 'limit_summary':
            result['count'] = ev['value'].get('board_count')
            result['complete'] = ev['value'].get('complete', False)
        if ev['event_type'] == 'limit_intervals':
            intervals = ev['value']['intervals']
    intervals = sorted(intervals, key=lambda v:v['time'])
    starts = [seconds(v['time']) for v in intervals]
    breaks = [seconds(v['openTime']) for v in intervals if v.get('openTime')]
    result['touch'] = 34200.0 if result['one'] else min(starts, default=None)
    result['broken'] = min(breaks, default=None)
    # If the auction opened at limit but the first recorded seal is later,
    # that first recorded seal is already the first reseal, not the next one.
    if result['one'] and starts and starts[0] > 34200:
        result['reseal'] = starts[0]
        result['broken'] = None  # opening break is not in this interval list
    elif result['broken'] is not None:
        result['reseal'] = min((v for v in starts if v > result['broken']), default=None)
    if result['touch'] is None:
        touches = [seconds(v['event_time']) for v in events if v['event_type'] in ('first_touch', 'first_limit') and v['event_time']]
        result['touch'] = min(touches, default=None)
    if e['high'] < up:
        result.update(buy=False, reason='未触及涨停'); return result
    if result['one']:
        if e['low'] == up:
            result.update(buy=False, reason='全天未开板'); return result
        if result['reseal'] is not None:
            result.update(buy=True, time=result['reseal'], reason='首次回封'); return result
        if result['sealed'] or (result['count'] is not None and result['count'] >= 2):
            result.update(buy=True, reason='已证实回封，首次回封时刻待核'); return result
        if result['count'] == 1 and starts and starts[0] == 34200:
            result.update(buy=False, reason='一字开板后未回封'); return result
        result['reason'] = '封板字段为空，未证实回封'; return result
    if result['sealed']:
        result.update(buy=True, time=result['touch'], reason='收盘涨停证实已上板')
        return result
    if result['count'] is not None and result['count'] > 0 and result['touch'] is not None:
        ok = True
        result.update(buy=ok, time=result['touch'] if ok else None,
                      reason='首次上板')
    else:
        result['reason'] = '未证实实际封板'
    return result


def scan(store, keys, directory):
    c = store.connect(); records=[]; pairs=set()
    try:
        for row in _select_records(c,None,None,keys):
            raw=json.loads(row['raw_json'])
            market=_trade_market(c,row['stock_id'],row['event_date'],0)
            if opening_day_result(market)['当天是否封板'] is None:
                pairs.add((row['code'],row['event_date']))
            if not passed(raw):continue
            fact=_record_facts(store,c,[],None,row,'dynamic')
            o=observe(fact['first_open_market'])
            prev=(fact['first_open_market'].get('previous') or {}).get('close')
            op=(fact['first_open_market'].get('event') or {}).get('open')
            auction=op is not None and prev is not None and op>=prev
            if '医药' not in raw['唯一主炒作属性'] and o['buy'] is not False:
                pairs.add((row['code'],row['event_date']))
                for peer in raw.get('首开潜在竞争对手事实清单',[]):
                    pairs.add((peer['股票代码'],row['event_date']))
            records.append({'record_key':row['legacy_record_key'],'name':raw.get('股票'),
                            'theme':raw['唯一主炒作属性'],'auction':auction,**o})
        result={'records':records,'pairs':[list(v) for v in sorted(pairs)]}
        _write_json(directory/'scan.json',result)
        return result
    finally:c.close()


def evaluate(store, keys, directory, commit=False, buy_day_only=False, commit_resolved=False):
    c=store.connect();records=[];decisions=[];facts=[]
    bought_rounds=set()
    reviews=_read_json(directory/'reviewed-observations.json') if (directory/'reviewed-observations.json').exists() else {}
    try:
        for row in sorted(_select_records(c,None,None,keys), key=lambda r:(r['event_date'] or '',r['legacy_record_key'])):
            fact=_record_facts(store,c,[],None,row,'dynamic');raw=fact['current_static_raw'];key=row['legacy_record_key']
            # This research does not carry future quotes into its decision or output.
            fact['first_open_market']=_trade_market(c,row['stock_id'],row['event_date'],0)
            static=_current_static_decision(raw)
            record={'record_key':key,'date':row['event_date'],'name':raw.get('股票'),
                    'theme':raw['唯一主炒作属性'],'bought':False,'sealed':None,'time':None,'pk':[]}
            record['day_sealed']=opening_day_result(fact['first_open_market'])['当天是否封板']
            decision={'record_key':key,'static':static}
            if not passed(raw):
                record['reason']='、'.join(v for v in ('补涨' if raw['补涨判断']=='补涨' else '', '一字压制' if raw['压制判断'].startswith('有') else '') if v)
            else:
                market=fact['first_open_market'];o=observe(market)
                review=reviews.get(key,{})
                if review.get('buy') is False:
                    o.update(buy=False,reason=review['basis'])
                elif review.get('buy') is True and review.get('sources'):
                    o.update(buy=True,reason=review['basis'])
                for field in ('time','broken','reseal'):
                    if review.get(field) is not None:o[field]=seconds(review[field])
                if review.get('time_window') and review.get('sources'):
                    o['time_window']=[seconds(v) for v in review['time_window']]
                if review.get('sources'):o['sources']=sorted(set(o['sources']+review['sources']))
                e=market.get('event') or {};prev=(market.get('previous') or {}).get('close')
                pct=(e['open']/prev-1)*100 if prev and e.get('open') is not None else None
                checks=[]
                eligible, timing_reason = morning_buy(o)
                round_key=(row['code'],fact['identity']['first_board_date'])
                if '医药' in raw['唯一主炒作属性']:record['reason']='医药及医药强相关题材，不买'
                elif round_key in bought_rounds:record['reason']='同一启动轮已存在买入机会，不重复买入'
                elif eligible is False:record['reason']=timing_reason
                elif eligible is None:record.update(bought=None,reason=timing_reason)
                else:
                    record.update(bought=True,reason=timing_reason,sealed=o['sealed'])
                    bought_rounds.add(round_key)
                record['time']=clock(o['time']);record['pk']=checks
                record['observed']=o
                dynamic={'auction':{'结果':'事实记录，不作全局淘汰','开盘涨幅百分比':pct,'依据':'首开日开盘价与前一交易日不复权收盘价比较；当前规则未以低开淘汰'},
                         'pk_checks':checks,'pk_result':'不参与筛选',
                         'buy_point':{'结果':'触发' if record['bought'] else '未触发' if record['bought'] is False else '未明确',
                                      '买点类型':'首次回封' if o['one'] else '首次上板','买点时间':record['time'] if record['bought'] else None,'事实':record['reason'],'来源':o['sources']},
                         'outcome':{'研究范围':'买点封板率','是否买入':record['bought'],'买入日最终封板':record['sealed']}}
                if review.get('time_window'):
                    dynamic['buy_point'].update(买点时间区间=review['time_window'],时间精度='区间，不代表精确秒',补证依据=review['basis'])
                if record['bought']:
                    dynamic['outcome'].update(买入价格=e['limit_up'],买入日期=row['event_date'])
                if record['bought'] and not buy_day_only:
                    following=_trade_market(c,row['stock_id'],row['event_date'],1)['following']
                    next_day=following[0] if following else {}
                    record['next_day']=next_day
                    known=all(next_day.get(k) is not None for k in ('close','high','limit_up','limit_down'))
                    record['next_limit_down']=bool(next_day['close']==next_day['limit_down']) if known else None
                    record['next_board']=bool(record['sealed'] and next_day['close']==next_day['limit_up']) if known else None
                    record['repaired']=bool(not record['sealed'] and next_day['high']>e['limit_up']) if known else None
                    dynamic['outcome'].update(次日最终跌停=record['next_limit_down'],统计次日连板=True,次日日期=next_day.get('day'),次日最终连板=record['next_board'],
                                              次日最高超过买入价=record['repaired'],次日行情=next_day)
                decision['dynamic']=dynamic
            records.append(record);decisions.append(decision);facts.append(fact)
        bought=[r for r in records if r['bought'] is True];uncertain=[r for r in records if r['bought'] is None]
        result={'total':len(records),'static_pass':sum(passed(f['current_static_raw']) for f in facts),
                'bought':len(bought),'sealed':sum(r['sealed'] for r in bought),'uncertain':len(uncertain),'records':records}
        result['seal_rate']=result['sealed']/len(bought) if bought else None
        result['next_day_missing']=[r['record_key'] for r in bought if not buy_day_only and r['next_board'] is None]
        if not buy_day_only:
            result['next_board_count']=sum(r.get('next_board') is True for r in bought)
            result['next_board_rate']=result['next_board_count']/len(bought) if bought else None
        _write_json(directory/'buy-seal-review.json',result)
        if commit or commit_resolved:
            missing_day=[r['record_key'] for r in records if r['day_sealed'] is None]
            if missing_day:raise ValueError('首开日收盘封板事实不完整：'+str(missing_day))
            if uncertain and not commit_resolved:raise ValueError('尚有未核清的买点，禁止作为完整统计发布')
            if result['next_day_missing']:raise ValueError('次日行情不完整：'+str(result['next_day_missing']))
            from .batch import verify_dynamic
            unresolved_rounds={(f['identity']['code'],f['identity']['first_board_date']) for f,r in zip(facts,records) if r['bought'] is None}
            completed=[(f,d) for f,d in zip(facts,decisions) if (f['identity']['code'],f['identity']['first_board_date']) not in unresolved_rounds]
            result['pending_record_keys']=[f['record_key'] for f in facts if (f['identity']['code'],f['identity']['first_board_date']) in unresolved_rounds]
            for f,d in completed:
                saved=c.execute('SELECT confirmation_status,raw_json FROM current_dynamic_research WHERE legacy_record_key=?',(f['record_key'],)).fetchone()
                if saved and (saved['confirmation_status']=='user_confirmed' or json.loads(saved['raw_json']).get('用户逐笔审核')):
                    raise ValueError(f['record_key']+' 已有用户逐笔确认，不允许批量覆盖')
            store.sync_rules()
            with store.immediate(c):
                for f,d in completed:store.write_research(dynamic_request(f,d,'buy-day-seal'),c)
                audit=verify_dynamic(store,{'records':[f for f,d in completed]},{'records':[d for f,d in completed]},c)
                if not audit['passed']:raise ValueError(audit)
                c.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('statistics_export_pending','1')")
            result['verification']=audit
            result['export']=store.publish_pending()
            _write_json(directory/'buy-seal-review.json',result)
        return result
    finally:c.close()


def refresh_facts(store, keys, directory):
    """Refresh source references after intake without changing saved decisions."""
    def facts_only(value):
        if isinstance(value, dict):
            return {k: facts_only(v) for k, v in value.items() if k not in ('sources', '来源', 'field_sources')}
        if isinstance(value, list):
            return [facts_only(v) for v in value]
        return value
    c = store.connect()
    requests = []
    try:
        for row in _select_records(c, None, None, keys):
            fact = _record_facts(store, c, [], None, row, 'dynamic')
            raw = fact['current_dynamic_raw']
            if not raw:
                raise ValueError(fact['record_key'] + ' 缺少已保存交易判断')
            updates = {'首开当日结果': opening_day_result(fact['first_open_market'])}
            if '首开行情' in raw:
                updates['首开行情'] = fact['first_open_market']
            for field, value in updates.items():
                if facts_only(raw.get(field)) != facts_only(value):
                    raise ValueError(fact['record_key'] + ' 行情事实发生变化，不能只更新来源：' + field)
            updates = {k: v for k, v in updates.items() if raw.get(k) != v}
            if updates:
                item = request(fact['record_key'], updates)
                item['kind'] = 'dynamic'
                saved = c.execute('SELECT research_status,confirmation_status FROM current_dynamic_research WHERE legacy_record_key=?', (fact['record_key'],)).fetchone()
                item.update(research_status=saved['research_status'], confirmation_status=saved['confirmation_status'])
                requests.append(item)
        with store.immediate(c):
            for item in requests:
                store.write_research(item, c)
            if requests:
                c.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('statistics_export_pending','1')")
        result = {'records': len(keys), 'source_references_refreshed': len(requests),
                  'export': store.publish_pending()}
        _write_json(directory/'source-refresh.json', result)
        return result
    finally:
        c.close()


def report(store, keys, directory):
    """Render every requested row from current saved decisions, with unresolved rows explicit."""
    c=store.connect();rows=[]
    try:
        for row in sorted(_select_records(c,None,None,keys),key=lambda r:(r['event_date'] or '',r['legacy_record_key'])):
            static=json.loads(row['raw_json'])
            saved=c.execute('SELECT raw_json FROM current_dynamic_research WHERE legacy_record_key=?',(row['legacy_record_key'],)).fetchone()
            raw=json.loads(saved['raw_json']) if saved else {}
            day=raw.get('首开当日结果') or opening_day_result(_trade_market(c,row['stock_id'],row['event_date'],0))
            outcome=raw.get('买入后结果') or {}
            buy=outcome.get('是否买入')
            reason=(raw.get('首开买点') or {}).get('事实') or (raw.get('买入筛选') or {}).get('依据')
            if not saved:reason='实际封板证据仍不充分；未写成无买点，未提交交易判断'
            replenishment = static.get('补涨判断')
            hits = [v for v in static.get('补涨映射明细', []) if v.get('命中')]
            if hits:
                replenishment += '：' + '、'.join(str(v.get('股票名称') or v.get('股票代码')) + '·' + str(v.get('高标主炒')) for v in hits)
            rows.append({'序号':len(rows)+1,'一字首开日':row['event_date'],'股票':static.get('股票'),'代码':row['code'],
                         '完整属性':'、'.join(static.get('开盘啦完整属性集', [])),
                         '属性时点说明':static.get('属性时点说明', ''),
                         '补涨':replenishment,'一字压制':static.get('压制判断'),'公告污染':'是' if static.get('公告污染') else '否',
                         '主炒':static.get('唯一主炒作属性'),'是否有买点':'有' if buy is True else '无' if buy is False else '未核实',
                         '当天是否封板':'是' if day['当天是否封板'] is True else '否' if day['当天是否封板'] is False else '未核实',
                         '说明':reason,'已写回':bool(saved)})
        _write_json(directory/'current-results.json',{'records':rows})
        columns=['序号','一字首开日','股票','代码','完整属性','主炒','补涨','一字压制','公告污染','是否有买点','当天是否封板','说明']
        def cell(row, key):
            value = escape(str(row.get(key) or ''))
            if key == '完整属性':
                value = '<details><summary>查看</summary>' + value + '<p>' + escape(str(row.get('属性时点说明') or '')) + '</p></details>'
            return '<td>' + value + '</td>'
        body=''.join('<tr>'+''.join(cell(r,k) for k in columns)+'</tr>' for r in rows)
        bought=sum(r['是否有买点']=='有' for r in rows);pending=sum(not r['已写回'] for r in rows)
        html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>2024年一字首开逐笔表</title>
<style>body{font:15px system-ui;margin:24px;color:#20252b}table{border-collapse:collapse;width:100%}th,td{padding:8px;border-bottom:1px solid #ddd;text-align:left}th{position:sticky;top:0;background:#edf1f6}tr:nth-child(even){background:#fafafa}input{padding:10px;width:320px;margin:12px 0}td:last-child{max-width:530px}td:nth-child(2),td:nth-child(3){white-space:nowrap}</style>
<h1>2024年一字首开逐笔表</h1>'''
        html+=f'<p>本轮已完成静态研究的 {len(rows)} 笔；已写回 {len(rows)-pending} 笔；有买点 {bought} 笔；证据未核实 {pending} 笔。日期全部为一字首开日。当天封板只看当日收盘；“无买点”包含按当前规则排除，说明列逐笔列出原因。研究判断尚未替代用户逐笔审核，不自动加入统一交易清单。</p>'
        html+='<input id="q" placeholder="搜索股票、日期、题材或结论" oninput="document.querySelectorAll(\'tbody tr\').forEach(r=>r.hidden=!r.innerText.includes(this.value))"><table><thead><tr>'+''.join('<th>'+v+'</th>' for v in columns)+'</tr></thead><tbody>'+body+'</tbody></table></html>'
        path=directory/'2024年一字首开逐笔表.html';path.write_text(html,encoding='utf-8')
        assert html.count('<tbody>')==1 and body.count('<tr>')==len(keys) and '首板日' not in html
        lines=[f'本轮共 {len(rows)} 笔，已写回 {len(rows)-pending} 笔；有买点 {bought} 笔，另有 {pending} 笔买点尚未核实。',
               '', '“是否有买点”按现行入选、上午买点与同轮一次规则判断；当天封板只认当日收盘涨停。所有日期为一字首开日。','']
        month=None
        for r in rows:
            current=(r['一字首开日'] or '')[:7]
            if current!=month:
                lines += ['',f'**{current}**','','| 序号 | 一字首开日 | 股票 | 是否有买点 | 当天是否封板 |','|---:|---|---|---|---|']
                month=current
            lines.append('| '+' | '.join(str(r[k]) for k in ['序号','一字首开日','股票','是否有买点','当天是否封板'])+' |')
        (directory/'2024年一字首开逐笔表.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return {'rows':len(rows),'saved':len(rows)-pending,'pending':pending,'bought':bought,'path':str(path.resolve())}
    finally:c.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('phase',choices=['prepare','scan','fetch','evaluate','commit','report','refresh-facts'])
    parser.add_argument('--batch',required=True)
    parser.add_argument('--buy-day-only',action='store_true',help='Only evaluate the opening day; do not require next-day or exit results')
    parser.add_argument('--commit-resolved',action='store_true',help='Save independent resolved rounds only; never publish unresolved rows as decisions')
    args=parser.parse_args(); store=ResearchStore(Path.cwd()); directory=store.root/args.batch
    keys=_read_json(directory/'batch.json')['record_keys']
    if args.phase=='prepare': result=prepare(store,keys,directory)
    elif args.phase=='report':result=report(store,keys,directory)
    elif args.phase=='refresh-facts':result=refresh_facts(store,keys,directory)
    elif args.phase=='scan':result=scan(store,keys,directory)
    elif args.phase in ('evaluate','commit'):result=evaluate(store,keys,directory,args.phase=='commit',args.buy_day_only,args.commit_resolved)
    else:
        from .events import acquire_market_facts
        result=acquire_market_facts(store,_read_json(directory/'scan.json')['pairs'],kinds=('snapshot','details'))
        _write_json(directory/'market-acquisition.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('records','results','pairs')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
