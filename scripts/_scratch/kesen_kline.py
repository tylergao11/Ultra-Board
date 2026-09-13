import json
import urllib.request

url = (
    "https://push2his.eastmoney.com/api/qt/stock/kline/get"
    "?secid=1.603626&fields1=f1,f2,f3,f4,f5,f6"
    "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
    "&klt=101&fqt=0&beg=20240826&end=20240912&lmt=1000"
)
req = urllib.request.Request(
    url,
    headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    },
)
data = json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
print("name", (data.get("data") or {}).get("name"))
for x in (data.get("data") or {}).get("klines") or []:
    print(x)
