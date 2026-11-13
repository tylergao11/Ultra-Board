"""Import observed limit-board intervals from saved provider responses."""
import json
import re
from datetime import datetime
from .system import SHANGHAI, json_text, price_milli


HISTORY_URL='https://apphis.longhuvip.com/w1/api/index.php'
HISTORY_HEADERS={
    'User-Agent':'Dalvik/2.1.0 (Linux; U; Android 14; V2178A Build/UP1A.231005.007)',
    'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
}


def import_suspension_file(store, connection, path):
    """Import reviewed non-trading dates with local announcement evidence."""
    document = json.loads(path.read_text(encoding='utf-8'))
    if document.get('kind') != 'reviewed_suspensions' or not isinstance(document.get('records'), list):
        raise ValueError('invalid suspension document')
    prepared = []
    for item in document['records']:
        code = item['code']
        if not re.fullmatch(r'\d{6}', code) or not item.get('basis') or not item.get('sources'):
            raise ValueError('suspension requires stock, basis and evidence')
        sources = []
        for value in item['sources']:
            source = (store.root / value).resolve()
            source.relative_to(store.root.resolve())
            if not source.is_file() or source.stat().st_size == 0:
                raise ValueError(f'missing suspension evidence: {value}')
            sources.append(source)
        for day in item['dates']:
            datetime.strptime(day, '%Y-%m-%d')
            stock = connection.execute('SELECT id FROM stocks WHERE code=?', (code,)).fetchone()
            if not stock:
                raise ValueError(f'unknown stock: {code}')
            if connection.execute("""SELECT 1 FROM daily_market WHERE stock_id=? AND trade_date=?
                AND open_milli>0 AND high_milli>0 AND low_milli>0 AND close_milli>0""", (stock[0], day)).fetchone():
                raise ValueError(f'{code} {day}: suspension conflicts with saved OHLC')
            prepared.append((stock[0], day, item, sources))
    store.register_evidence_path(path, connection)
    for sid, day, item, sources in prepared:
        ids = [store.register_evidence_path(source, connection) for source in sources]
        connection.execute("DELETE FROM intraday_events WHERE stock_id=? AND trade_date=? AND event_type='suspended'", (sid, day))
        connection.execute("""INSERT INTO intraday_events
            (stock_id,trade_date,event_type,time_precision,value_json,evidence_file_id)
            VALUES(?,?,'suspended','day',?,?)""", (sid, day, json_text(item), ids[0]))
    return len(prepared)


def _valid_history(data, code, day, kind):
    if not isinstance(data,dict) or str(data.get('errcode','0'))!='0' or str(data.get('code'))!=code or str(data.get('day'))!=day.replace('-',''):
        return False
    if kind=='trend':
        return isinstance(data.get('trend'),list) and bool(data['trend']) and all(
            isinstance(v,(list,tuple)) and len(v)>=2 and re.fullmatch(r'\d{2}:\d{2}',str(v[0])) and (price_milli(v[1]) or 0)>0 for v in data['trend'])
    real=data.get('real')
    if not isinstance(real,dict):return False
    prices=[price_milli(real.get(k)) for k in ['open_px','high_px','low_px','last_px','up_px','down_px']]
    return all(v is not None and v>0 for v in prices) and prices[2]<=min(prices[0],prices[3])<=max(prices[0],prices[3])<=prices[1]


