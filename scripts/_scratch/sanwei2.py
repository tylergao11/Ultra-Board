import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


for d in ["2024-12-12", "2024-12-13", "2024-12-16"]:
    data = json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    stocks = data["stocks"]
    rows = [s for s in stocks if "字节" in blob(s)]
    main = [s for s in stocks if "字节" in (s.get("theme") or "")]
    print(d, "字节 主", len(main), "属", len(rows))
    print(
        "  ",
        ", ".join(
            f"{s['name']}{s['boards']}板/{s.get('theme')}/{hhmm(s.get('first_limit_ts'))}/{s['turnover_rate']}%"
            for s in sorted(rows, key=lambda x: -(x.get("boards") or 0))
        ),
    )

req = urllib.request.Request(
    "https://q.stock.sohu.com/hisHq?code=cn_002115&start=20241210&end=20241217&stat=1&order=D",
    headers={"User-Agent": "Mozilla/5.0"},
)
print(urllib.request.urlopen(req, timeout=15).read().decode("gbk", "replace")[:1400])
