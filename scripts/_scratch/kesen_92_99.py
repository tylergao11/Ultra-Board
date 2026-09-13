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


focus = ["603626", "002676", "000062", "002302"]
# 科森 奋达 华强 西部
extra_keys = [
    "消费电子",
    "折叠屏",
    "端侧AI",
    "电子烟",
    "华为概念",
    "华为海思",
    "华为",
]

days = [
    "2024-08-29",
    "2024-08-30",
    "2024-09-02",
    "2024-09-03",
    "2024-09-04",
    "2024-09-05",
    "2024-09-06",
    "2024-09-09",
    "2024-09-10",
]

for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    by = {s["code"]: s for s in data["stocks"]}
    for c in focus:
        s = by.get(c)
        if not s:
            print(f"  {c} 不在池")
            continue
        raw = s.get("raw") or []
        circ = raw[13] if len(raw) > 13 else None
        print(
            f"  {s['name']} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"sec={s.get('sector_code')} tags={s.get('theme_tags_text')} "
            f"price={s.get('price')} circ={circ}"
        )

    # 科森同梯队：同板数消费电子 / 折叠屏
    kesen = by.get("603626")
    kb = kesen.get("boards") if kesen else None

    tc = Counter(s.get("theme") or "?" for s in data["stocks"])
    print("  主标签 top:", ", ".join(f"{k}{v}" for k, v in tc.most_common(10)))
    for key in extra_keys:
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
    if kb:
        same = [
            s
            for s in data["stocks"]
            if s.get("boards") == kb and "消费电子" in blob(s)
        ]
        print(
            f"  同{kb}板且属消费电子: "
            + (
                ", ".join(f"{s['name']}/{s.get('theme')}" for s in same)
                or "无"
            )
        )
