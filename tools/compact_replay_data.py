"""迁移为个股中心的成员关系，核对后删除重复板块快照；默认仅报告。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ultraboard.kaipanla.query import _member_snapshot, _read
from ultraboard.kaipanla import membership_store as store

OLD = ROOT / 'data/kaipanla/plate_members'
BREADTH = ROOT / 'data/replay/breadth'

def migrate(folder, apply):
    day = folder.name
    from datetime import date
    date.fromisoformat(day)
    files = sorted(folder.glob('*.json'))
    if not files:
        return (0, 0, 0)
    body = {'schema': 1, 'date': day, 'source': 'kaipanla',
            'source_action': 'ZhiShuStockList_W8',
            'historical_membership_verified': False, 'stocks': {}, 'plates': {}}
    existing = store.load(day)
    if existing:
        body = json.loads(json.dumps(existing))
    before = 0
    expected = {}
    for path in files:
        doc = _read(path)
        if doc['date'] != day or str(doc['plate_id']) != path.stem:
            raise ValueError(f'身份错误: {path}')
        snap = _member_snapshot(day, path.stem, doc['raw_pages'])
        codes = {r['code'] for r in snap['members']}
        if codes != {r['code'] for r in doc['members']} or len(codes) != doc['member_count']:
            raise ValueError(f'成员不一致: {path}')
        expected[path.stem] = codes
        for code, ids in body['stocks'].items():
            if path.stem in ids and code not in codes:
                ids.remove(path.stem)
        for code in codes:
            ids = body['stocks'].setdefault(code, [])
            if path.stem not in ids:
                ids.append(path.stem)
        body['plates'][path.stem] = {'member_count': len(codes), 'captured_at': doc.get('captured_at')}
        before += path.stat().st_size
    body['stocks'] = {c: sorted(ids) for c, ids in sorted(body['stocks'].items()) if ids}
    serialized = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if apply:
        store.save(day, body)
        # 验证实际落盘文件；完整成员集合相等保证与任意涨停池的交集不变。
        saved = _read(store.ROOT / f'{day}.json')
        for plate, codes in expected.items():
            actual = {c for c, ids in saved['stocks'].items() if plate in ids}
            if actual != codes:
                raise ValueError(f'迁移不一致: {day} {plate}')
        # 只删本轮已成功迁移的确切JSON文件，保留目录和其他原始数据。
        for path in files:
            if path.resolve().parent != folder.resolve() or not path.resolve().is_relative_to(OLD.resolve()):
                raise ValueError('清理路径越界')
            path.unlink()
            derived = BREADTH / day / path.name
            if derived.exists():
                before += derived.stat().st_size
                derived.unlink()
    return (len(files), before, len(serialized))

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--day')
    args = p.parse_args()
    folders = [OLD / args.day] if args.day else sorted(x for x in OLD.iterdir() if x.is_dir())
    folders = [f for f in folders if next(f.glob('*.json'), None) is not None]
    totals = [0, 0, 0]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, result in enumerate(pool.map(lambda f: migrate(f, args.apply), folders), 1):
            totals = [a+b for a,b in zip(totals, result)]
            if i % 50 == 0 or i == len(folders):
                print(json.dumps({'days': i, 'total_days': len(folders), 'files': totals[0],
                                  'before_MB': round(totals[1]/1e6, 2), 'after_MB': round(totals[2]/1e6, 2)}, ensure_ascii=False), flush=True)
    report = {'applied': args.apply, 'migrated_files': totals[0], 'before_bytes': totals[1], 'after_bytes': totals[2]}
    if args.apply:
        prior = {}
        prior_path = ROOT / 'data/replay/compact_report.json'
        if prior_path.exists():
            prior = _read(prior_path)
            for key in ('migrated_files', 'before_bytes', 'after_bytes'):
                report[key] += prior.get(key, 0)
        (ROOT / 'data/replay/compact_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        # 旧导入缓存同样只在成员集合完全一致时删除，避免重新导入大快照。
        imported = ROOT / 'data/kaipanla/research_attributes'
        removed = prior.get('removed_duplicate_import_bytes', 0)
        for path in imported.rglob('*.json'):
            doc = _read(path)
            query = doc.get('query', {})
            day, plate = query.get('date'), query.get('plate_code')
            if not day or not plate or not doc.get('raw_response') or (args.day and args.day != day):
                continue
            compact = store.snapshot(day, str(plate))
            if compact is None:
                continue
            try:
                snap = _member_snapshot(day, str(plate), [doc['raw_response']])
            except (ValueError, RuntimeError, TypeError, KeyError):
                continue
            if {x['code'] for x in snap['members']} == {x['code'] for x in compact['members']}:
                if not path.resolve().is_relative_to(imported.resolve()):
                    raise ValueError('导入缓存路径越界')
                removed += path.stat().st_size
                path.unlink()
        report['removed_duplicate_import_bytes'] = removed
        (ROOT / 'data/replay/compact_report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
