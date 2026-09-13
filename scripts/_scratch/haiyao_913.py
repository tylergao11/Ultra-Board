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


keys = [
    "医药",
    "创新药",
    "病毒防治",
    "国企改革",
    "国有企业",
    "民营医院",
    "医疗器械",
]

days = [
    "2024-09-10",
    "2024-09-11",
    "2024-09-12",
    "2024-09-13",
    "2024-09-18",
    "2024-09-19",
]

for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    s = next((x for x in data["stocks"] if x["code"] == "000566"), None)
    if not s:
        print("  海南海药 不在池")
    else:
        raw = s.get("raw") or []
        print(
            f"  海南海药 {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"sec={s.get('sector_code')} tags={s.get('theme_tags_text')} "
            f"price={s.get('price')} raw16={raw[16] if len(raw)>16 else None} "
            f"raw20={raw[20] if len(raw)>20 else None}"
        )
    tc = Counter(x.get("theme") or "?" for x in data["stocks"])
    print("  主标签 top:", ", ".join(f"{k}{v}" for k, v in tc.most_common(12)))
    for key in keys:
        rows = [x for x in data["stocks"] if key in blob(x)]
        main = [x for x in data["stocks"] if (x.get("theme") or "") == key]
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
        if rows:
            print(
                "   ",
                ", ".join(
                    f"{x['name']}{x['boards']}板/{x.get('theme')}/"
                    f"{hhmm(x.get('first_limit_ts'))}/{x['turnover_rate']}%"
                    for x in sorted(rows, key=lambda z: -(z.get("boards") or 0))
                ),
            )
