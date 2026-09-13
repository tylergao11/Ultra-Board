import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


focus = [
    "成都路桥",
    "重庆建工",
    "中化岩土",
    "华立股份",
    "双成药业",
    "光智科技",
    "粤桂股份",
    "文一科技",
]

keys = ["西部大开发", "基础建设", "低空经济", "并购重组", "芯片"]

days = [
    "2024-10-18",
    "2024-10-21",
    "2024-10-22",
    "2024-10-23",
    "2024-10-24",
    "2024-10-25",
    "2024-10-28",
    "2024-10-29",
    "2024-10-30",
    "2024-10-31",
]

for d in days:
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    by = {s["name"]: s for s in data["stocks"]}
    for name in focus:
        s = by.get(name)
        if not s:
            print(f"  {name} 不在池")
            continue
        raw = s.get("raw") or []
        print(
            f"  {s['name']} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"tags={s.get('theme_tags_text')} open={raw[16] if len(raw)>16 else None}"
        )
    print(
        "  主标签 top:",
        ", ".join(
            f"{k}{v}"
            for k, v in Counter(s.get("theme") or "?" for s in data["stocks"]).most_common(8)
        ),
    )
    tops = sorted(data["stocks"], key=lambda s: -(s.get("boards") or 0))[:6]
    print(
        "  高度:",
        ", ".join(
            f"{s['name']}{s['boards']}板/{s.get('theme')}/{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
            for s in tops
        ),
    )
    for key in keys:
        rows = [s for s in data["stocks"] if key in blob(s)]
        main = [s for s in data["stocks"] if (s.get("theme") or "") == key]
        if not rows:
            print(f"  [{key}] 0")
            continue
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
