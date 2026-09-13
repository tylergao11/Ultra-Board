import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
DAYS = ["2024-12-11", "2024-12-12", "2024-12-13", "2024-12-16", "2024-12-17"]


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


def circ(s):
    raw = s.get("raw") or []
    try:
        return round(float(raw[13]) / 1e8, 1)
    except Exception:
        return None


for d in DAYS:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    stocks = data.get("stocks") or []
    print(f"\n==== {d} n={data.get('count')} H={data.get('max_board')} ====")
    print("top", ", ".join(f"{k}{v}" for k, v in Counter((s.get("theme") or "?") for s in stocks).most_common(6)))
    s = next((x for x in stocks if x["name"] == "三维通信"), None)
    if not s:
        print("  三维通信 不在池")
    else:
        raw = s.get("raw") or []
        print(
            f"  三维通信 {s.get('code')} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"{hhmm(s.get('first_limit_ts'))} theme={s.get('theme')} sec={s.get('sector_code')} "
            f"tags={s.get('theme_tags_text')} open={raw[16] if len(raw)>16 else None} "
            f"流通{circ(s)}亿 price={s.get('price')}"
        )
    for key in ["文化传媒", "通信", "腾讯", "AI视频"]:
        rows = [x for x in stocks if key in blob(x)]
        main = [x for x in stocks if key in (x.get("theme") or "")]
        if not rows:
            continue
        print(f"  [{key}] 主{len(main)}属{len(rows)}")
        print(
            "   ",
            ", ".join(
                f"{x['name']}{x['boards']}板/{x.get('theme')}/"
                f"{hhmm(x.get('first_limit_ts'))}/{x['turnover_rate']}%"
                for x in sorted(rows, key=lambda z: -(z.get("boards") or 0))[:10]
            ),
        )
