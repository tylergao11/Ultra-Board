import json
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
ZB = Path("data/ths/open_limit_pool")
TZ = timezone(timedelta(hours=8))
YIZI_TURN = 6.5

TRADES = [
    ("001379", "2024-07-30"), ("600326", "2024-08-15"), ("000062", "2024-08-20"),
    ("002302", "2024-08-27"), ("603626", "2024-09-03"), ("000566", "2024-09-11"),
    ("002583", "2024-09-25"), ("600881", "2024-09-26"), ("002628", "2024-10-18"),
    ("002542", "2024-10-30"), ("000833", "2024-11-15"), ("002348", "2024-11-27"),
    ("002730", "2024-12-25"), ("000533", "2025-01-02"), ("002917", "2025-01-13"),
    ("603928", "2025-01-22"), ("605398", "2025-02-05"), ("601177", "2025-02-14"),
    ("002522", "2025-02-24"), ("002910", "2025-02-26"), ("603700", "2025-03-05"),
    ("000665", "2025-03-10"), ("603677", "2025-03-14"), ("002278", "2025-03-20"),
    ("002767", "2025-03-25"), ("002549", "2025-04-01"),
]

days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
didx = {d: i for i, d in enumerate(days)}
_zt = {}
_zb = {}


def load_zt(day):
    if day not in _zt:
        _zt[day] = json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))
    return _zt[day]


def stocks(day):
    return load_zt(day).get("stocks") or []


def hhmm(ts):
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M")


def is_st(name):
    n = name or ""
    return "ST" in n.upper()


def keep_code(code):
    return code and not code.startswith(("4", "8", "9")) and not code.startswith("688")


def is_yizi(s):
    if hhmm(s.get("first_limit_ts")) != "09:25":
        return False
    t = s.get("turnover_rate")
    return t is not None and t <= YIZI_TURN


def sector_count(day, sector):
    if not sector:
        return 0
    return sum(1 for s in stocks(day) if (s.get("sector_code") or "") == sector)


def zb_codes(day):
    if day in _zb:
        return _zb[day]
    p = ZB / f"{day}.json"
    if not p.exists():
        _zb[day] = None
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    _zb[day] = {str(s.get("code")).zfill(6) for s in data.get("stocks") or []}
    return _zb[day]


def find(day, code):
    for s in stocks(day):
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


print("==== 用板块代码核对你的一字日 ====")
for code, buy in TRADES:
    i = didx[buy]
    yizi_day, prev = days[i - 1], days[i - 2]
    s = find(yizi_day, code)
    if not s:
        print(f"{code} {buy} 一字日{yizi_day} 不在池")
        continue
    sec = s.get("sector_code") or ""
    n1, n0 = sector_count(yizi_day, sec), sector_count(prev, sec)
    higher = [
        x.get("name")
        for x in stocks(yizi_day)
        if (x.get("sector_code") or "") == sec
        and str(x.get("code")).zfill(6) != code
        and is_yizi(x)
        and (x.get("boards") or 0) > (s.get("boards") or 0)
    ]
    print(
        f"{s.get('name')} 一字{yizi_day} {s.get('boards')}板 换手{s.get('turnover_rate')} "
        f"{s.get('theme')}/{sec} 板块{n0}->{n1} "
        f"一字={'Y' if is_yizi(s) else 'N'} 降={'Y' if n1 < n0 else 'N'} "
        f"头顶={higher or '无'}"
    )
