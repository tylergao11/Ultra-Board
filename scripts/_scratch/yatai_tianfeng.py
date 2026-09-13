import json
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


def show(d, names):
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    by_name = {s["name"]: s for s in data["stocks"]}
    for name in names:
        s = by_name.get(name)
        if not s:
            print(f"  {name} 不在池")
            continue
        raw = s.get("raw") or []
        print(
            f"  {s['name']} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"sec={s.get('sector_code')} tags={s.get('theme_tags_text')} "
            f"open={raw[16] if len(raw)>16 else None}"
        )
    for key in ["地产链", "房地产", "证券", "金融概念", "通信"]:
        rows = [s for s in data["stocks"] if key in blob(s)]
        main = [s for s in data["stocks"] if (s.get("theme") or "") == key]
        tops = sorted(rows, key=lambda x: -(x.get("boards") or 0))[:6]
        print(
            f"  [{key}] 主{len(main)} 属{len(rows)} "
            + ", ".join(
                f"{s['name']}{s['boards']}板/{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
                for s in tops
            )
        )


names = ["海能达", "亚泰集团", "天风证券", "双成药业"]
for d in [
    "2024-09-23",
    "2024-09-24",
    "2024-09-25",
    "2024-09-26",
    "2024-09-27",
    "2024-09-30",
    "2024-10-08",
    "2024-10-09",
]:
    show(d, names)
