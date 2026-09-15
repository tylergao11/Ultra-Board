"""股票日价格唯一存储。年行情和每日查询文件只保存映射。"""
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_DIR = ROOT / 'data' / 'stock_prices'
DB = ROOT / 'data' / 'stock_prices.sqlite3'  # migration source only

def connect(year, *, readonly=False):
    path = DB_DIR / f'{int(year)}.sqlite3'
    if readonly:
        return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=60)
    DB_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.execute('CREATE TABLE IF NOT EXISTS quotes(code TEXT, day TEXT, opening REAL, closing REAL, PRIMARY KEY(code,day))')
    db.execute('CREATE TABLE IF NOT EXISTS years(code TEXT, year INTEGER, meta TEXT, PRIMARY KEY(code,year))')
    db.execute('CREATE TABLE IF NOT EXISTS daily(day TEXT, code TEXT, extra TEXT, PRIMARY KEY(day,code))')
    return db

def kind(path):
    p = Path(path).resolve()
    try:
        parts = p.relative_to(ROOT / 'data').parts
    except ValueError:
        return None
    if len(parts) == 4 and parts[:2] == ('ths', 'prices_unadjusted') and p.suffix == '.json':
        return 'year'
    if len(parts) == 3 and parts[:2] == ('replay', 'prices') and p.suffix == '.json':
        return 'day'
    return None

def write(path, body):
    mode = kind(path)
    if not mode or '$price_store' in body:
        return body
    db = connect(body['year'] if mode == 'year' else body['date'][:4])
    try:
        with db:
            if mode == 'year':
                code, year = body['code'], int(body['year'])
                for day, bar in body['bars'].items():
                    db.execute('INSERT OR REPLACE INTO quotes VALUES(?,?,?,?)', (code, day, bar['open'], bar['close']))
                meta = {k:v for k,v in body.items() if k not in ('raw_response','bars')}
                db.execute('INSERT OR REPLACE INTO years VALUES(?,?,?)', (code,year,json.dumps(meta,ensure_ascii=False,separators=(',',':'))))
                return {'$price_store':'year','code':code,'year':year}
            day = body['date']
            db.execute('DELETE FROM daily WHERE day=?', (day,))
            for original in body['stocks']:
                row = dict(original); code = row['code']
                if row.get('open') is not None and row.get('close') is not None:
                    found = db.execute('SELECT opening,closing FROM quotes WHERE code=? AND day=?',(code,day)).fetchone()
                    expected = (row['open'],row['close'])
                    if found is not None and found != expected:
                        raise ValueError(f'{day} {code}: 每日价格与唯一价格不一致')
                    db.execute('INSERT OR IGNORE INTO quotes VALUES(?,?,?,?)',(code,day,*expected))
                    row.pop('open'); row.pop('close')
                previous = row.get('previous_trade_date')
                if previous and row.get('previous_trade_close') is not None:
                    found = previous_close(db, code, previous, day)
                    if found and found[0] == row['previous_trade_close']:
                        row.pop('previous_trade_close')
                # 只移除能够无损重建的计算值。
                if original.get('open') and original.get('reference_price'):
                    calculated = round((original['open']/original['reference_price']-1)*100,4)
                    if row.get('open_pct') == calculated: row.pop('open_pct')
                if original.get('open') and original.get('previous_trade_close'):
                    calculated = round((original['open']/original['previous_trade_close']-1)*100,4)
                    if row.get('open_pct_previous_close') == calculated: row.pop('open_pct_previous_close')
                row.pop('code',None)
                if row.get('date') == day: row.pop('date')
                db.execute('INSERT INTO daily VALUES(?,?,?)',(day,code,json.dumps(row,ensure_ascii=False,separators=(',',':'))))
            return {'$price_store':'day','date':day}
    finally:
        db.close()

def read(ref):
    db = connect(ref['year'] if ref['$price_store'] == 'year' else ref['date'][:4], readonly=True)
    try:
        if ref['$price_store'] == 'year':
            code,year = ref['code'],ref['year']
            found = db.execute('SELECT meta FROM years WHERE code=? AND year=?',(code,year)).fetchone()
            if not found: raise ValueError('缺少年行情映射')
            body = json.loads(found[0])
            body['bars'] = {day:{'open':opening,'close':closing} for day,opening,closing in db.execute(
                'SELECT day,opening,closing FROM quotes WHERE code=? AND day>=? AND day<=? ORDER BY day',
                (code,f'{year}-01-01',f'{year}-12-31'))}
            return body
        day=ref['date']; stocks=[]
        for code,extra,opening,closing in db.execute('SELECT d.code,d.extra,q.opening,q.closing FROM daily d LEFT JOIN quotes q ON q.code=d.code AND q.day=d.day WHERE d.day=? ORDER BY d.code',(day,)):
            row={'code':code,'date':day,**json.loads(extra)}
            if opening is not None: row.update(open=opening,close=closing)
            if row.get('previous_trade_date') and 'previous_trade_close' not in row:
                found=previous_close(db,code,row['previous_trade_date'],day)
                if found: row['previous_trade_close']=found[0]
            if opening and row.get('reference_price') and 'open_pct' not in row:
                row['open_pct']=round((opening/row['reference_price']-1)*100,4)
            if opening and row.get('previous_trade_close') and 'open_pct_previous_close' not in row:
                row['open_pct_previous_close']=round((opening/row['previous_trade_close']-1)*100,4)
            stocks.append(row)
        return {'date':day,'stocks':stocks}
    finally:
        db.close()


def previous_close(db, code, previous, day):
    if previous[:4] == day[:4]:
        return db.execute('SELECT closing FROM quotes WHERE code=? AND day=?',(code,previous)).fetchone()
    path=DB_DIR / f'{int(previous[:4])}.sqlite3'
    if not path.exists():return None
    other=connect(previous[:4],readonly=True)
    try:return other.execute('SELECT closing FROM quotes WHERE code=? AND day=?',(code,previous)).fetchone()
    finally:other.close()
