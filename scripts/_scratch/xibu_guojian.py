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


keys = ("西部大开发", "地产链", "房地产", "房屋检测", "基础建设", "建材", "地产")

for d in ["2024-08-26", "2024-08-27", "2024-08-28", "2024-08-29"]:
    data = load(d)
    print(f"\n==== {d} 全场{data['count']} H={data['max_board']} ====")
    for code, name in (("002302", "西部建设"), ("603060", "国检集团")):
        s = next((x for x in data["stocks"] if x["code"] == code), None)
        if not s:
            print(f"  {name} 不在池")
            continue
        print(
            f"  {name} {s['boards']}板 换手{s['turnover_rate']} 首封{hhmm(s.get('first_limit_ts'))} "
            f"theme={s.get('theme')} sec={s.get('sector_code')} tags={s.get('theme_tags_text')}"
        )
    print("  分标签家数:")
    for key in keys:
        rows = [s for s in data["stocks"] if key in blob(s)]
        if not rows:
            print(f"    {key}: 0")
            continue
        print(f"    {key}: {len(rows)}  " + ", ".join(
            f"{s['name']}{s['boards']}板/{s.get('theme')}/{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
            for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
        ))
