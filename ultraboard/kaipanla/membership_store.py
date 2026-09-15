"""按交易日、股票代码存一次成员关系；板块查询是派生视图。"""
import json
import os
from functools import lru_cache
from pathlib import Path
from threading import RLock

ROOT = Path(__file__).resolve().parents[2] / 'data' / 'kaipanla' / 'stock_memberships'
LOCK = RLock()

@lru_cache(maxsize=8)
def load(day):
    path = ROOT / f'{day}.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None

def save(day, body):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / f'{day}.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(body, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    os.replace(tmp, path)
    load.cache_clear()

def snapshot(day, plate):
    body = load(day)
    if body is None or plate not in body['plates']:
        return None
    meta = body['plates'][plate]
    codes = [code for code, plates in body['stocks'].items() if plate in plates]
    if len(codes) != meta['member_count']:
        raise ValueError(f'{day} {plate}: 成员关系数量不一致')
    return {'date': day, 'plate_id': plate, 'provider': 'kaipanla',
            'member_count': len(codes), 'members': [{'code': c} for c in codes],
            'membership_note': '历史成员为供应商补采返回版本。',
            'historical_membership_verified': False}

def put(day, plate, data):
    with LOCK:
        body = load(day) or {'schema': 1, 'date': day, 'source': 'kaipanla', 'stocks': {}, 'plates': {}}
        codes = {r['code'] for r in data['members']}
        for code, plates in body['stocks'].items():
            if plate in plates and code not in codes:
                plates.remove(plate)
        for code in sorted(codes):
            ids = body['stocks'].setdefault(code, [])
            if plate not in ids:
                ids.append(plate); ids.sort()
        body['plates'][plate] = {'member_count': len(codes), 'captured_at': data.get('captured_at')}
        save(day, body)
