import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
obs, prev = "2024-07-29", days[days.index("2024-07-29") - 1]


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def hit(s, key="商业航天"):
    blob = "|".join([
        s.get("theme") or "",
        s.get("theme_tags_text") or "",
        str((s.get("raw") or [""])[5] if s.get("raw") else ""),
        str((s.get("raw") or [""] * 13)[12] if s.get("raw") and len(s.get("raw") or []) > 12 else ""),
    ])
    return key in blob


def dump(d):
    data = load(d)
    rows = [s for s in data["stocks"] if hit(s)]
    main = [s for s in data["stocks"] if (s.get("sector_code") or "") == "801843"]
    print(f"\n{d} 全场{data['count']}  主标签801843={len(main)}  属性含商业航天={len(rows)}")
    for s in rows:
        mark = "主" if (s.get("sector_code") or "") == "801843" else "挂"
        print(
            f"  [{mark}] {s['name']} {s['boards']}板 换手{s.get('turnover_rate')} 首封{hhmm(s.get('first_limit_ts'))} "
            f"theme={s.get('theme')} tags={s.get('theme_tags_text')}"
        )


dump(prev)
dump(obs)
print(f"\n属性口径: {prev} {sum(1 for s in load(prev)['stocks'] if hit(s))} -> {obs} {sum(1 for s in load(obs)['stocks'] if hit(s))}")
