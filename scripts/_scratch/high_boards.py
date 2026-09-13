import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("data/kaipanla/raw")


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


for d in ["2024-10-17", "2024-10-22", "2024-10-23", "2024-10-24", "2024-10-25"]:
    data = load(d)
    rows = [s for s in data["stocks"] if (s.get("boards") or 0) >= 3]
    by_b = defaultdict(list)
    for s in rows:
        by_b[s["boards"]].append(f"{s['name']}/{s.get('theme')}/{s['turnover_rate']}%")
    print(f"\n==== {d} 涨停{data['count']} H={data['max_board']} 三板及以上{len(rows)} ====")
    for b in sorted(by_b, reverse=True):
        print(f"  {b}板({len(by_b[b])}): " + ", ".join(by_b[b]))
