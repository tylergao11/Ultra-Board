import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
DAYS = [
    "2024-12-25",
    "2024-12-26",
    "2024-12-27",
    "2024-12-30",
    "2024-12-31",
    "2025-01-02",
    "2025-01-03",
]
FOCUS = ["顺钠股份", "电光科技", "实益达"]
KEYS = ["算力", "核电", "智能电网"]


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


def circ(s):
    raw = s.get("raw") or []
    try:
        return round(float(raw[13]) / 1e8, 1)
    except Exception:
        return None


for d in DAYS:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(f"\n==== {d} MISSING ====")
        continue
    data = json.loads(p.read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    by = {s["name"]: s for s in stocks}
    print(f"\n==== {d} n={data.get('count')} H={data.get('max_board')} ====")
    print("top", ", ".join(f"{k}{v}" for k, v in Counter((s.get("theme") or "?") for s in stocks).most_common(6)))
    for name in FOCUS:
        s = by.get(name)
        if not s:
            print(f"  {name} 不在池")
            continue
        raw = s.get("raw") or []
        print(
            f"  {name} {s.get('code')} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} sec={s.get('sector_code')} "
            f"tags={s.get('theme_tags_text')} open={raw[16] if len(raw)>16 else None} "
            f"流通{circ(s)}亿 price={s.get('price')}"
        )
    for key in KEYS:
        rows = [s for s in stocks if key in blob(s)]
        main = [s for s in stocks if (s.get("theme") or "") == key]
        if not rows:
            continue
        print(f"  [{key}] 主{len(main)}属{len(rows)}")
        print(
            "   ",
            ", ".join(
                f"{s['name']}{s['boards']}板/{s.get('theme')}/"
                f"{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
                for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
            ),
        )
