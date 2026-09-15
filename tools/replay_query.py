"""统一离线复盘入口；本命令绝不联网或自动补采。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ultraboard.kaipanla import membership_store
from ultraboard.kaipanla.query import _read
DATA = ROOT / "data"


def read(path: Path):
    return _read(path) if path.exists() else None


def query_raw(day: str, code: str | None = None, plate: str | None = None, *, fields=None) -> dict:
    raw = DATA / "kaipanla" / "raw" / day
    paths = {"limit_pool": raw / "zt_pool.json", "ladder": raw / "limit_ladder.json",
             "reasons": raw / "history_limit_resumption.json",
             "market": DATA / "replay" / "market" / f"{day}.json",
             "prices": DATA / "replay" / "prices" / f"{day}.json"}
    if fields is not None:
        if 'catalysts' not in fields: paths.pop('reasons')
        paths.pop('ladder')
    docs = {key: read(path) for key, path in paths.items()}
    result = {"date": day, "offline": True, "sources": {key: str(p.relative_to(ROOT)) for key, p in paths.items()},
              "missing_components": [key for key, body in docs.items() if body is None]}
    stocks = {}
    for kind in ("limit_pool", "market", "prices"):
        for row in (docs[kind] or {}).get("stocks", []):
            if code is None or row["code"] == code:
                stocks.setdefault(row["code"], {"code": row["code"]})[kind] = row
    for row in (docs.get("ladder") or {}).get("StockList", []):
        if code is None or row[0] == code:
            stocks.setdefault(row[0], {"code": row[0]})["large_order_one_price_mark"] = row[6]
    for group in (docs.get("reasons") or {}).get("list", []):
        for row in group.get("StockList", []):
            if code is None or row[0] == code:
                stocks.setdefault(row[0], {"code": row[0]}).setdefault("kaipanla_catalysts", []).append({
                    "source_group_id": group.get("ZSCode"), "source_group_name": group.get("ZSName"),
                    "source_group_explanation": group.get("TCExplain"), "text": row[17] if len(row) > 17 else None,
                })
    result["stocks"] = list(stocks.values())
    relations = membership_store.load(day) if fields is None or 'plate_ids' in fields or plate else None
    if (fields is None or 'plate_ids' in fields or plate) and relations is None:
        result['missing_components'].append('stock_memberships')
    if relations:
        for stock in result['stocks']:
            stock['plate_ids'] = relations['stocks'].get(stock['code'], [])
    if plate:
        members = membership_store.snapshot(day, plate)
        if members is not None:
            codes = {x['code'] for x in members['members']}
            matched = [x for x in (docs['limit_pool'] or {}).get('stocks', []) if x['code'] in codes]
            result['breadth'] = {'date': day, 'plate_id': plate,
                                 'member_count': len(codes),
                                 'limit_count': len(matched) if docs['limit_pool'] is not None else None,
                                 'stocks': [{'code': x['code'], 'name': x['name']} for x in matched],
                                 'source': 'kaipanla_stock_memberships_intersect_limit_pool'}
            return result
        breadth_path = DATA / "replay" / "breadth" / day / f"{plate}.json"
        breadth = read(breadth_path)
        if breadth:
            if breadth.get("date") != day or str(breadth.get("plate_id")) != plate:
                raise ValueError("细分数量缓存日期或编号不匹配")
            result["breadth"] = {**breadth, "source_path": str(breadth_path.relative_to(ROOT))}
        else:
            result["breadth"] = {"plate_id": plate, "missing": "breadth", "limit_count": None}
            result['missing_components'].append('plate_members:' + plate)
    return result


FIELDS = ('code', 'name', 'boards', 'board_type', 'closed_limit', 'failed_limit',
          'open', 'close', 'open_pct', 'first_limit_time', 'final_limit_time', 'open_count',
          'plate_ids', 'catalysts', 'has_limit_attack', 'has_reseal', 'first_limit_ts')
DEFAULT_FIELDS = ('code','name','boards','board_type','closed_limit','failed_limit',
                  'open_pct','first_limit_time')

def query(day, code=None, plate=None, *, fields=None, pool=None):
    from datetime import date, datetime
    from ultraboard.kaipanla.client import CN_TZ
    day = date.fromisoformat(day).isoformat()
    fields = fields or DEFAULT_FIELDS
    unknown = set(fields) - set(FIELDS)
    if unknown:
        raise ValueError('未知字段: ' + ','.join(sorted(unknown)))
    if pool not in (None, 'limit', 'failed', 'one-price'):
        raise ValueError('未知股票池')
    if len(fields) != len(set(fields)):
        raise ValueError('字段不得重复')
    raw = query_raw(day, code, plate, fields=fields)
    rows = []
    catalyst_groups = {}
    for item in raw['stocks']:
        market = item.get('market', {})
        limit = item.get('limit_pool', {})
        prices = item.get('prices', {})
        if pool == 'limit' and not limit: continue
        if pool == 'failed' and not market.get('failed_limit'): continue
        if pool == 'one-price' and market.get('board_type') != '一字板': continue
        if plate and plate not in item.get('plate_ids', []): continue
        first = market.get('first_limit_ts') or limit.get('first_limit_ts')
        final = market.get('final_limit_ts')
        row = {'code':item['code'], 'name':limit.get('name') or market.get('name'),
               'boards':limit.get('boards',market.get('boards')), 'board_type':market.get('board_type'),
               'closed_limit':bool(limit) if limit else market.get('closed_limit'),
               'failed_limit':market.get('failed_limit'), 'open':prices.get('open'),
               'close':prices.get('close'), 'open_pct':prices.get('open_pct'),
               'first_limit_time':datetime.fromtimestamp(first,CN_TZ).strftime('%H:%M:%S') if first else None,
               'final_limit_time':datetime.fromtimestamp(final,CN_TZ).strftime('%H:%M:%S') if final else None,
               'open_count':market.get('open_count'), 'plate_ids':item.get('plate_ids'),
               'catalysts':item.get('kaipanla_catalysts',[]) if 'reasons' not in raw['missing_components'] else None, 'has_limit_attack':market.get('has_limit_attack'),
               'has_reseal':market.get('has_reseal'), 'first_limit_ts':first}
        if 'catalysts' in fields and row['catalysts'] is not None:
            catalysts=[]
            for catalyst in row['catalysts']:
                group=str(catalyst['source_group_id'])
                value={'name':catalyst['source_group_name'], 'explanation':catalyst['source_group_explanation']}
                if group in catalyst_groups and catalyst_groups[group]!=value:
                    raise ValueError('同日催化组编号对应多个内容')
                catalyst_groups[group]=value
                entry={'group':group,'text':catalyst['text']}
                if entry not in catalysts:catalysts.append(entry)
            row['catalysts']=catalysts
        rows.append({key:row[key] for key in fields})
    result = {'date':day, 'offline':True, 'count':len(rows), 'stocks':rows}
    if catalyst_groups: result['catalyst_groups']=catalyst_groups
    if raw['missing_components']: result['missing_components']=raw['missing_components']
    if plate:
        b=raw.get('breadth',{})
        result['plate']={'id':plate,'member_count':b.get('member_count'),'limit_count':b.get('limit_count')}
        if b.get('limit_count') is None:
            result['plate']['status'] = 'needs_data'
            result['plate']['reason'] = '该日期的完整细分成员或涨停池未齐备，空列表不表示零只涨停'
    return result


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day")
    parser.add_argument("--code")
    parser.add_argument("--plate")
    parser.add_argument('--pool', choices=['limit','failed','one-price'])
    parser.add_argument('--fields', help='只返回指定字段，逗号分隔；如code,name,open_pct,catalysts')
    args = parser.parse_args()
    print(json.dumps(query(args.day, args.code, args.plate, fields=args.fields.split(',') if args.fields else None, pool=args.pool), ensure_ascii=False, separators=(",", ":")))
