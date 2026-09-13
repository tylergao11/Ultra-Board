import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")

DAYS = [
    "2024-11-15",
    "2024-11-18",
    "2024-11-19",
    "2024-11-20",
    "2024-11-21",
    "2024-11-22",
    "2024-11-25",
    "2024-11-26",
    "2024-11-27",
]
FOCUS = ["粤桂股份", "二六三", "高乐股份"]
KEYS = ["锂电池", "磷化工", "硫化物", "通信", "互联网", "云计算", "算力", "数字经济"]


def load(d):
    p = ROOT / d / "zt_pool.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


for d in DAYS:
    data = load(d)
    if not data:
        print(f"\n==== {d} MISSING ====")
        continue
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    by = {s["name"]: s for s in data["stocks"]}
    for name in FOCUS:
        s = by.get(name)
        if not s:
            print(f"  {name} 不在池")
            continue
        raw = s.get("raw") or []
        print(
            f"  {s['name']} {s.get('code')} {s.get('boards')}板 "
            f"换手{s.get('turnover_rate')} 首封{hhmm(s.get('first_limit_ts'))} "
            f"theme={s.get('theme')} sec={s.get('sector_code')} "
            f"tags={s.get('theme_tags_text')} "
            f"open_cnt={raw[16] if len(raw)>16 else None} "
            f"price={s.get('price')} circ={raw[13] if len(raw)>13 else None}"
        )
    print(
        "  主标签 top:",
        ", ".join(f"{k}{v}" for k, v in Counter(s.get("theme") or "?" for s in data["stocks"]).most_common(8)),
    )
    for key in KEYS:
        rows = [s for s in data["stocks"] if key in blob(s)]
        main = [s for s in data["stocks"] if (s.get("theme") or "") == key]
        if not rows and not main:
            continue
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
        print(
            "   ",
            ", ".join(
                f"{s['name']}{s['boards']}板/{s.get('theme')}/"
                f"{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
                for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))[:16]
            ),
        )
