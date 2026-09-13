import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
FOCUS = ["广博股份", "葫芦娃", "二六三", "高乐股份", "粤桂股份"]
KEYS = ["文创产品", "文化传媒", "腾讯概念", "人工智能", "锂电池", "医药"]


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


days = sorted(
    p.name
    for p in ROOT.iterdir()
    if p.is_dir() and p.name >= "2024-11-15" and p.name <= "2024-12-13" and (p / "zt_pool.json").exists()
)
for d in days:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    by = {s["name"]: s for s in stocks}
    hits = [n for n in FOCUS if n in by]
    print(f"\n==== {d} n={data.get('count')} H={data.get('max_board')} ====")
    print("  top:", ", ".join(f"{k}{v}" for k, v in Counter((s.get("theme") or "?") for s in stocks).most_common(6)))
    for name in FOCUS:
        s = by.get(name)
        if not s:
            continue
        raw = s.get("raw") or []
        print(
            f"  {name} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"{hhmm(s.get('first_limit_ts'))} {s.get('theme')} "
            f"tags={s.get('theme_tags_text')} open={raw[16] if len(raw)>16 else None} "
            f"circ={raw[13] if len(raw)>13 else None}"
        )
    for key in KEYS:
        rows = [s for s in stocks if key in blob(s)]
        main = [s for s in stocks if (s.get("theme") or "") == key]
        if not rows:
            continue
        print(
            f"  [{key}] 主{len(main)}属{len(rows)}",
            ", ".join(
                f"{s['name']}{s['boards']}板/{s.get('theme')}/{s['turnover_rate']}%"
                for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))[:8]
            ),
        )
    if not hits:
        print("  focus none")
