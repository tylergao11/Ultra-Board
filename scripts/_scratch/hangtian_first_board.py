import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
codes = ["001379", "600501", "603278", "600855", "300581", "002278"]


def find(d, code):
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    for s in data["stocks"]:
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


for code in codes:
    first = None
    for d in days:
        if d < "2024-07-15" or d > "2024-08-06":
            continue
        s = find(d, code)
        if s and (s.get("boards") or 0) == 1:
            raw = s.get("raw") or []
            cap = raw[13] if len(raw) > 13 else None
            first = (d, s.get("name"), s.get("price"), cap, s.get("turnover_rate"), s.get("theme"))
            # keep earliest 1板 in window; if later another 1板 after break, still note
    # walk properly: first 1板 that starts a streak touching our story
    print("---", code)
    prev_b = None
    for d in days:
        if d < "2024-07-10" or d > "2024-08-06":
            continue
        s = find(d, code)
        b = s.get("boards") if s else None
        if s and b == 1 and prev_b != 1:
            raw = s.get("raw") or []
            cap = raw[13] if len(raw) > 13 else None
            yi = cap / s["price"] / 1e4 if cap and s["price"] else None
            print(
                f"  首板 {d} {s['name']} 价{s['price']} 流通市值{cap/1e8:.2f}亿 "
                f"约{yi:.0f}万股 换手{s['turnover_rate']}% {s.get('theme')}"
            )
        prev_b = b
