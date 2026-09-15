"""将价格迁移至唯一股票日表，逐文件回读验证，再用映射替换副本。"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ultraboard import price_store

def atomic(path, body):
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(body,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    tmp.replace(path)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    files=sorted((ROOT/'data/ths/prices_unadjusted').glob('*/*.json'))
    files+=sorted((ROOT/'data/replay/prices').glob('*.json'))
    if not args.apply:
        print(json.dumps({'files':len(files),'bytes':sum(p.stat().st_size for p in files)}));return
    count=0;before=0;after=0
    for i,path in enumerate(files,1):
        doc=json.loads(path.read_text(encoding='utf-8-sig'))
        if '$price_store' in doc: continue
        reference=price_store.write(path,doc)
        restored=price_store.read(reference)
        if reference['$price_store']=='year':
            if restored['bars']!=doc['bars']:raise ValueError(f'{path}: 年价格迁移不一致')
        else:
            old={x['code']:x for x in doc['stocks']};new={x['code']:x for x in restored['stocks']}
            if old!=new:raise ValueError(f'{path}: 日查询迁移不一致')
        before+=path.stat().st_size
        atomic(path,reference)
        after+=path.stat().st_size;count+=1
        if i%1000==0 or i==len(files):print(json.dumps({'processed':i,'total':len(files),'verified':count}),flush=True)
    # 除权页面已解析为分红记录；其查询只需要解析后的记录和来源信息。
    for path in (ROOT/'data/ths/corporate_actions').glob('*.json'):
        doc=json.loads(path.read_text(encoding='utf-8-sig'))
        if 'raw_html' in doc and doc.get('dividend_rows') and 'ex_dates' in doc:
            before+=path.stat().st_size
            doc.pop('raw_html');atomic(path,doc);after+=path.stat().st_size
    from ultraboard.kaipanla.query import _read
    from ultraboard.market_storage import compact, expand
    for path in (ROOT/'data/replay/market').glob('*.json'):
        original=_read(path)
        saved=compact(original)
        if expand(saved)!=original:raise ValueError(f'{path}: market mismatch')
        before+=path.stat().st_size
        atomic(path,saved);after+=path.stat().st_size
    for path in (ROOT/'data/dabanke/raw').glob('*.json'):
        doc=json.loads(path.read_text(encoding='utf-8-sig'))
        if 'html' not in doc:continue
        target=ROOT/'data/replay/market'/path.name
        if not target.exists():continue
        market=_read(target)
        if market.get('date')!=doc.get('date') or not market.get('stocks'):
            raise ValueError(f'{path}: invalid market reference')
        before+=path.stat().st_size
        atomic(path,{k:v for k,v in doc.items() if k!='html'} | {'market_ref':str(target.relative_to(ROOT)).replace('\\','/')})
        after+=path.stat().st_size
    report={'files':count,'before_bytes':before,'mapping_bytes':after,'price_database_bytes':sum(p.stat().st_size for p in price_store.DB_DIR.glob('*.sqlite3'))}
    atomic(ROOT/'data/replay/fact_cleanup_report.json',report)
    print(json.dumps(report),flush=True)

if __name__=='__main__':main()
