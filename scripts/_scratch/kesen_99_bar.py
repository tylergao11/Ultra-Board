import json
import urllib.request

ua = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn/",
}

urls = [
    (
        "tencent",
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh603626,day,2024-09-01,2024-09-12,20,",
    ),
    (
        "sina",
        "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sh603626&scale=240&ma=no&datalen=40",
    ),
]

for name, url in urls:
    try:
        req = urllib.request.Request(url, headers=ua)
        raw = urllib.request.urlopen(req, timeout=15).read()
        text = raw.decode("utf-8", "replace")
        print("====", name, "len", len(text))
        print(text[:2500])
    except Exception as e:
        print("====", name, "ERR", type(e).__name__, e)
