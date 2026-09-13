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


days = sorted(
    p.name
    for p in ROOT.iterdir()
    if p.name.startswith("2024-09") or p.name.startswith("2024-10")
)

print("== 双成药业逐日 ==")
for d in days:
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        continue
    data = load(d)
    s = next((x for x in data["stocks"] if x["name"] == "双成药业"), None)
    if not s:
        continue
    raw = s.get("raw") or []
    m_main = sum(1 for x in data["stocks"] if (x.get("theme") or "") == "并购重组")
    m_attr = sum(1 for x in data["stocks"] if "并购重组" in blob(x))
    print(
        f"{d} {s['boards']}板 换手{s.get('turnover_rate')} 首封{hhmm(s.get('first_limit_ts'))} "
        f"theme={s.get('theme')} tags={s.get('theme_tags_text')} "
        f"open={raw[16] if len(raw)>16 else None} "
        f"并购主{m_main}属{m_attr} 全场{data.get('count')} H={data.get('max_board')}"
    )

print("\n== 9.20-9.25 并购重组名单 ==")
for d in ["2024-09-20", "2024-09-23", "2024-09-24", "2024-09-25", "2024-09-26"]:
    data = load(d)
    rows = [x for x in data["stocks"] if "并购重组" in blob(x)]
    print(
        d,
        ", ".join(
            f"{x['name']}{x['boards']}板/{x.get('theme')}/{hhmm(x.get('first_limit_ts'))}/{x['turnover_rate']}%"
            for x in sorted(rows, key=lambda z: -(z.get("boards") or 0))
        )
        or "0",
    )
