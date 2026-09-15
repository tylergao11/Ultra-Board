"""市场事实保留一次；时间格式、触板布尔值和来源文字由读取层展开。"""
from datetime import datetime
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Shanghai')
SOURCE_KEYS=('provider','source_url','source_path','first_limit_time_source')
DERIVED=('has_seal_action','has_reseal','seal_action_basis','reseal_basis','has_limit_attack',
         'first_limit_attack_ts','first_limit_attack_time','first_limit_attack_session','first_limit_attack_basis')

def expand(body):
    if body.get('_market_storage')!=1:return body
    result={k:v for k,v in body.items() if k not in ('_market_storage','sources','stocks')}
    rows=[]
    for saved in body['stocks']:
        row=dict(saved)
        idx=row.pop('$source',None)
        if idx is not None:row.update(body['sources'][idx])
        closed,failed=row.get('closed_limit'),row.get('failed_limit')
        action=True if closed or failed else (False if closed is False and failed is False else None)
        count=row.get('open_count');first=row.get('first_limit_ts')
        time=datetime.fromtimestamp(first,TZ).strftime('%H:%M:%S') if first else None
        defaults={'has_seal_action':action,'has_limit_attack':action,
                  'has_reseal':False if action is False else (count>=2 or (count>=1 and closed is True)) if isinstance(count,int) and count>=0 else None,
                  'seal_action_basis':'source_limit_or_failed_limit_status',
                  'reseal_basis':'source_open_count_and_closing_status' if isinstance(count,int) else 'missing_open_count',
                  'first_limit_attack_ts':first if action and first else None,
                  'first_limit_attack_time':time,
                  'first_limit_attack_session':('auction' if time<'09:30:00' else 'continuous') if time else None,
                  'first_limit_attack_basis':'source_first_limit_time' if first else ('missing_first_limit_time' if action else 'no_limit_attack')}
        for k,v in defaults.items():row.setdefault(k,v)
        rows.append(row)
    result['stocks']=rows
    return result

def compact(body):
    if body.get('_market_storage')==1:return body
    sources=[];rows=[]
    for original in body['stocks']:
        row=dict(original)
        source={k:row.pop(k) for k in SOURCE_KEYS if k in row}
        if source:
            if source not in sources:sources.append(source)
            row['$source']=sources.index(source)
        probe=expand({'_market_storage':1,'sources':sources,'stocks':[{k:v for k,v in row.items() if k not in DERIVED}]})['stocks'][0]
        for k in DERIVED:
            if k in row and row[k]==probe.get(k):row.pop(k)
        rows.append(row)
    result={**body,'_market_storage':1,'sources':sources,'stocks':rows}
    if expand(result)!=body:raise ValueError('行情无损映射检查失败')
    return result
