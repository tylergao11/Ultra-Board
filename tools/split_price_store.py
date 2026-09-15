"""按年拆分价格唯一库，逐表双向比较后删除旧库，避免 Git 单文件过大。"""
import sqlite3
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ultraboard import price_store

def main():
    old=price_store.DB
    if not old.exists():return
    src=sqlite3.connect(old)
    years=[r[0] for r in src.execute('SELECT DISTINCT substr(day,1,4) FROM quotes ORDER BY 1')]
    for year in years:
        db=price_store.connect(year)
        db.execute('ATTACH DATABASE ? AS old',(str(old),))
        with db:
            for table,column in [('quotes','day'),('years','year'),('daily','day')]:
                where=f'substr({column},1,4)=?'
                db.execute(f'INSERT OR REPLACE INTO main.{table} SELECT * FROM old.{table} WHERE {where}',(year,))
                for a,b in [('main','old'),('old','main')]:
                    different=db.execute(f'SELECT * FROM {a}.{table} WHERE {where} EXCEPT SELECT * FROM {b}.{table} WHERE {where}',(year,year)).fetchone()
                    if different:raise ValueError(f'{year} {table}: mismatch')
        db.close()
        print(year,(price_store.DB_DIR/f'{year}.sqlite3').stat().st_size,flush=True)
    src.close()
    if old.resolve().parent != (ROOT/'data').resolve():raise ValueError('invalid deletion path')
    old.unlink()

if __name__=='__main__':main()
