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


focus = ["光大嘉宝", "成都路桥", "亚泰集团", "中化岩土"]
keys = ["地产链", "房地产", "基础建设", "国企改革", "并购重组"]

for d in [
    "2024-10-09",
    "2024-10-10",
    "2024-10-11",
    "2024-10-14",
    "2024-10-15",
    "2024-10-16",
    "2024-10-17",
    "2024-10-18",
]:
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
            f"  {s['name']} {s.get('code')} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"sec={s.get('sector_code')} tags={s.get('theme_tags_text')} "
            f"price={s.get('price')} open={raw[16] if len(raw)>16 else None}"
        )
    tc = Counter(s.get("theme") or "?" for s in data["stocks"])
    print("  主标签 top:", ", ".join(f"{k}{v}" for k, v in tc.most_common(8)))
    for key in keys:
        rows = [s for s in data["stocks"] if key in blob(s)]
        main = [s for s in data["stocks"] if (s.get("theme") or "") == key]
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
