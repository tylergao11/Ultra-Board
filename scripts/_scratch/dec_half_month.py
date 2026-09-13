import json
import time
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
CACHE = Path("scripts/_scratch/bars_dec24")
CACHE.mkdir(parents=True, exist_ok=True)

DAYS = sorted(
    p.name
    for p in ROOT.iterdir()
    if p.is_dir()
    and "2024-11-26" <= p.name <= "2024-12-17"
    and (p / "zt_pool.json").exists()
)
FOCUS = ["广博股份", "葫芦娃", "益民集团", "二六三", "高乐股份"]


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def is_yizi(s):
    return hhmm(s.get("first_limit_ts")) == "09:25" and (s.get("turnover_rate") or 99) <= 6.5


def symbol(code):
    code = str(code).zfill(6)
    return ("sh" if code.startswith(("6", "5")) else "sz") + code


def fetch_one(code):
    code = str(code).zfill(6)
    path = CACHE / f"{code}.json"
    if path.exists():
        return code, json.loads(path.read_text(encoding="utf-8"))
    sym = symbol(code)
    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={sym},day,2024-11-20,2024-12-20,40,"
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://gu.qq.com/"}
    )
    text = urllib.request.urlopen(req, timeout=12).read().decode()
    rows = ((json.loads(text).get("data") or {}).get(sym) or {}).get("day") or []
    bars = {}
    for r in rows:
        bars[r[0]] = {
            "open": float(r[1]),
            "close": float(r[2]),
            "high": float(r[3]),
            "low": float(r[4]),
        }
    path.write_text(json.dumps(bars, ensure_ascii=False), encoding="utf-8")
    return code, bars


def pct(a, b):
    if not a or not b:
        return None
    return (a / b - 1) * 100


def median(xs):
    if not xs:
        return None
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def fmt(x):
    return "-" if x is None else f"{x:.2f}"


pools = {d: load(d) for d in DAYS}
codes = sorted(
    {
        str(s.get("code") or (s.get("raw") or [""])[0]).zfill(6)
        for data in pools.values()
        for s in data.get("stocks") or []
        if str(s.get("code") or (s.get("raw") or [""])[0]).zfill(6).isdigit()
    }
)
print(f"days={DAYS}")
print(f"unique_codes={len(codes)}")

bars = {}
fail = []
with ThreadPoolExecutor(max_workers=16) as ex:
    futs = {ex.submit(fetch_one, c): c for c in codes}
    for i, fut in enumerate(as_completed(futs), 1):
        c = futs[fut]
        try:
            code, b = fut.result()
            bars[code] = b
        except Exception as e:
            fail.append((c, str(e)[:80]))
        if i % 80 == 0:
            print(f"fetch {i}/{len(codes)} fail={len(fail)}")

print(f"bars_ok={len(bars)} fail={len(fail)}")
if fail[:8]:
    print("fail_sample", fail[:8])

# focus path
print("\n== FOCUS ==")
for d in DAYS:
    data = pools[d]
    by = {s["name"]: s for s in data.get("stocks") or []}
    print(f"{d} n={data.get('count')} H={data.get('max_board')}")
    for name in FOCUS:
        s = by.get(name)
        if not s:
            continue
        print(
            f"  {name} {s.get('boards')}板 换手{s.get('turnover_rate')} "
            f"{hhmm(s.get('first_limit_ts'))} {s.get('theme')} yizi={is_yizi(s)}"
        )


def nxt(day):
    i = DAYS.index(day)
    return DAYS[i + 1] if i + 1 < len(DAYS) else None


def row_of(s, day, nxt_day):
    code = str(s.get("code") or (s.get("raw") or [""])[0]).zfill(6)
    b = bars.get(code) or {}
    t = b.get(day)
    n = b.get(nxt_day)
    close_t = float(s.get("price") or 0) or (t["close"] if t else None)
    if not close_t or not n:
        return None
    return {
        "name": s.get("name"),
        "code": code,
        "day": day,
        "boards": s.get("boards") or 0,
        "yizi": is_yizi(s),
        "open_p": pct(n["open"], close_t),
        "close_p": pct(n["close"], close_t),
        "high_p": pct(n["high"], close_t),
        "again": n["close"] >= close_t * (1 + 0.095) if (s.get("limit_pct") or 10) < 15 else n["close"] >= close_t * (1 + 0.19),
    }