def fetch_stock_day(store, code, day, kind='snapshot', refresh=False):
    """Exact code/date API. Validate the provider identity before accepting cache or response."""
    from .network import retry_call, request_bytes
    if not re.fullmatch(r'\d{6}',code):raise ValueError('股票代码须为6位数字')
    datetime.strptime(day,'%Y-%m-%d')
    if kind not in ('snapshot','trend'):raise ValueError('unsupported historical data kind')
    path=store.root/'data/kaipanla/stock_history'/day/(code+('-trend' if kind=='trend' else '')+'.json')
    params={'a':'GetStockPanKou' if kind=='snapshot' else 'GetStockTrend','c':'StockL2History',
            'StockID':code,'Day':day,'apiv':'w43','PhoneOSNew':'1'}
    def valid(data):
        return _valid_history(data,code,day,kind)
    def facts(data):
        if kind=='trend':return {'precision':'minute','points':len(data['trend'])}
        real=data['real']
        return {key:real.get(field) for key,field in [('open','open_px'),('high','high_px'),('low','low_px'),
                ('close','last_px'),('limit_up','up_px'),('limit_down','down_px')]} | {'previous_close':data.get('preclose_px')}
    if path.exists() and not refresh:
        try:
            cached=json.loads(path.read_text(encoding='utf-8')).get('response')
            if valid(cached):
                return {'path':str(path),'code':code,'date':day,'kind':kind,'facts':facts(cached),'cached':True,'attempts':0,'retry_wait_seconds':0,'elapsed_seconds':0}
        except (ValueError,OSError):pass
    def request():
        payload=json.loads(request_bytes(HISTORY_URL,data=params,headers=HISTORY_HEADERS,timeout=10))
        if not valid(payload):raise ValueError(f'{code} {day} {kind}: 返回代码、日期或数据内容未通过校验')
        return payload
    payload,timing=retry_call(request)
    path.parent.mkdir(parents=True,exist_ok=True)
    staging=path.with_suffix('.json.new')
    staging.write_text(json_text({'url':HISTORY_URL,'params':params,'response':payload}),encoding='utf-8')
    staging.replace(path)
    return {'path':str(path),'code':code,'date':day,'kind':kind,'facts':facts(payload),'cached':False,**timing}


def import_history_file(store,connection,path):
    document=json.loads(path.read_text(encoding='utf-8'))
    data=document.get('response',{})
    if not data and document.get('body'):
        data=json.loads(document['body'])
    code=str(data.get('code',''));value=str(data.get('day',''))
    if not re.fullmatch(r'\d{6}',code) or not re.fullmatch(r'20\d{6}',value):raise ValueError('历史行情身份无效')
    day=datetime.strptime(value,'%Y%m%d').date().isoformat()
    kind='trend' if 'trend' in data else 'snapshot'
    params=document.get('params',{})
    named=re.fullmatch(r'(\d{6})(-trend)?',path.stem)
    if (params and (str(params.get('StockID'))!=code or params.get('Day')!=day)) or (named and (named[1]!=code or bool(named[2])!=(kind=='trend'))) or path.parent.name!=day:
        raise ValueError(f'{code} {day}: 请求、文件路径与响应身份不一致')
    if not _valid_history(data,code,day,kind):raise ValueError(f'{code} {day}: 历史行情内容校验失败')
    sid=store.stock_id(connection,code);eid=store.register_evidence_path(path,connection)
    if isinstance(data.get('real'),dict):
        real=data['real']
        existing=connection.execute("SELECT raw_json FROM daily_market WHERE stock_id=? AND trade_date=? AND source_type='kaipanla_snapshot' AND evidence_file_id=?",(sid,day,eid)).fetchone()
        if existing and existing[0]==json_text(data):return
        connection.execute("DELETE FROM daily_market WHERE stock_id=? AND trade_date=? AND source_type='kaipanla_snapshot'",(sid,day))
        connection.execute("""INSERT INTO daily_market(stock_id,trade_date,source_type,price_mode,open_milli,high_milli,low_milli,close_milli,previous_close_milli,limit_up_milli,limit_down_milli,evidence_file_id,raw_json)
            VALUES(?,?,'kaipanla_snapshot','unadjusted',?,?,?,?,?,?,?,?,?)""",(sid,day,*[price_milli(real.get(k)) for k in ['open_px','high_px','low_px','last_px']],price_milli(data.get('preclose_px')),price_milli(real.get('up_px')),price_milli(real.get('down_px')),eid,json_text(data)))
    elif data.get('trend'):
        existing=connection.execute("SELECT value_json FROM intraday_events WHERE stock_id=? AND trade_date=? AND event_type='minute_trend' AND evidence_file_id=?",(sid,day,eid)).fetchone()
        if existing and existing[0]==json_text(data):return
        connection.execute("DELETE FROM intraday_events WHERE stock_id=? AND trade_date=? AND event_type='minute_trend' AND evidence_file_id=?",(sid,day,eid))
        connection.execute("INSERT INTO intraday_events(stock_id,trade_date,event_type,time_precision,value_json,evidence_file_id) VALUES(?,?,'minute_trend','minute',?,?)",(sid,day,json_text(data),eid))
    else:raise ValueError(f'{code} {day}: 历史行情为空')


