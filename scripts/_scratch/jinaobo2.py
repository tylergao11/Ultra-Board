import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
DAYS = ["2025-01-08", "2025-01-09", "2025-01-10", "2025-01-13"]
KEYS = ["机器人", "民用爆破", "民爆", "西藏", "水电站"]


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


for d in DAYS:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    print(f"\n==== {d} n={data.get('count')} H={data.get('max_board')} ====")
    for key in KEYS:
        rows = [s for s in stocks if key in blob(s)]
        main = [s for s in stocks if key in (s.get("theme") or "")]
        print(f"  [{key}] 主{len(main)}属{len(rows)}")
        if rows:
            print(
                "   ",
                ", ".join(
                    f"{s['name']}{s['boards']}板/{s.get('theme')}/"
                    f"{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%/{s.get('theme_tags_text')}"
                    for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
                ),
            )
