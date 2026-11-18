"""Date-scoped historical market acquisition; preserves existing source files."""
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from .events import HISTORY_URL, HISTORY_HEADERS, fetch_historical_messages
from .network import request_bytes, retry_call
from .system import json_text, SHANGHAI

LIVE_URL = 'https://apphq.longhuvip.com/w1/api/index.php'


def fetch_response(store, day, kind):
    datetime.strptime(day, '%Y-%m-%d')
    parameters = {'c': 'HisHomeDingPan', 'Date': day, 'Day': day,
                  'PhoneOSNew': '1', 'apiv': 'w42', 'VerSion': '5.21.0.2'}
    if kind.startswith('limit_performance_'):
        parameters.update(a='DailyLimitPerformance', PidType=kind.rsplit('_', 1)[1],
                          Order='0', st='2000', Index='0', Type='4')
    elif kind == 'sector_ladder_response':
        parameters.update(c='FuPanLa', a='GetYTFP_BKHX')
    else:
        parameters['a'] = {'sentiment': 'HisZhangFuDetail', 'expression': 'ZhangTingExpression'}[kind]
    path = store.root / 'data/kaipanla/raw' / day / (kind + '.json')
    def validate(body):
        if str(body.get('errcode', '0')) != '0':
            raise ValueError(f'{day} {kind}: {body}')
        info = body.get('info')
        observed = body.get('Date') or body.get('date') or body.get('day')
        if isinstance(info, list) and info and isinstance(info[-1], str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}', info[-1]):
            observed = info[-1]
        if kind == 'expression':
            if observed is None and isinstance(info, list) and len(info) >= 10:
                # This endpoint does not echo a date. Preserve that limitation explicitly.
                return body
            if observed == day and isinstance(body.get('list'), list) and bool(body['list']):
                return body
        if observed != day:
            raise ValueError(f'{day} {kind}: response date {observed}; keys {list(body)}')
        return body
    if path.exists():
        return validate(json.loads(path.read_text(encoding='utf-8-sig')))
    def fetch_one():
        raw = json.loads(request_bytes(HISTORY_URL, data=parameters, headers=HISTORY_HEADERS).decode('utf-8'))
        if str(raw.get('errcode', '0')) == '1020':
            now = datetime.now(SHANGHAI)
            if day == now.date().isoformat() and (now.hour, now.minute) < (15, 5):
                raise ValueError(f'{day} {kind}: trading session not closed yet')
            live_params = {'PhoneOSNew': '1', 'apiv': 'w42', 'VerSion': '5.21.0.2'}
            if kind.startswith('limit_performance_'):
                live_params.update(c='HomeDingPan', a='DailyLimitPerformance',
                                   PidType=kind.rsplit('_', 1)[1], Order='0', st='2000', Index='0', Type='4')
            elif kind == 'sector_ladder_response':
                live_params.update(c='FuPanLa', a='GetYTFP_BKHX')
            else:
                live_params.update(c='HomeDingPan',
                                   a={'sentiment': 'ZhangFuDetail', 'expression': 'ZhangTingExpression'}[kind])
            raw = json.loads(request_bytes(LIVE_URL, data=live_params, headers=HISTORY_HEADERS).decode('utf-8'))
            validated = validate(raw)
            if kind == 'expression':
                validated['_acquisition'] = dict(host='apphq', parameters=live_params, response_date_echo=True)
            return validated
        validated = validate(raw)
        if kind == 'expression':
            validated['_acquisition'] = dict(host='apphis', parameters=parameters, response_date_echo=False)
        return validated

    body, timing = retry_call(fetch_one)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json_text(body, pretty=True) + '\n', encoding='utf-8')
    return body


def normalize_pool(day, bodies):
    rows = []
    for pid, body in enumerate(bodies, 1):
        for r in body['info'][0]:
            if (len(r) < 23 or len(str(r[0])) != 6 or not r[1]
                    or datetime.fromtimestamp(r[4], SHANGHAI).date().isoformat() != day
                    or not isinstance(r[15], int) or r[15] < 1
                    or min(r[15], 5) != pid):
                raise ValueError(f'{day}: invalid pool row {r}')
            rows.append(dict(code=r[0], name=r[1], boards=r[15], boards_desc=r[18] or '',
                             theme=r[5], theme_tags_text=r[12], sector_code=r[19],
                             first_limit_ts=r[4], turnover_rate=r[14], amount=r[11],
                             price=r[21], limit_pct=r[22], is_fanbao=False, raw=r))
    if not rows or len({r['code'] for r in rows}) != len(rows):
        raise ValueError(f'{day}: empty/duplicate pool')
    return dict(date=day, count=len(rows), max_board=max(r['boards'] for r in rows),
                board_counts=dict(Counter(r['boards'] for r in rows)), stocks=rows)


