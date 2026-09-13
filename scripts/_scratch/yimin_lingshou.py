import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
DAYS = [
    "2024-12-10",
    "2024-12-11",
    "2024-12-12",
    "2024-12-13",
    "2024-12-16",
    "2024-12-17",
]
KEYS = ["零售", "首发经济", "上海", "平台经济"]
FOCUS = ["益民集团", "中百集团", "文峰股份", "友阿股份"]


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


for d in DAYS:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    by = {s["name"]: s for s in stocks}
    print(f"\n==== {d} n={data.get('count')} H={data.get('max_board')} ====")
    print("  top:", ", ".join(f"{k}{v}" for k, v in Counter((s.get("theme") or "?") for s in stocks).most_common(8)))
    for name in FOCUS:
        s = by.get(name)
        if not s:
            continue
        print(
            f"  {name} {s.get('boards')}板 换手{s.get('turnover_rate')} {hhmm(s.get('first_limit_ts'))} "
            f"theme={s.get('theme')} sec={s.get('sector_code')} tags={s.get('theme_tags_text')}"
        )
    for key in KEYS:
        rows = [s for s in stocks if key in blob(s)]
        main = [s for s in stocks if (s.get("theme") or "") == key]
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
        if rows:
            print(
                "   ",
                ", ".join(
                    f"{s['name']}{s['boards']}板/{s.get('theme')}/"
                    f"{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
                    for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
                ),
            )
