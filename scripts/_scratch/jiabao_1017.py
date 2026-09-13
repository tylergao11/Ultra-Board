import json
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
url = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param=sh600622,day,2024-10-11,2024-10-22,20,"
)
req = urllib.request.Request(
    url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
)
text = urllib.request.urlopen(req, timeout=15).read().decode()
rows = ((json.loads(text).get("data") or {}).get("sh600622") or {}).get("day") or []
print("date open close high low vol")
for r in rows:
    print(r)
