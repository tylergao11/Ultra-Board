"""On-demand yearly daily bars for researched stocks and their named peers."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import time
from urllib.request import Request, urlopen

from .system import json_text, price_milli
from .network import retry_call


def _codes(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"股票代码", "code", "stock_code"} and re.fullmatch(r"\d{6}", str(child)):
                found.add(str(child))
            elif isinstance(child, (dict, list)):
                found.update(_codes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_codes(child))
    return found


def daily_file_identity(path):
    if path.parent.name == 'sina_history' and re.fullmatch(r'\d{6}\.json',path.name):
        return path.stem, 'sina_history'
    if path.parent.name == 'ths_kline' and re.fullmatch(r'\d{6}-\d{4}-00\.js',path.name):
        return path.name[:6], 'ths_kline'
    return None


def read_daily_file(path):
    identity = daily_file_identity(path)
    if not identity:
        raise ValueError(f'unsupported daily source: {path}')
    return parse_daily_text(path.read_text(encoding='utf-8'), identity[1])


def parse_daily_text(text, source_type):
    if source_type == 'sina_history':
        doc = json.loads(text)
        if 'CN_MarketDataService.getKLineData' not in doc.get('action',''):
            raise ValueError('unknown price adjustment mode')
        bars = [[r['day'].replace('-',''),r['open'],r['high'],r['low'],r['close']]
                for r in doc['records']]
    else:
        match = re.search(r'\((\{.*\})\)\s*;?\s*$',text,re.S)
        if not match:
            raise ValueError('invalid THS daily response')
        bars = [r.split(',') for r in json.loads(match.group(1))['data'].split(';') if r]
    seen = set()
    for row in bars:
        if len(row)<5 or not re.fullmatch(r'20\d{6}',row[0]) or row[0] in seen:
            raise ValueError('invalid or duplicate daily date')
        from datetime import datetime
        datetime.strptime(row[0],'%Y%m%d')
        prices = [price_milli(v) for v in row[1:5]]
        if any(v is None or v<=0 for v in prices) or not (prices[2]<=min(prices[0],prices[3])<=max(prices[0],prices[3])<=prices[1]):
            raise ValueError(f'invalid OHLC on {row[0]}')
        seen.add(row[0])
    if not bars:
        raise ValueError('empty daily response')
    return sorted(bars)


def replace_daily_source(path, text, source_type):
    parse_daily_text(text, source_type)
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_suffix(path.suffix + '.new')
    try:
        staging.write_text(text, encoding='utf-8')
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def import_daily_file(store, connection, path, years):
    code, source_type = daily_file_identity(path)
    bars = read_daily_file(path)
    stock = connection.execute('SELECT id FROM stocks WHERE code=?',(code,)).fetchone()
    if not stock:
        raise ValueError('stock identity missing')
    evidence = store.register_evidence_path(path,connection)
    previous = None
    count = 0
    for values in bars:
        prices = [price_milli(v) for v in values[1:5]]
        if values[0][:4] in years:
            date = f'{values[0][:4]}-{values[0][4:6]}-{values[0][6:8]}'
            connection.execute('DELETE FROM daily_market WHERE stock_id=? AND trade_date=? AND source_type=?',(stock[0],date,source_type))
            connection.execute("""INSERT INTO daily_market(stock_id,trade_date,source_type,price_mode,
                open_milli,high_milli,low_milli,close_milli,previous_close_milli,evidence_file_id,raw_json)
                VALUES(?,?,?,'unadjusted',?,?,?,?,?,?,?)""",
                (stock[0],date,source_type,*prices,previous,evidence,json_text({'values':values})))
            connection.execute("""INSERT INTO trading_days(trade_date,is_trading_day,calendar_source,price_coverage)
                VALUES(?,1,?,1) ON CONFLICT(trade_date) DO UPDATE SET price_coverage=1""",(date,source_type))
            count += 1
        previous = prices[3]
    return count


def research_price_needs(connection, record_keys=None, from_date=None, to_date=None, following_days=0):
    selected = set(record_keys) if record_keys is not None else None
    from datetime import date
    calendar = [r[0] for r in connection.execute(
        "SELECT trade_date FROM trading_days WHERE is_trading_day=1 AND trade_date<=? ORDER BY trade_date",
        (date.today().isoformat(),))] if following_days else []
    needed = {}
    matched = set()
    for row in connection.execute("""SELECT r.legacy_record_key,r.main_theme,r.raw_json,s.code,l.focus_date,f.event_date
            FROM current_static_research r JOIN first_open_events f ON f.id=r.first_open_event_id
            JOIN launch_rounds l ON l.id=f.launch_round_id JOIN stocks s ON s.id=l.stock_id"""):
        if selected is not None and row['legacy_record_key'] not in selected:
            continue
        if selected is None and not row['main_theme']:
            continue
        if (from_date and row['focus_date']<from_date) or (to_date and row['focus_date']>to_date):
            continue
        matched.add(row['legacy_record_key'])
        raw = json.loads(row['raw_json'])
        codes = {row['code']} | _codes(raw.get('首开潜在竞争对手事实清单',[])) | _codes(raw.get('同题材PK核验明细',[]))
        event = row['event_date'] or row['focus_date']
        required = {row['focus_date'], event}
        if following_days:
            previous = [day for day in calendar if day<event]
            following = [day for day in calendar if day>event][:following_days]
            if previous:
                required.add(previous[-1])
            if following:
                required.update(following)
        for code in codes:
            for date in required:
                needed.setdefault((code,date[:4]),set()).add(date)
    if selected is not None and selected-matched:
        raise KeyError('unmatched record keys: '+','.join(sorted(selected-matched)))
    return needed, len(matched)


def ensure_research_prices(store, record_keys=None, from_date=None, to_date=None, following_days=0):
    started = time.perf_counter()
    connection = store.connect()
    try:
        needed, selected_count = research_price_needs(connection,record_keys,from_date,to_date,following_days)
        def coverage():
            covered = {}
            for r in connection.execute("""SELECT s.code,d.trade_date FROM daily_market d JOIN stocks s ON s.id=d.stock_id
                WHERE d.source_type IN ('ths_kline','sina_history') AND d.price_mode='unadjusted'
                AND d.open_milli IS NOT NULL AND d.high_milli IS NOT NULL
                AND d.low_milli IS NOT NULL AND d.close_milli IS NOT NULL"""):
                key = (r['code'],r['trade_date'][:4])
                if key in needed:
                    covered.setdefault(key,set()).add(r['trade_date'])
            return covered
        suspended = {}
        for r in connection.execute("""SELECT s.code,i.trade_date,e.path FROM intraday_events i
            JOIN stocks s ON s.id=i.stock_id JOIN evidence_files e ON e.id=i.evidence_file_id
            WHERE i.event_type='suspended'"""):
            key = (r['code'],r['trade_date'][:4])
            if key in needed and r['trade_date'] in needed[key]:
                suspended.setdefault(key,{})[r['trade_date']] = r['path']
        covered = coverage()
        pending = [(code,year,max(dates)) for (code,year),dates in needed.items()
                   if dates-covered.get((code,year),set())-set(suspended.get((code,year),{}))]
        result = {'records':selected_count,'stock_years':len(needed),'reused':len(needed)-len(pending),
                  'downloaded':0,'imported_rows':0,'errors':[]}
        def download(item):
            code,year,date = item
            sina = store.root/'data/price_checks/sina_history'/f'{code}.json'
            if sina.exists():
                document = json.loads(sina.read_text(encoding='utf-8'))
                if 'CN_MarketDataService.getKLineData' in document.get('action',''):
                    records = [r for r in document.get('records',[]) if r['day'].startswith(year)]
                    if records and needed[(code,year)] <= {r['day'] for r in records}:
                        bars = [[r['day'].replace('-',''),r['open'],r['high'],r['low'],r['close']] for r in records]
                        return code,year,sina,bars,False,'sina_history'
            path = store.root/'data/price_checks/ths_kline'/f'{code}-{year}-00.js'
            old = store.root/'data/research/buy_points_2026/ths_kline'/path.name
            cached = path if path.exists() else old
            text = cached.read_text(encoding='utf-8') if cached.exists() else ''
            def parse(text):
                match = re.search(r'\((\{.*\})\)\s*;?\s*$', text, re.S)
                if not match:
                    return []
                return [r.split(',') for r in json.loads(match.group(1)).get('data','').split(';')
                        if re.match(r'^20\d{6},',r)]
            bars = parse(text)
            fetched = False
            if not {d.replace('-','') for d in needed[(code,year)]} <= {r[0] for r in bars}:
                url = f'https://d.10jqka.com.cn/v6/line/hs_{code}/00/{year}.js'
                request = Request(url,headers={'Referer':f'https://stockpage.10jqka.com.cn/{code}/','User-Agent':'Mozilla/5.0'})
                def request_ths():
                    with urlopen(request,timeout=20) as response:
                        body=response.read().decode('utf-8')
                    parse_daily_text(body,'ths_kline')
                    return body
                try:
                    text,_=retry_call(request_ths)
                except Exception:
                    market = 'sh' if code.startswith(('5','6','9')) else 'sz'
                    alternate = f'https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData?symbol={market}{code}&scale=240&ma=no&datalen=1023'
                    def request_sina():
                        with urlopen(Request(alternate,headers={'User-Agent':'Mozilla/5.0'}),timeout=20) as response:
                            records=json.loads(response.read())
                        if not isinstance(records,list) or not records:raise ValueError('daily response empty')
                        document={'code':code,'provider':'sina','action':'CN_MarketDataService.getKLineData, scale=240, unadjusted','records':records}
                        parse_daily_text(json_text(document),'sina_history')
                        return document
                    document,_=retry_call(request_sina)
                    replace_daily_source(sina,json_text(document),'sina_history')
                    bars=[[r['day'].replace('-',''),r['open'],r['high'],r['low'],r['close']] for r in document['records'] if r['day'].startswith(year)]
                    if not bars:raise ValueError('requested year absent from daily bar response')
                    return code,year,sina,bars,True,'sina_history'
                bars = parse(text)
                if not bars:
                    raise ValueError('daily bar response has no data')
                replace_daily_source(path,text,'ths_kline')
                cached = path
                fetched = True
            return code,year,cached,bars,fetched,'ths_kline'
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(download,item):item for item in pending}
            for future in as_completed(futures):
                item = futures[future]
                try:
                    code,year,path,bars,fetched,source_type = future.result()
                    imported = import_daily_file(store, connection, path, {year})
                    connection.commit()
                    result['downloaded'] += int(fetched)
                    result['imported_rows'] += imported
                    if bars[-1][0] < item[2].replace('-',''):
                        result.setdefault('coverage_notes',[]).append({'code':code,'year':year,'last_date':bars[-1][0], 'requested_date':item[2]})
                except Exception as exc:
                    connection.rollback()
                    result['errors'].append({'code':item[0],'year':item[1],'error':str(exc)})
        after = coverage()
        result['gaps'] = [{'code':code,'year':year,'dates':sorted(dates-after.get((code,year),set())-set(suspended.get((code,year),{})))}
                          for (code,year),dates in needed.items() if dates-after.get((code,year),set())-set(suspended.get((code,year),{}))]
        result['non_trading'] = [{'code':code,'year':year,'dates':days} for (code,year),days in suspended.items()]
        result['complete'] = not result['errors'] and not result['gaps']
        result['elapsed_seconds'] = round(time.perf_counter()-started,3)
        return result
    finally:
        connection.close()
