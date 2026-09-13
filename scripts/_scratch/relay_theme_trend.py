import json
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
didx = {d: i for i, d in enumerate(days)}

trades = [
    ("001379", "腾达科技", "2024-07-30"), ("600326", "西藏天路", "2024-08-15"),
    ("000062", "深圳华强", "2024-08-20"), ("002302", "西部建设", "2024-08-27"),
    ("603626", "科森科技", "2024-09-03"), ("000566", "海南海药", "2024-09-11"),
    ("002583", "海能达", "2024-09-25"), ("600881", "亚泰集团", "2024-09-26"),
    ("002628", "成都路桥", "2024-10-18"), ("002542", "中化岩土", "2024-10-30"),
    ("000833", "粤桂股份", "2024-11-15"), ("002348", "高乐股份", "2024-11-27"),
    ("002730", "电光科技", "2024-12-25"), ("000533", "顺钠股份", "2025-01-02"),
    ("002917", "金奥博", "2025-01-13"), ("603928", "兴业股份", "2025-01-22"),
    ("605398", "新炬网络", "2025-02-05"), ("601177", "杭齿前进", "2025-02-14"),
    ("002522", "浙江众成", "2025-02-24"), ("002910", "庄园牧场", "2025-02-26"),
    ("603700", "宁水集团", "2025-03-05"), ("000665", "湖北广电", "2025-03-10"),
    ("603677", "奇精机械", "2025-03-14"), ("002278", "神开股份", "2025-03-20"),
    ("002767", "先锋电子", "2025-03-25"), ("002549", "凯美特气", "2025-04-01"),
]
_c = {}


def pool(day):
    if day not in _c:
        _c[day] = json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))
    return _c[day]


def theme_count(day, theme):
    n = 0
    for s in pool(day)["stocks"]:
        tags = (s.get("theme_tags_text") or "") + "|" + (s.get("theme") or "")
        if theme and theme in tags:
            n += 1
    return n


print(f"{'name':<6} {'buy':<10} {'theme':<8} {'D-2':>4} {'D-1':>4} {'D':>4}  全场D-2/D-1/D  趋势(D-2→D-1)")
for code, name, buy in trades:
    i = didx[buy]
    d1, d2 = days[i - 1], days[i - 2]
    s1 = next((s for s in pool(d1)["stocks"] if str(s["code"]).zfill(6) == code), None)
    theme = s1.get("theme") if s1 else "?"
    c2, c1, c0 = theme_count(d2, theme), theme_count(d1, theme), theme_count(buy, theme)
    t2, t1, t0 = pool(d2)["count"], pool(d1)["count"], pool(buy)["count"]
    trend = "降" if c1 < c2 else ("平" if c1 == c2 else "升")
    print(f"{name:<6} {buy} {theme:<8} {c2:>4} {c1:>4} {c0:>4}  {t2}/{t1}/{t0}  {trend}")