def normalize_ladder(day, body):
    if not body.get('List'):
        raise ValueError(f'{day}: empty sector ladder')
    sectors, fanbao_all = [], []
    for position, s in enumerate(body['List'], 1):
        tiers, fanbao, marks = {}, [], []
        for group in s.get('TD', []):
            t = str(group['TDType'])
            for stock in group.get('Stock', []):
                item = dict(code=stock['StockID'], name=stock['StockName'], tips=stock.get('Tips') or '')
                if t == '0':
                    fanbao.append(item)
                    fanbao_all.append(dict(item, sector=s['ZSName']))
                elif t == '9':
                    marks.append(item)
                else:
                    tiers.setdefault(t, []).append(item)
        sectors.append(dict(code=s['ZSCode'], name=s['ZSName'], count=s['Count'],
                            source_position=position, source_meta={k:v for k,v in s.items() if k != 'TD'},
                            tiers=tiers, fanbao=fanbao, height_marks=marks))
    return dict(date=day, sectors=sectors, fanbao_all=fanbao_all)


def acquire_day(store, day, reconcile=False):
    folder = store.root / 'data/kaipanla/raw' / day
    saved = []
    bodies = [fetch_response(store, day, f'limit_performance_{pid}') for pid in range(1, 6)]
    pool = normalize_pool(day, bodies)
    ladder_path = folder / 'sector_ladder.json'
    if not ladder_path.exists():
        ladder = normalize_ladder(day, fetch_response(store, day, 'sector_ladder_response'))
        ladder_path.write_text(json_text(ladder, pretty=True) + '\n', encoding='utf-8')
        saved.append('sector_ladder.json')
    else:
        ladder = json.loads(ladder_path.read_text(encoding='utf-8-sig'))
        if ladder.get('date', day) != day or not ladder.get('sectors'):
            raise ValueError(f'{day}: invalid saved ladder')
    message_path = fetch_historical_messages(store, day)
    for kind in ('sentiment', 'expression'):
        fetch_response(store, day, kind)
    messages = json.loads(message_path.read_text(encoding='utf-8-sig'))
    message_rows = [r for s in messages['list'] for r in s.get('StockList', [])]
    if any(datetime.fromtimestamp(r[6], SHANGHAI).date().isoformat() != day for r in message_rows if r[6]):
        raise ValueError(f'{day}: message row date mismatch')
    path = folder / 'zt_pool.json'
    differences = []
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8-sig'))
        if old.get('date') != day:
            raise ValueError(f'{day}: saved pool date mismatch')
        previous = {r['code']:r for r in old['stocks']}
        actual = {r['code']:r for r in pool['stocks']}
        differences = [{'code':code, 'change':'missing_in_saved' if code not in previous else 'only_in_saved'}
                       for code in sorted(previous.keys() ^ actual.keys())]
        # Retain original evidence. Newly acquired raw groups contain any omitted rows.
        differences += [{'code':code,'change':'board_or_one_word_disagreement'} for code in previous.keys() & actual.keys()
                        if previous[code].get('boards') != actual[code]['boards']
                        or previous[code].get('raw', [])[16:18] != actual[code]['raw'][16:18]]
        if reconcile and differences:
            if any(d['change'] != 'missing_in_saved' for d in differences):
                raise ValueError(f'{day}: conflicting rows require evidence review: {differences}')
            old['stocks'].extend(actual[d['code']] for d in differences)
            old.update(count=len(old['stocks']), max_board=max(r['boards'] for r in old['stocks']),
                       board_counts=dict(Counter(r['boards'] for r in old['stocks'])))
            old['source_reconciliation'] = dict(source_row_count=len(actual), included_count=len(old['stocks']),
                excluded_bse_count=0, excluded_bse=[], contract='preserve every provider row; no market filtering')
            path.write_text(json_text(old, pretty=True)+'\n', encoding='utf-8')
            saved.append('zt_pool.json')
    else:
        fanbao = {r['code'] for r in ladder.get('fanbao_all', [])}
        for r in pool['stocks']:
            r['is_fanbao'] = r['code'] in fanbao
        path.write_text(json_text(pool, pretty=True) + '\n', encoding='utf-8')
        saved.append('zt_pool.json')
    return dict(date=day, status='complete', pool_count=pool['count'], message_count=len(message_rows),
                sector_count=len(ladder['sectors']), saved=saved, differences=differences)


