import json
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("data/kaipanla/raw")
BARS = Path("scripts/_scratch/bars_dec24")
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


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def yizi(s):
    return hhmm(s.get("first_limit_ts")) == "09:25" and (s.get("turnover_rate") or 99) <= 6.5


def blob(s):
    return (s.get("theme") or "") + "|" + (s.get("theme_tags_text") or "")


def circ_yi(s):
    raw = s.get("raw") or []
    try:
        v = float(raw[13]) / 1e8
        return round(v, 1)
    except Exception:
        return None


pools = {
    d: json.loads((ROOT / d / "zt_pool.json").read_text(encoding="utf-8"))
    for d in DAYS
}
bars = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in BARS.glob("*.json")}


def nxt(d):
    i = DAYS.index(d)
    return DAYS[i + 1] if i + 1 < len(DAYS) else None


def t1(s, d):
    nd = nxt(d)
    code = str(s.get("code") or "").zfill(6)
    b = (bars.get(code) or {}).get(nd) if nd else None
    close0 = float(s.get("price") or 0)
    if not b or not close0:
        return "-"
    op = (b["open"] / close0 - 1) * 100
    cp = (b["close"] / close0 - 1) * 100
    return f"次日开{op:+.1f}收{cp:+.1f}"


def counts(stocks, key):
    main = sum(1 for s in stocks if (s.get("theme") or "") == key)
    attr = sum(1 for s in stocks if key in blob(s))
    return main, attr


prev = None
for d in DAYS:
    data = pools[d]
    stocks = data.get("stocks") or []
    print(f"\n======== {d} n={data.get('count')} H={data.get('max_board')} ========")
    print("top", ", ".join(f"{k}{v}" for k, v in Counter((s.get("theme") or "?") for s in stocks).most_common(6)))
    highs = sorted(stocks, key=lambda x: -(x.get("boards") or 0))[:6]
    print(
        "高度",
        " | ".join(
            f"{s['name']}{s.get('boards')}板/{s.get('theme')}/{hhmm(s.get('first_limit_ts'))}/{s.get('turnover_rate')}%"
            for s in highs
        ),
    )
    cands = [s for s in stocks if yizi(s) and (s.get("boards") or 0) >= 2]
    cands.sort(key=lambda x: -(x.get("boards") or 0))
    if not cands:
        print("二板+一字 无")
    for s in cands:
        th = s.get("theme") or "?"
        pm = pa = None
        if prev:
            pm, pa = counts(prev, th)
        m, a = counts(stocks, th)
        delta = f"主{pm}->{m} 属{pa}->{a}" if prev else f"主{m} 属{a}"
        print(
            f"  {s['name']} {s.get('boards')}板 {th} 换手{s.get('turnover_rate')} "
            f"流通{circ_yi(s)}亿 tags={s.get('theme_tags_text')} {delta} {t1(s, d)}"
        )
    prev = stocks
