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


focus = ["金桥信息", "中化岩土", "粤桂股份", "高乐股份"]

for d in [
    "2024-11-07",
    "2024-11-08",
    "2024-11-11",
    "2024-11-12",
    "2024-11-13",
    "2024-11-14",
    "2024-11-15",
]:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
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
            f"open={raw[16] if len(raw)>16 else None}"
        )
    print(
        "  主标签 top:",
        ", ".join(f"{k}{v}" for k, v in Counter(s.get("theme") or "?" for s in data["stocks"]).most_common(8)),
    )
    s = by.get("金桥信息")
    keys = []
    if s:
        keys.append(s.get("theme") or "")
        for t in (s.get("theme_tags_text") or "").split("、"):
            if t.strip():
                keys.append(t.strip())
    keys = list(dict.fromkeys([k for k in keys if k]))
    extra = ["算力", "通信", "华为", "数字经济", "人工智能"]
    for key in keys + [k for k in extra if k not in keys]:
        rows = [x for x in data["stocks"] if key in blob(x)]
        main = [x for x in data["stocks"] if (x.get("theme") or "") == key]
        if not rows and not main:
            continue
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
        if rows[:8]:
            print(
                "   ",
                ", ".join(
                    f"{x['name']}{x['boards']}板/{x.get('theme')}/"
                    f"{hhmm(x.get('first_limit_ts'))}/{x['turnover_rate']}%"
                    for x in sorted(rows, key=lambda z: -(z.get("boards") or 0))[:8]
                ),
            )
