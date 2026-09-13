import json
import urllib.request

url = (
    "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    "?param=sz000566,day,2024-09-06,2024-09-20,20,"
)
req = urllib.request.Request(
    url,
    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"},
)
text = urllib.request.urlopen(req, timeout=15).read().decode()
data = json.loads(text)
rows = ((data.get("data") or {}).get("sz000566") or {}).get("day") or []
print("date open close high low vol")
for r in rows:
    print(r)
