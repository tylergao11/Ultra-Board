import json
import time
import urllib.request

CODES = {
    "001379": "腾达科技",
    "000062": "深圳华强",
    "002302": "西部建设",
    "603626": "科森科技",
    "000566": "海南海药",
    "002583": "海能达",
    "600622": "光大嘉宝",
    "002628": "成都路桥",
    "002542": "中化岩土",
    "603918": "金桥信息",
    "000833": "粤桂股份",
}


def fetch(code):
    url = (
        f"https://q.stock.sohu.com/hisHq?code=cn_{code}"
        "&start=20240722&end=20241127&stat=1&order=A"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    text = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "replace")
    hq = (json.loads(text)[0] or {}).get("hq") or []
    out = {}
    for r in hq:
        out[r[0]] = {
            "open": float(r[1]),
            "close": float(r[2]),
            "low": float(r[5]),
            "high": float(r[6]),
        }
    return out


all_bars = {}
for code, name in CODES.items():
    try:
        all_bars[code] = fetch(code)
        print("ok", code, name, len(all_bars[code]))
    except Exception as e:
        print("fail", code, e)
    time.sleep(0.15)

need = {
    "001379": ["2024-07-30", "2024-08-05", "2024-08-06"],
    "000062": ["2024-08-20", "2024-08-28", "2024-08-29"],
    "002302": ["2024-08-28", "2024-08-29", "2024-08-30"],
    "603626": ["2024-09-03", "2024-09-06", "2024-09-09"],
    "000566": ["2024-09-11", "2024-09-13", "2024-09-18"],
    "002583": ["2024-09-25", "2024-09-26", "2024-09-27"],
    "600622": ["2024-10-16", "2024-10-17"],
    "002628": ["2024-10-18", "2024-10-23", "2024-10-24"],
    "002542": ["2024-10-30", "2024-11-07", "2024-11-08"],
    "603918": ["2024-11-13", "2024-11-14"],
    "000833": ["2024-11-15", "2024-11-25", "2024-11-26"],
}
print("\n== bars ==")
for code, days in need.items():
    b = all_bars.get(code) or {}
    print(f"\n{CODES[code]} {code}")
    for d in days:
        print(" ", d, b.get(d))
