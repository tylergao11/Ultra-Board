import json
import urllib.request
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


keys = ["通信", "数字经济", "地产链", "房地产", "国企改革", "并购重组"]
focus = ["002583", "600881", "002693", "600198"]

for d in ["2024-09-24", "2024-09-25", "2024-09-26", "2024-09-27", "2024-09-30"]:
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    by = {s["code"]: s for s in data["stocks"]}
    for code in focus:
        s = by.get(code)
        if not s:
            print(f"  {code} 不在池")
            continue
        raw = s.get("raw") or []
        print(
            f"  {s['name']} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} "
            f"tags={s.get('theme_tags_text')} open={raw[16] if len(raw)>16 else None}"
        )
    tc = Counter(s.get("theme") or "?" for s in data["stocks"])
    print("  主标签 top:", ", ".join(f"{k}{v}" for k, v in tc.most_common(8)))
    for key in keys:
        rows = [s for s in data["stocks"] if key in blob(s)]
        main = [s for s in data["stocks"] if (s.get("theme") or "") == key]
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
        if rows[:8]:
            print(
                "   ",
                ", ".join(
                    f"{s['name']}{s['boards']}板/{s.get('theme')}/"
                    f"{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
                    for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))[:8]
                ),
            )

url = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param=sz002583,day,2024-09-20,2024-09-30,20,"
)
req = urllib.request.Request(
    url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
)
text = urllib.request.urlopen(req, timeout=15).read().decode()
rows = ((json.loads(text).get("data") or {}).get("sz002583") or {}).get("day") or []
print("\n== 海能达日线 date open close high low ==")
for r in rows:
    print(r)
