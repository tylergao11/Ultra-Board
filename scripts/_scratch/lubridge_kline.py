import json
import urllib.request

url = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param=sz002628,day,2024-10-17,2024-10-28,20,"
)
req = urllib.request.Request(
    url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
)
text = urllib.request.urlopen(req, timeout=15).read().decode()
rows = ((json.loads(text).get("data") or {}).get("sz002628") or {}).get("day") or []
print("date open close high low vol")
for r in rows:
    print(r)