def acquire_range(store, start, end, report, reconcile=False):
    from pathlib import Path
    from .intake import ingest_paths
    with store.connect() as c:
        days = [r[0] for r in c.execute('SELECT trade_date FROM trading_days WHERE is_trading_day=1 AND trade_date BETWEEN ? AND ? ORDER BY trade_date', (start, end))]
    results = []
    def one(day):
        try:
            return acquire_day(store, day, reconcile)
        except Exception as exc:
            return dict(date=day, status='error', error=str(exc))
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(one, days):
            results.append(result)
            print(json_text(result), flush=True)
    paths = [store.root / 'data/kaipanla/raw' / r['date'] for r in results if r['status']=='complete']
    intake = ingest_paths(store, paths)
    output = dict(start=start, end=end, days=len(days), results=results, intake=intake)
    target = Path(report)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json_text(output, pretty=True)+'\n', encoding='utf-8')
    return output


def audit_range(store, start, end, report):
    """Read-only verification against every raw group and the indexed daily pool."""
    from pathlib import Path
    result = dict(start=start, end=end, months={}, errors=[], days=0,
                  expression_date_validation='Request date retained; endpoint has no date echo.')
    with store.connect() as c:
        days = [r[0] for r in c.execute('SELECT trade_date FROM trading_days WHERE is_trading_day=1 AND trade_date BETWEEN ? AND ? ORDER BY trade_date', (start, end))]
        for day in days:
            folder = store.root / 'data/kaipanla/raw' / day
            try:
                read = lambda name: json.loads((folder / (name+'.json')).read_text(encoding='utf-8-sig'))
                groups = [read(f'limit_performance_{i}') for i in range(1,6)]
                if any(b.get('info', [None, None])[1] != day for b in groups):
                    raise ValueError('raw group date mismatch')
                expected = normalize_pool(day, groups)
                saved = read('zt_pool')
                original = {r['code']:r for r in expected['stocks']}
                actual = {r['code']:r for r in saved['stocks']}
                if saved.get('date') != day or len(actual) != len(saved['stocks']) or saved['count'] != len(actual):
                    raise ValueError('normalized pool date/count/identity mismatch')
                if original.keys() != actual.keys():
                    raise ValueError('normalized pool omitted or added provider stock')
                if any(original[k]['boards'] != actual[k]['boards'] or original[k]['raw'][16:18] != actual[k]['raw'][16:18] for k in original):
                    raise ValueError('board height/one-price facts mismatch')
                indexed = {r['code']:r['board_height'] for r in c.execute('SELECT s.code,d.board_height FROM daily_market d JOIN stocks s ON s.id=d.stock_id WHERE d.trade_date=? AND d.source_type=?', (day,'kaipanla_limit_pool'))}
                if indexed != {k:r['boards'] for k,r in actual.items()}:
                    raise ValueError('database daily pool differs from normalized source')
                messages = read('historical_messages')
                if messages.get('date') != day or not messages.get('list'):
                    raise ValueError('messages date/rows missing')
                ladder = read('sector_ladder')
                if ladder.get('date', day) != day or not ladder.get('sectors'):
                    raise ValueError('ladder date/rows missing')
                expr = read('expression')
                if read('sentiment').get('date') != day or not (expr.get('info') or (expr.get('day') == day and expr.get('list'))):
                    raise ValueError('daily overview missing')
                month = result['months'].setdefault(day[:7], dict(trading_days=0, pool_rows=0))
                month['trading_days'] += 1
                month['pool_rows'] += len(actual)
                result['days'] += 1
            except Exception as exc:
                result['errors'].append(dict(date=day,error=str(exc)))
    result['expected_days'] = len(days)
    result['passed'] = not result['errors'] and result['days'] == len(days)
    Path(report).write_text(json_text(result,pretty=True)+'\n',encoding='utf-8')
    return result
