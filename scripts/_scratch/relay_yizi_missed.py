import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("data/kaipanla/raw")
TZ = timezone(timedelta(hours=8))
days = sorted(
    p.name for p in ROOT.iterdir() if p.is_dir() and (p / "zt_pool.json").exists()
)
days = [d for d in days if "2024-07-22" <= d <= "2025-04-10"]
didx = {d: i for i, d in enumerate(days)}

buys = {
    "2024-07-30": "001379", "2024-08-15": "600326", "2024-08-20": "000062",
    "2024-08-27": "002302", "2024-09-03": "603626", "2024-09-11": "000566",
    "2024-09-25": "002583", "2024-09-26": "600881", "2024-10-18": "002628",
    "2024-10-30": "002542", "2024-11-15": "000833", "2024-11-26": "002348",
    "2024-12-25": "002730", "2025-01-02": "000533", "2025-01-13": "002917",
    "2025-01-22": "603928", "2025-02-05": "605398", "2025-02-14": "601177",
    "2025-02-24": "002522", "2025-02-26": "002910", "2025-03-05": "603700",
    "2025-03-10": "000665", "2025-03-13": "603677", "2025-03-20": "002278",
    "2025-03-24": "002767", "2025-04-01": "002549",
}
# 持仓区间（买日..断板前一日）用于标记当天是否满仓
holds = [
    ("2024-07-30", "2024-08-05"), ("2024-08-15", "2024-08-15"), ("2024-08-20", "2024-08-26"),
    ("2024-08-27", "2024-08-29"), ("2024-09-03", "2024-09-06"), ("2024-09-11", "2024-09-13"),
    ("2024-09-25", "2024-09-25"), ("2024-09-26", "2024-10-08"), ("2024-10-18", "2024-10-23"),
    ("2024-10-30", "2024-11-07"), ("2024-11-15", "2024-11-25"), ("2024-11-26", "2024-11-26"),
    ("2024-12-25", "2024-12-27"), ("2025-01-02", "2025-01-03"), ("2025-01-13", "2025-01-17"),
    ("2025-01-22", "2025-01-24"), ("2025-02-05", "2025-02-12"), ("2025-02-14", "2025-02-21"),
    ("2025-02-24", "2025-02-24"), ("2025-02-26", "2025-02-27"), ("2025-03-05", "2025-03-06"),
    ("2025-03-10", "2025-03-12"), ("2025-03-13", "2025-03-20"), ("2025-03-20", "2025-03-21"),
    ("2025-03-24", "2025-03-25"), ("2025-04-01", "2025-04-02"),
]

_cache = {}


def load(day):
    if day not in _cache:
        p = ROOT / day / "zt_pool.json"
        _cache[day] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    return _cache[day]


def pool(day):
    data = load(day)
    return {str(s.get("code")).zfill(6): s for s in (data or {}).get("stocks") or []}


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def is_yizi(s):
    return hhmm(s.get("first_limit_ts")) == "09:25" and (s.get("turnover_rate") or 99) <= 6.5


def future(code, day):
    last_d, last_b = None, None
    for d in days[didx[day]:]:
        s = pool(d).get(code)
        if s:
            last_d, last_b = d, s.get("boards")
        elif last_d:
            break
    return last_d, last_b


def holding(day):
    return any(a <= day <= b for a, b in holds)


print("口径：D-1 一字(09:25首封且换手<=6.5%) 且 D-1>=2板；D 涨停且换手>=8%（开板回封）")
print()
for i in range(1, len(days)):
    d, prev = days[i], days[i - 1]
    cur, pre = pool(d), pool(prev)
    rows = []
    for code, s in cur.items():
        p = pre.get(code)
        if not p or not is_yizi(p) or (p.get("boards") or 0) < 2:
            continue
        if (s.get("turnover_rate") or 0) < 8:
            continue
        ld, lb = future(code, d)
        extra = (lb or 0) - (s.get("boards") or 0)
        rows.append((code, s, p, ld, lb, extra))
    if not rows:
        continue
    data = load(d)
    tag = "买日" if d in buys else ("持仓中" if holding(d) else "空仓")
    print(f"### {d}  涨停{data.get('count')} H={data.get('max_board')}  [{tag}]")
    for code, s, p, ld, lb, extra in sorted(rows, key=lambda r: -r[5]):
        mark = " <== 已买" if buys.get(d) == code else ""
        print(
            f"  {code} {s.get('name')} {p.get('boards')}板一字{p.get('turnover_rate')}% -> "
            f"{s.get('boards')}板 换手{s.get('turnover_rate')} 首封{hhmm(s.get('first_limit_ts'))} "
            f"{s.get('theme')} 此后->{lb}板/{ld} extra={extra}{mark}"
        )
    print()
