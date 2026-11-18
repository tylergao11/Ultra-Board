"""Recover a complete catalogue-scoped concept snapshot from provider members."""
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .intake import ingest_paths
from .system import SHANGHAI, valid_code


def recover(store, codes, catalogue_path, quote_date):
    codes = sorted(set(codes))
    if any(valid_code(c) != c for c in codes):
        raise ValueError('Invalid stock code')
    catalogue_file = store.root / catalogue_path
    catalogue = json.loads(catalogue_file.read_text(encoding='utf-8'))['catalogue']
    directory = store.root / 'data/kaipanla/plate_members' / quote_date
    directory.mkdir(parents=True, exist_ok=True)
    endpoint = 'https://apphis.longhuvip.com/w1/api/index.php'

    def members(item):
        plate, name = item
        path = directory / (plate + '.json')
        if path.exists():
            doc = json.loads(path.read_text(encoding='utf-8'))
            rows = doc['members']
            if (doc.get('plate_id') == plate and doc.get('date') == quote_date
                    and len(rows) == doc.get('member_count')):
                return plate, name, path, {r['code'] for r in rows}
        pages, collected, offset = [], {}, 0
        while True:
            params = dict(a='ZhiShuStockList_W8', c='ZhiShuRanking', PlateID=plate,
                          Date=quote_date, Index=offset, st=500, apiv='w43',
                          PhoneOSNew=1, Type=6, Order=1)
            for attempt in range(3):
                try:
                    with urlopen(Request(endpoint + '?' + urlencode(params)), timeout=20) as response:
                        raw = json.loads(response.read().decode('utf-8'))
                    if str(raw.get('errcode', '0')) != '0' or quote_date not in raw.get('Day', []):
                        raise ValueError('Wrong date or provider error')
                    rows = raw.get('list')
                    if not isinstance(rows, list) or 'Count' not in raw:
                        raise ValueError('Missing member list/count')
                    break
                except Exception:
                    if attempt == 2:
                        raise
                    time.sleep(3)
            pages.append(raw)
            previous = len(collected)
            for row in rows:
                code = valid_code(str(row[0]))
                if code:
                    collected[code] = dict(code=code, name=row[1], raw=row)
            expected = int(raw['Count'])
            if len(collected) == expected:
                break
            if not rows or len(collected) == previous or len(collected) > expected:
                raise ValueError('Incomplete or inconsistent pagination: ' + plate)
            offset += len(rows)
        doc = dict(provider='kaipanla', endpoint=endpoint, action='ZhiShuStockList_W8',
                   date=quote_date, plate_id=plate, plate_name=name,
                   captured_at=datetime.now(SHANGHAI).isoformat(),
                   historical_membership_verified=False, member_count=len(collected),
                   members=list(collected.values()), raw_pages=pages)
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        return plate, name, path, set(collected)

    results, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = {executor.submit(members, item): item[0] for item in catalogue.items()}
        for future in as_completed(pending):
            try:
                results.append(future.result())
            except Exception as exc:
                errors.append(dict(plate=pending[future], error=str(exc)))
    if errors:
        return dict(complete=False, checked=len(results), total=len(catalogue), errors=errors)
    sources = [catalogue_path] + sorted(p.relative_to(store.root).as_posix() for _, _, p, _ in results)
    captured = datetime.now(SHANGHAI).date().isoformat()
    out = store.root / 'data/kaipanla/concepts_current' / captured
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for code in codes:
        concepts = sorted([[plate, name] for plate, name, _, stocks in results if code in stocks])
        if not concepts:
            raise ValueError('No recovered concepts: ' + code)
        path = out / (code + '-membership.json')
        doc = dict(code=code, captured_date=captured, concepts=concepts,
                   snapshot_mode='complete_catalogue_membership_reconstruction',
                   quote_date=quote_date, historical_membership_verified=False,
                   catalogue_count=len(catalogue), checked_count=len(results), sources=sources,
                   note='Provider membership as captured; not certified historical membership.')
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        saved.append(path)
    intake = ingest_paths(store, [p for _, _, p, _ in results] + saved)
    return dict(complete=True, checked=len(results), saved=[str(p) for p in saved], intake=intake)