def bucket(rows, title):
    if not rows:
        print(f"{title} n=0")
        return
    op = [r["open_p"] for r in rows if r["open_p"] is not None]
    cp = [r["close_p"] for r in rows if r["close_p"] is not None]
    win_o = 100 * sum(x > 0 for x in op) / len(op) if op else None
    win_c = 100 * sum(x > 0 for x in cp) / len(cp) if cp else None
    win_flat = 100 * sum(x >= 0 for x in cp) / len(cp) if cp else None
    print(
        f"{title} n={len(rows)} "
        f"开盘溢价中位{fmt(median(op))} 均{fmt(mean(op))} 开盘胜{fmt(win_o)}% | "
        f"收盘中位{fmt(median(cp))} 均{fmt(mean(cp))} 收盘胜{fmt(win_c)}% 非负{fmt(win_flat)}% "
        f"再涨停{sum(1 for r in rows if r['again'])}/{len(rows)}"
    )


TOXIC = [d for d in DAYS if d <= "2024-12-13"]
print("\n== T->T+1 全涨停 按日 ==")
all_rows = []
yizi_rows = []
relay_obs = []
for d in TOXIC:
    nd = nxt(d)
    if not nd:
        continue
    day_rows = []
    for s in pools[d].get("stocks") or []:
        r = row_of(s, d, nd)
        if not r:
            continue
        day_rows.append(r)
        all_rows.append(r)
        if r["yizi"]:
            yizi_rows.append(r)
        if r["yizi"] and r["boards"] >= 2:
            relay_obs.append(r)
    bucket(day_rows, d)

print("\n== T->T+1 汇总 11.26-12.13 ==")
bucket(all_rows, "全涨停")
bucket(yizi_rows, "一字")
bucket(relay_obs, "二板+一字")
bucket([r for r in all_rows if r["boards"] >= 2], "二板+")
bucket([r for r in all_rows if r["boards"] >= 3], "三板+")

print("\n== 接力买法：T一字二板+ / 买T+1 / 看T+2 ==")
buy_next = []
for r in relay_obs:
    t1 = nxt(r["day"])
    t2 = nxt(t1) if t1 else None
    if not t2:
        continue
    b = bars.get(r["code"]) or {}
    a, c = b.get(t1), b.get(t2)
    if not a or not c:
        continue
    buy_next.append(
        {
            "name": r["name"],
            "obs": r["day"],
            "buy": t1,
            "open_p": pct(c["open"], a["close"]),
            "close_p": pct(c["close"], a["close"]),
            "again": False,
        }
    )
    buy_next[-1]["again"] = c["close"] >= a["close"] * 1.095
bucket(buy_next, "观察后买入的次日")
# also buy-day itself vs observe close
buy_day = []
for r in relay_obs:
    t1 = nxt(r["day"])
    if not t1:
        continue
    b = bars.get(r["code"]) or {}
    a = b.get(t1)
    obs = b.get(r["day"])
    close0 = obs["close"] if obs else None
    if not a or not close0:
        continue
    buy_day.append(
        {
            "name": r["name"],
            "open_p": pct(a["open"], close0),
            "close_p": pct(a["close"], close0),
            "again": a["close"] >= close0 * 1.095,
        }
    )
bucket(buy_day, "观察后买入当天")

print("\n== 12.16对照 全涨停T->T+1 ==")
d, nd = "2024-12-16", "2024-12-17"
rows16 = []
for s in pools[d].get("stocks") or []:
    r = row_of(s, d, nd)
    if r:
        rows16.append(r)
bucket(rows16, "12.16全涨停")
bucket([r for r in rows16 if r["yizi"] and r["boards"] >= 2], "12.16二板+一字")

print("\n== 具名票 T+1 ==")
for name in FOCUS:
    for r in all_rows + rows16:
        if r["name"] == name:
            print(
                f"  {r['day']} {name} {r['boards']}板 yizi={r['yizi']} "
                f"次日开{fmt(r['open_p'])} 收{fmt(r['close_p'])}"
            )
