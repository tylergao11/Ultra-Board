"""Audit every current entry against observed first buy/open times."""
import hashlib
import json
from datetime import datetime
from .system import SHANGHAI
from .batch import _trade_market
from .buy_seal import observe, seconds, clock, morning_buy


def classify(one, buy_time, break_time, time_window=None):
    keep, reason = morning_buy(dict(buy=True,one=one,time=buy_time,broken=break_time,time_window=time_window,reason=None))
    if keep is None:
        raise ValueError('First actual buy time is unresolved')
    return keep, reason


def audit(store, commit=False):
    c=store.connect(); records=[]
    reviews={}
    for p in sorted((store.root/'data/research').glob('*-buy-seal/reviewed-observations.json')):
        if p.exists():reviews.update(json.loads(p.read_text(encoding='utf-8')))
    try:
        for row in c.execute('SELECT * FROM current_dynamic_research').fetchall():
            raw=json.loads(row['raw_json'])
            if not raw.get('当前统一交易清单'):continue
            key=row['legacy_record_key'];day=raw['首开买点']['买入日期']
            sid=c.execute('SELECT id FROM stocks WHERE code=?',(key[:6],)).fetchone()[0]
            m=_trade_market(c,sid,day,0);o=observe(m)
            intervals=[v for e in m['event']['events'] if e['event_type']=='limit_intervals' for v in e['value']['intervals']]
            buy=o['time'];broken=o['broken'];sources=list(o['sources'])
            if not o['one'] and intervals:
                buy=min(seconds(v['time']) for v in intervals)
            if buy is None:
                paths=[store.root/p for p in reviews.get(key,{}).get('sources',[])]
                paths+=list((store.root/'data/research/afternoon-buy-audit/sources').glob(f'*{day}.json'))
                for path in paths:
                    data=json.loads(path.read_text(encoding='utf-8'))
                    for fact in data.get('response',{}).get('data',[]):
                        if fact.get('symbol','')[:6]!=key[:6]:continue
                        def stamp(field):
                            value=fact.get(field)
                            if not value:return None
                            dt=datetime.fromtimestamp(value,SHANGHAI)
                            if dt.date().isoformat()!=day:raise ValueError('Wrong-date time evidence')
                            return dt.hour*3600+dt.minute*60+dt.second
                        broken=stamp('first_break_limit_up')
                        last=stamp('last_limit_up')
                        if fact.get('break_limit_up_times')==1 and broken is not None and last is not None and last>broken:
                            buy=last
                        sources.append(path.relative_to(store.root).as_posix())
            window=(raw.get('首开买点') or {}).get('买点时间区间')
            keep,basis=classify(o['one'],buy,broken,[seconds(v) for v in window] if window else None)
            name=json.loads(c.execute('SELECT raw_json FROM current_static_research WHERE legacy_record_key=?',(key,)).fetchone()[0])['股票']
            records.append({'记录键':key,'股票':name,'买入日期':day,'一字开盘':o['one'],
                            '首次开板':clock(broken),'首次买点':clock(buy),'保留':keep,'依据':basis,'来源':sorted(set(sources))})
        if commit:
            with store.immediate(c):
                for item in records:
                    key=item['记录键'];updates={'买点时段核验':item}
                    if not item['保留']:
                        updates.update({'当前统一交易清单':False,'固定样本版本':None,'本轮逐笔审核统计':None,'卖出核验':None,
                            '用户逐笔审核':{'结论':'不买','依据':item['依据'],'来源':'用户确认开板超10分钟买点全部剔除'},
                            '首开买点':{'是否买入':False,'结果':'不买','依据':item['依据']},'买入后结果':{'是否买入':False}})
                        old=json.loads(c.execute('SELECT raw_json FROM current_dynamic_research WHERE legacy_record_key=?',(key,)).fetchone()[0])
                        if old.get('公告扩展核验'):
                            f=dict(old['公告扩展核验']);f.update(excluded=True,exclude_reason=item['依据'],review_status='按现行10分钟交易时间回封规则排除');updates['公告扩展核验']=f
                    digest=hashlib.sha256(json.dumps(updates,sort_keys=True).encode()).hexdigest()
                    store.write_research({'request_id':'morning-audit-'+digest,'record_key':key,'kind':'dynamic','confirmation_status':'user_confirmed','updates':updates},c)
        return {'检查笔数':len(records),'剔除笔数':sum(not r['保留'] for r in records),'保留笔数':sum(r['保留'] for r in records),'记录':records}
    finally:c.close()
