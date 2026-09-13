import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
TZ = timezone(timedelta(hours=8))
days = sorted(
    p.name for p in ROOT.iterdir() if p.is_dir() and (p / "zt_pool.json").exists()
)
didx = {d: i for i, d in enumerate(days)}

trades = [
    ("001379", "腾达科技", "2024-07-30"),
    ("600326", "西藏天路", "2024-08-15"),
    ("000062", "深圳华强", "2024-08-20"),
    ("002302", "西部建设", "2024-08-27"),
    ("603626", "科森科技", "2024-09-03"),
    ("000566", "海南海药", "2024-09-11"),
    ("002583", "海能达", "2024-09-25"),
    ("600881", "亚泰集团", "2024-09-26"),
    ("002628", "成都路桥", "2024-10-18"),
    ("002542", "中化岩土", "2024-10-30"),
    ("000833", "粤桂股份", "2024-11-15"),
    ("002348", "高乐股份", "2024-11-26"),
    ("002730", "电光科技", "2024-12-25"),
    ("000533", "顺钠股份", "2025-01-02"),
    ("002917", "金奥博", "2025-01-13"),
    ("603928", "兴业股份", "2025-01-22"),
    ("605398", "新炬网络", "2025-02-05"),
    ("601177", "杭齿前进", "2025-02-14"),
    ("002522", "浙江众成", "2025-02-24"),
    ("002910", "庄园牧场", "2025-02-26"),
    ("603700", "宁水集团", "2025-03-05"),
    ("000665", "湖北广电", "2025-03-10"),
    ("603677", "奇精机械", "2025-03-13"),
    ("002278", "神开股份", "2025-03-20"),
    ("002767", "先锋电子", "2025-03-24"),
    ("002549", "凯美特气", "2025-04-01"),
]

_cache = {}


def load(day):
    if day not in _cache:
        p = ROOT / day / "zt_pool.json"
        _cache[day] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return _cache[day]


def find(day, code):
    data = load(day)
    if not data:
        return None
    for s in data.get("stocks") or []:
        if str(s.get("code")).zfill(6) == code:
            return s
    return None


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


print(f"{'name':<6} {'buy':<10} {'D-1':<10} {'D-1板':>4} {'D-1换手':>7} {'D-1首封':>6} | {'D板':>3} {'D换手':>6} {'D首封':>6}")
for code, name, buy in trades:
    i = didx[buy]
    prev = days[i - 1]
    p = find(prev, code)
    b = find(buy, code)
    pb = p.get("boards") if p else None
    pt = p.get("turnover_rate") if p else None
    pf = hhmm(p.get("first_limit_ts")) if p else "-"
    print(
        f"{name:<6} {buy} {prev} {str(pb):>4} {str(pt):>7} {pf:>6} | "
        f"{str(b.get('boards')):>3} {str(b.get('turnover_rate')):>6} {hhmm(b.get('first_limit_ts')):>6}"
    )
