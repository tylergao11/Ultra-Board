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


for d in ["2024-09-30", "2024-10-08", "2024-10-09", "2024-10-10", "2024-10-11"]:
    data = load(d)
    print(f"\n==== {d} count={data.get('count')} H={data.get('max_board')} ====")
    for name in ["亚泰集团", "天风证券", "恒银科技", "双成药业", "国海证券"]:
        s = next((x for x in data["stocks"] if x["name"] == name), None)
        if not s:
            print(f"  {name} 不在池")
            continue
        print(
            f"  {s['name']} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"首封{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')}"
        )
    for key in ["地产链", "证券", "金融概念"]:
        main = sum(1 for x in data["stocks"] if (x.get("theme") or "") == key)
        attr = sum(1 for x in data["stocks"] if key in blob(x))
        print(f"  [{key}] 主{main} 属{attr}")

for symbol, label in (("sh600881", "亚泰"), ("sh601162", "天风")):
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={symbol},day,2024-09-26,2024-10-14,20,"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    )
    try:
        text = urllib.request.urlopen(req, timeout=15).read().decode()
        rows = ((json.loads(text).get("data") or {}).get(symbol) or {}).get("day") or []
        print(f"\n== {label} ==")
        for r in rows:
            print(r)
    except Exception as e:
        print(label, e)