def acquire_market_facts(store, pairs, kinds=('snapshot','trend'), refresh=False):
    from concurrent.futures import ThreadPoolExecutor,as_completed
    from pathlib import Path
    import time
    started=time.perf_counter();pairs={(str(code),day) for code,day in pairs}
    connection=store.connect()
    non_trading=[]
    try:
        with store.immediate(connection):
            for row in connection.execute("""SELECT s.code,i.stock_id,i.trade_date,e.path FROM intraday_events i
                JOIN stocks s ON s.id=i.stock_id JOIN evidence_files e ON e.id=i.evidence_file_id
                WHERE i.event_type='suspended'""").fetchall():
                pair=(row['code'],row['trade_date'])
                if pair not in pairs:continue
                non_trading.append({'code':pair[0],'date':pair[1],'source':row['path']})
                # Providers may carry forward yesterday's OHLC on suspended days.
                invalid=connection.execute("SELECT evidence_file_id FROM daily_market WHERE stock_id=? AND trade_date=? AND source_type='iwencai_daily'",(row['stock_id'],pair[1])).fetchall()
                for item in invalid:
                    connection.execute("DELETE FROM intraday_events WHERE stock_id=? AND trade_date=? AND evidence_file_id=? AND event_type<>'suspended'",(row['stock_id'],pair[1],item[0]))
                connection.execute("DELETE FROM daily_market WHERE stock_id=? AND trade_date=? AND source_type='iwencai_daily'",(row['stock_id'],pair[1]))
                pairs.discard(pair)
    finally:
        connection.close()
    jobs=sorted({(code,day,kind) for code,day in pairs for kind in kinds})
    for code,day,kind in jobs:
        if not re.fullmatch(r'\d{6}',code):raise ValueError('股票代码须为6位数字')
        datetime.strptime(day,'%Y-%m-%d')
        if kind not in {'snapshot','trend','details'}:raise ValueError('unsupported data kind')
    result={'requests':len(jobs),'downloaded':0,'reused':0,'errors':[],'results':[],'non_trading':non_trading}
    connection=store.connect();write_seconds=0
    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures={executor.submit(fetch_limit_details if kind=='details' else fetch_stock_day,store,code,day,kind,refresh):(code,day,kind) for code,day,kind in jobs}
            for future in as_completed(futures):
                code,day,kind=futures[future]
                try:
                    item=future.result();write_start=time.perf_counter()
                    if kind=='details':
                        if not import_provider_file(store,connection,Path(item['path']),{(code,day)}):
                            raise ValueError(f'{code} {day}: 明细缺少有效行情字段')
                    else:
                        import_history_file(store,connection,Path(item['path']))
                    connection.commit()
                    write_seconds+=time.perf_counter()-write_start
                    result['reused' if item['cached'] else 'downloaded']+=1;result['results'].append(item)
                except Exception as exc:
                    connection.rollback()
                    from query_iwencai import ENDPOINT
                    result['errors'].append({'code':code,'date':day,'kind':kind,'url':ENDPOINT if kind=='details' else HISTORY_URL,'error':str(exc),**getattr(exc,'retry_timing',{})})
        result.update(complete=not result['errors'],write_seconds=round(write_seconds,3),elapsed_seconds=round(time.perf_counter()-started,3),
                      max_request_seconds=max((v.get('elapsed_seconds',0) for v in result['results']+result['errors']),default=0),
                      max_retry_wait_seconds=max((v.get('retry_wait_seconds',0) for v in result['results']+result['errors']),default=0))
        return result
    finally:connection.close()


