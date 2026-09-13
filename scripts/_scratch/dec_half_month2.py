import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
CACHE = Path("scripts/_scratch/bars_dec24")

DAYS = [
    "2024-11-26",
    "2024-11-27",
    "2024-11-28",
    "2024-11-29",
    "2024-12-02",
    "2024-12-03",
    "2024-12-04",
    "2024-12-05",
    "2024-12-06",
    "2024-12-09",
    "2024-12-10",
    "2024-12-11",
    "2024-12-12",
    "2024-12-13",
    "2024-12-16",
    "2024-12-17",
]
MAD = {"广博股份", "葫芦娃"}


def load(d):
    return json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def is_yizi(s):
    return hhmm(s.get("first_limit_ts")) == "09:25" and (s.get("turnover_rate") or 99) <= 6.5


def pct(a, b):
    return (a / b - 1) * 100 if a and b else None


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
bars = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in CACHE.glob("*.json")}


def nxt(day):
    i = DAYS.index(day)
    return DAYS[i + 1] if i + 1 < len(DAYS) else None


def row_of(s, day, nd):
    code = str(s.get("code") or (s.get("raw") or [""])[0]).zfill(6)
    b = bars.get(code) or {}
    t, n = b.get(day), b.get(nd)
    close_t = float(s.get("price") or 0) or (t["close"] if t else None)
    if not close_t or not n:
        return None
    return {
        "name": s.get("name"),
        "code": code,
        "day": day,
        "theme": s.get("theme") or "",
        "boards": s.get("boards") or 0,
        "yizi": is_yizi(s),
        "turn": s.get("turnover_rate"),
        "open_p": pct(n["open"], close_t),
        "close_p": pct(n["close"], close_t),
        "again": n["close"] >= close_t * (1.095 if (s.get("limit_pct") or 10) < 15 else 1.19),
    }


def bucket(rows, title):
    if not rows:
        print(f"{title} n=0")
        return
    op = [r["open_p"] for r in rows]
    cp = [r["close_p"] for r in rows]
    print(
        f"{title} n={len(rows)} "
        f"开盘中位{fmt(median(op))} 均{fmt(mean(op))} 开盘胜{100*sum(x>0 for x in op)/len(op):.1f}% | "
        f"收盘中位{fmt(median(cp))} 均{fmt(mean(cp))} 收盘胜{100*sum(x>0 for x in cp)/len(cp):.1f}% "
        f"再涨停{sum(1 for r in rows if r['again'])}/{len(rows)}"
    )


def collect(days, pred):
    out = []
    for d in days:
        nd = nxt(d)
        if not nd:
            continue
        for s in pools[d].get("stocks") or []:
            if not pred(s, d):
                continue
            r = row_of(s, d, nd)
            if r:
                out.append(r)
    return out


def relay_t2(obs_rows):
    out = []
    for r in obs_rows:
        t1, t2 = nxt(r["day"]), nxt(nxt(r["day"])) if nxt(r["day"]) else None
        if not t2:
            continue
        b = bars.get(r["code"]) or {}
        a, c = b.get(t1), b.get(t2)
        if not a or not c:
            continue
        out.append(
            {
                "name": r["name"],
                "day": r["day"],
                "open_p": pct(c["open"], a["close"]),
                "close_p": pct(c["close"], a["close"]),
                "again": c["close"] >= a["close"] * 1.095,
            }
        )
    return out


pre = [d for d in DAYS if "2024-11-26" <= d <= "2024-12-02"]
post = [d for d in DAYS if "2024-12-03" <= d <= "2024-12-13"]
alld = [d for d in DAYS if d <= "2024-12-13"]

print("== 广博还在 11.26-12.02 ==")
bucket(collect(pre, lambda s, d: True), "全涨停")
bucket(collect(pre, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2), "二板+一字")
bucket(
    collect(pre, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2 and s.get("name") not in MAD),
    "二板+一字 剔广博葫芦娃",
)
bucket(
    collect(pre, lambda s, d: is_yizi(s) and 2 <= (s.get("boards") or 0) <= 4 and s.get("name") not in MAD),
    "2-4板一字 剔疯狗",
)

print("\n== 广博死后 12.03-12.13 ==")
bucket(collect(post, lambda s, d: True), "全涨停")
bucket(collect(post, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2), "二板+一字")
bucket(
    collect(post, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2 and s.get("name") not in MAD),
    "二板+一字 剔广博葫芦娃",
)
bucket(
    collect(post, lambda s, d: is_yizi(s) and 2 <= (s.get("boards") or 0) <= 4 and s.get("name") not in MAD),
    "2-4板一字 剔疯狗",
)
bucket(
    collect(post, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 5 and s.get("name") not in MAD),
    "5板+一字 剔疯狗",
)

print("\n== 接力：观察一字二板+ 剔疯狗，买次日，再看次日 ==")
obs_pre = collect(pre, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2 and s.get("name") not in MAD)
obs_post = collect(post, lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2 and s.get("name") not in MAD)
# post collect already has T+1; rebuild observe list from pools
obs_pre = []
obs_post = []
for d in alld:
    for s in pools[d].get("stocks") or []:
        if is_yizi(s) and (s.get("boards") or 0) >= 2 and s.get("name") not in MAD:
            rec = {"name": s.get("name"), "code": str(s.get("code")).zfill(6), "day": d, "boards": s.get("boards")}
            if d <= "2024-12-02":
                obs_pre.append(rec)
            elif d <= "2024-12-12":
                obs_post.append(rec)
bucket(relay_t2(obs_pre), "11.26-12.02观察 买入次日")
bucket(relay_t2(obs_post), "12.03-12.12观察 买入次日")

print("\n== 12.03当天想开仓：次日 ==")
bucket(collect(["2024-12-03"], lambda s, d: True), "12.03全涨停")
bucket(collect(["2024-12-03"], lambda s, d: is_yizi(s)), "12.03一字")
bucket(
    collect(["2024-12-03"], lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2 and s.get("name") not in MAD),
    "12.03二板+一字剔疯狗",
)

print("\n== 12.03 二板+一字名单 次日 ==")
for r in collect(["2024-12-03"], lambda s, d: is_yizi(s) and (s.get("boards") or 0) >= 2):
    print(f"  {r['name']} {r['boards']}板 {r['theme']} 换手{r['turn']} 次日开{fmt(r['open_p'])} 收{fmt(r['close_p'])}")

print("\n== 12.04-12.12 每天2-4板一字剔疯狗 ==")
for d in [x for x in post if x <= "2024-12-12"]:
    rows = collect([d], lambda s, dd: is_yizi(s) and 2 <= (s.get("boards") or 0) <= 4 and s.get("name") not in MAD)
    bucket(rows, d)
    for r in rows:
        print(f"    {r['name']} {r['boards']}板 {r['theme']} 次日开{fmt(r['open_p'])} 收{fmt(r['close_p'])}")

print("\n== 葫芦娃日线 ==")
b = bars.get("300571") or {}
for d, x in sorted(b.items()):
    print(d, x)
print("\n== 广博日线 ==")
b = bars.get("002103") or {}
for d, x in sorted(b.items()):
    print(d, x)
print("\n== 益民日线 ==")
b = bars.get("600824") or {}
for d, x in sorted(b.items()):
    print(d, x)
