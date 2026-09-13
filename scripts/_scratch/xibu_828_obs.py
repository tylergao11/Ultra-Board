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


codes = ["002302", "603060", "000062", "603626"]
names = {
    "002302": "西部建设",
    "603060": "国检集团",
    "000062": "深圳华强",
    "603626": "科森科技",
}

for d in [
    "2024-08-23",
    "2024-08-26",
    "2024-08-27",
    "2024-08-28",
    "2024-08-29",
    "2024-08-30",
]:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    by = {s["code"]: s for s in data["stocks"]}
    for c in codes:
        s = by.get(c)
        if not s:
            print(f"  {names[c]} 不在池")
            continue
        raw = s.get("raw") or []
        circ = raw[13] if len(raw) > 13 else None
        print(
            f"  {s['name']} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"sec={s.get('sector_code')} tags={s.get('theme_tags_text')} "
            f"price={s.get('price')} circ={circ}"
        )

    tc = Counter(s.get("theme") or "?" for s in data["stocks"])
    print("  主标签 top:", ", ".join(f"{k}{v}" for k, v in tc.most_common(12)))
    for key in [
        "西部大开发",
        "地产链",
        "房屋检测",
        "基础建设",
        "建材",
        "华为海思",
        "华为概念",
        "消费电子",
    ]:
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
