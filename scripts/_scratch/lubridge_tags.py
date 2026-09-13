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


keys = [
    "西部大开发",
    "西部",
    "基础建设",
    "基建",
    "机器人",
    "重庆建工",
]

for d in ["2024-10-22", "2024-10-23", "2024-10-24"]:
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} ====")
    s = next((x for x in data["stocks"] if x["name"] == "成都路桥"), None)
    if s:
        print(
            f"  路桥 theme={s.get('theme')} sec={s.get('sector_code')} "
            f"tags={s.get('theme_tags_text')} {s.get('boards')}板"
        )
    else:
        print("  路桥 不在池")

    print("  含「西部」的票:")
    for x in data["stocks"]:
        b = blob(x)
        if "西部" in b:
            print(
                f"    {x['name']}{x['boards']}板 theme={x.get('theme')} "
                f"sec={x.get('sector_code')} tags={x.get('theme_tags_text')} "
                f"{hhmm(x.get('first_limit_ts'))}/{x['turnover_rate']}%"
            )

    print("  含「基础建设」或「基建」的票:")
    for x in data["stocks"]:
        b = blob(x)
        if "基础建设" in b or "基建" in b:
            print(
                f"    {x['name']}{x['boards']}板 theme={x.get('theme')} "
                f"sec={x.get('sector_code')} tags={x.get('theme_tags_text')} "
                f"{hhmm(x.get('first_limit_ts'))}/{x['turnover_rate']}%"
            )

    print("  含「机器人」的票:")
    rows = [x for x in data["stocks"] if "机器人" in blob(x)]
    print(
        "   ",
        ", ".join(
            f"{x['name']}{x['boards']}板/{x.get('theme')}"
            for x in sorted(rows, key=lambda z: -(z.get("boards") or 0))
        )
        or "无",
    )

    from collections import Counter

    sec = Counter(x.get("sector_code") for x in data["stocks"])
    print("  sector top:", sec.most_common(8))
    print("  theme=西部大开发", sum(1 for x in data["stocks"] if x.get("theme") == "西部大开发"))
    print("  theme=基础建设", sum(1 for x in data["stocks"] if x.get("theme") == "基础建设"))
    print("  sec=801470", sum(1 for x in data["stocks"] if x.get("sector_code") == "801470"))