def fetch_limit_details(store,code,day,kind='details',refresh=False):
    from query_iwencai import table_rows, query, signing_bundle
    def matching(rows):
        for row in rows:
            if _row_identity(row)!=(code,day):continue
            high,limit=price_milli(_field(row,'最高价:不复权')),price_milli(_field(row,'涨停价'))
            intervals=_field(row,'涨停明细数据')
            prices=[price_milli(_field(row,label)) for label in ['开盘价:不复权','最高价:不复权','最低价:不复权','收盘价:不复权']]
            if not all(v and v>0 for v in prices) or not prices[2]<=min(prices[0],prices[3])<=max(prices[0],prices[3])<=prices[1]:continue
            if intervals is not None:
                try:
                    values=json.loads(intervals) if isinstance(intervals,str) else intervals
                    if not isinstance(values,list):continue
                    for value in values:
                        start,end=_stamp(value['time']),_stamp(value.get('openTime'))
                        if str(value.get('code',''))[:6]!=code or not start or start.date().isoformat()!=day or (end and (end<start or end.date().isoformat()!=day)):
                            raise ValueError('invalid provider interval')
                except (ValueError,KeyError,TypeError):continue
                return row
            # A valid dated quote may explicitly lack board-event fields.
            # Preserve that distinction in facts.complete instead of treating
            # the response as a network failure or inventing a zero count.
            return row
        return None
    path=store.root/'data/price_checks/iwencai'/f"{code}-{day.replace('-','')}.json"
    row=None;timing={'attempts':0,'retry_wait_seconds':0,'elapsed_seconds':0};cached=False
    if path.exists() and not refresh:
        try:row=matching(table_rows(json.loads(path.read_text(encoding='utf-8')).get('response',{})))
        except (ValueError,OSError):pass
    if row is not None:cached=True
    else:
        bundle,version=signing_bundle()
        dated=datetime.strptime(day,'%Y-%m-%d').strftime('%Y年%m月%d日')
        item={'id':path.stem,'question':f'股票代码{code}，{dated}开盘价、最高价、最低价、收盘价、涨停价、跌停价、涨停明细数据、封板次数'}
        result=query(item,path.parent,bundle,version,validate=lambda rows:matching(rows) is not None,refresh=refresh)
        timing.update({k:result.get(k,0) for k in timing})
        row=matching(table_rows(json.loads(path.read_text(encoding='utf-8'))['response']))
        cached=result.get('cached',False)
    encoded=_field(row,'涨停明细数据')
    intervals=(json.loads(encoded) if isinstance(encoded,str) else encoded) or []
    count=_field(row,'封板次数')
    op,high,low,up=[price_milli(_field(row,k)) for k in ['开盘价:不复权','最高价:不复权','最低价:不复权','涨停价']]
    complete=encoded is not None and count is not None and len(intervals)==int(count)
    if high and up and high<up:
        complete=True
    if intervals and op==up and low and up and low<up and all(v.get('openTime') is None for v in intervals):complete=False
    return {'code':code,'date':day,'kind':kind,'path':str(path),'cached':cached,**timing,
            'facts':{'board_count':count,'precision':'millisecond','intervals':intervals,'complete':complete,
                     'missing_fields':([] if high and up and high<up else
                         (['封板次数'] if count is None else [])+(['封板时间序列'] if encoded is None else []))}}




def _stamp(value):
    if value in (None, '', 0):
        return None
    number = int(value)
    return datetime.fromtimestamp(number / (1000 if number>10**11 else 1), SHANGHAI)


def _field(row, label):
    return next((v for k,v in row.items() if k==label or k.startswith(label+'[')),None)


def _row_identity(row):
    code=str(row.get('股票代码',''))[:6]
    value=str(row.get('时间区间',''))
    if not re.fullmatch(r'20\d{6}',value):
        dates={d for k in row for d in re.findall(r'\[(20\d{6})\]',k)}
        value=next(iter(dates)) if len(dates)==1 else ''
    if re.fullmatch(r'\d{6}',code) and re.fullmatch(r'20\d{6}',value):
        return code,datetime.strptime(value,'%Y%m%d').date().isoformat()


