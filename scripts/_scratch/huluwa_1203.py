import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


for d in ["2024-12-02", "2024-12-03", "2024-12-04", "2024-12-05"]:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    print(f"\n==== {d} n={data.get('count')} H={data.get('max_board')} ====")
    print("top", ", ".join(f"{k}{v}" for k, v in Counter((s.get("theme") or "?") for s in stocks).most_common(6)))
    for name in ["葫芦娃", "广博股份", "南京化纤", "欣龙控股", "海南瑞泽"]:
        s = next((x for x in stocks if x["name"] == name), None)
        if not s:
            print(f"  {name} 不在池")
            continue
        raw = s.get("raw") or []
        print(
            f"  {name} {s.get('boards')}板 换手{s.get('turnover_rate')} {hhmm(s.get('first_limit_ts'))} "
            f"{s.get('theme')} tags={s.get('theme_tags_text')} open={raw[16] if len(raw)>16 else None}"
        )
    rows = [s for s in stocks if "海南" in blob(s)]
    main = [s for s in stocks if (s.get("theme") or "") == "海南"]
    print(f"  [海南] 主{len(main)}属{len(rows)}")
    print(
        "   ",
        ", ".join(
            f"{s['name']}{s['boards']}板/{s.get('theme')}/{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
            for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
        ),
    )
