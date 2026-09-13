import json
import urllib.request
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


def kline(code, start, end):
    prefix = "sh" if code.startswith("6") else "sz"
    symbol = prefix + code
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},day,{start},{end},30,"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    )
    text = urllib.request.urlopen(req, timeout=15).read().decode()
    rows = ((json.loads(text).get("data") or {}).get(symbol) or {}).get("day") or []
    print(f"\n== {code} 日线 date open close high low ==")
    for r in rows:
        print(r[0], r[1], r[2], r[3], r[4])


keys = ["人工智能", "数据中心", "AI应用", "国产软件"]
for d in ["2024-11-21", "2024-11-22", "2024-11-25", "2024-11-26"]:
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    for key in keys:
        rows = [s for s in data["stocks"] if key in blob(s)]
        main = [s for s in data["stocks"] if (s.get("theme") or "") == key]
        print(f"  [{key}] 主{len(main)} 属{len(rows)}")
        if rows:
            print(
                "   ",
                ", ".join(
                    f"{s['name']}{s['boards']}板/{s.get('theme')}/"
                    f"{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%/"
                    f"开{(s.get('raw') or [None]*17)[16] if len(s.get('raw') or [])>16 else '-'}"
                    for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
                ),
            )

kline("000833", "2024-11-14", "2024-11-28")
kline("002467", "2024-11-14", "2024-11-28")