def import_provider_file(store, connection, path, allowed=None):
    """One parser for automatic acquisition and daily intake; caller owns transaction."""
    from query_iwencai import table_rows
    document=json.loads(path.read_text(encoding='utf-8'))
    count=0;eid=None
    named=re.fullmatch(r'(\d{6})-(20\d{6})',path.stem)
    expected=(named[1],datetime.strptime(named[2],'%Y%m%d').date().isoformat()) if named else None
    for row in table_rows(document.get('response',{})):
        identity=_row_identity(row)
        if not identity or (allowed is not None and identity not in allowed):
            continue
        if expected and identity!=expected:
            continue
        code,day=identity
        sid=(store.stock_id(connection,code),)
        if connection.execute("SELECT 1 FROM intraday_events WHERE stock_id=? AND trade_date=? AND event_type='suspended'",(sid[0],day)).fetchone():
            raise ValueError(f'{code} {day}: announcement confirms suspension; quote rejected')
        values=[price_milli(_field(row,k)) for k in ['开盘价:不复权','最高价:不复权','最低价:不复权','收盘价:不复权','涨停价','跌停价']]
        if any(v is None or v<=0 for v in values[:4]):
            continue
        op,hi,lo,cl,up,down=values
        if not lo<=min(op,cl)<=max(op,cl)<=hi:
            raise ValueError(f'{code} {day}: invalid OHLC')
        intervals=_field(row,'涨停明细数据')
        intervals=json.loads(intervals) if isinstance(intervals,str) and intervals.startswith('[') else intervals if isinstance(intervals,list) else None
        if intervals:
            intervals=sorted(intervals,key=lambda v:int(v['time']))
            for item in intervals:
                start,end=_stamp(item['time']),_stamp(item.get('openTime'))
                if str(item.get('code',''))[:6]!=code or start.date().isoformat()!=day or (end and (end<start or end.date().isoformat()!=day)):
                    raise ValueError(f'{code} {day}: invalid interval')
        eid=eid or store.register_evidence_path(path,connection)
        connection.execute("DELETE FROM daily_market WHERE stock_id=? AND trade_date=? AND source_type='iwencai_daily'",(sid[0],day))
        connection.execute("""INSERT INTO daily_market(stock_id,trade_date,source_type,price_mode,open_milli,high_milli,low_milli,close_milli,limit_up_milli,limit_down_milli,evidence_file_id,raw_json)
            VALUES(?,?,'iwencai_daily','unadjusted',?,?,?,?,?,?,?,?)""",(sid[0],day,*values,eid,json_text(row)))
        connection.execute("""DELETE FROM intraday_events WHERE stock_id=? AND trade_date=?
            AND evidence_file_id IN (SELECT id FROM evidence_files WHERE path=?)
            AND event_type IN ('limit_summary','limit_intervals','first_touch','first_break','first_reseal')""",
            (sid[0],day,path.resolve().relative_to(store.root.resolve()).as_posix()))
        board_count=_field(row,'封板次数')
        complete=intervals is not None and board_count is not None and len(intervals)==int(board_count)
        if hi and up and hi<up:
            complete=True
        # A full-day open interval conflicts with an observed trade below limit.
        if intervals and op==up and up and lo<up and all(v.get('openTime') is None for v in intervals):
            complete=False
        events=[('limit_summary',None,{'board_count':board_count,'complete':complete})]
        if intervals:
            events.extend([('limit_intervals',None,{'intervals':intervals,'complete':complete}),('first_touch',_stamp(intervals[0]['time']),{})])
            broken=min((_stamp(v['openTime']) for v in intervals if v.get('openTime')),default=None)
            if broken:
                events.append(('first_break',broken,{}))
                reseal=min((_stamp(v['time']) for v in intervals if _stamp(v['time'])>broken),default=None)
                if reseal:events.append(('first_reseal',reseal,{}))
        for kind,moment,value in events:
            connection.execute("INSERT INTO intraday_events(stock_id,trade_date,event_type,event_time,time_precision,value_json,evidence_file_id) VALUES(?,?,?,?,?,?,?)",
                (sid[0],day,kind,moment.strftime('%H:%M:%S.%f')[:12] if moment else None,'millisecond',json_text(value),eid))
        count+=1
    return count


def ensure_trade_events(store, record_keys):
    """Read candidate/peer identity only; acquire facts without deciding trades."""
    from .market import _codes
    pairs=set()
    connection=store.connect()
    try:
        for key in record_keys:
            row=connection.execute("""SELECT s.code,r.raw_json,f.event_date
                FROM current_static_research r JOIN first_open_events f ON f.id=r.first_open_event_id
                JOIN launch_rounds l ON l.id=f.launch_round_id JOIN stocks s ON s.id=l.stock_id
                WHERE r.legacy_record_key=?""",(key,)).fetchone()
            if not row or not row['event_date']:raise ValueError(f'{key}: 首开日期缺失')
            codes={row['code']}|_codes(json.loads(row['raw_json']).get('首开潜在竞争对手事实清单',[]))
            pairs.update((code,row['event_date']) for code in codes)
    finally:connection.close()
    result=acquire_market_facts(store,pairs)
    if not result['complete']:raise RuntimeError(json_text(result))
    return result
