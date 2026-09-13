import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


for d in [
    "2024-09-18",
    "2024-09-19",
    "2024-09-20",
    "2024-09-23",
    "2024-09-24",
    "2024-09-25",
]:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    top = sorted(data["stocks"], key=lambda s: -(s.get("boards") or 0))[:8]
    print(d, "H", data.get("max_board"), "count", data.get("count"))
    for s in top:
        print(
            f"  {s['name']} {s['boards']}板 {s.get('theme')} "
            f"{hhmm(s.get('first_limit_ts'))} {s['turnover_rate']}%"
        )
