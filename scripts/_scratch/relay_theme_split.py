import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

ROOT = Path("data/kaipanla/raw")
TZ = timezone(timedelta(hours=8))
days = sorted(p.name for p in ROOT.iterdir() if (p / "zt_pool.json").exists())
days = [d for d in days if "2024-07-22" <= d <= "2025-04-10"]
didx = {d: i for i, d in enumerate(days)}
_c = {}


def data(day):
    if day not in _c:
        _c[day] = json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))
    return _c[day]


def pool(day):
    return {str(s["code"]).zfill(6): s for s in data(day)["stocks"]}


def hhmm(ts):
    return datetime.fromtimestamp(int(ts), TZ).strftime("%H:%M") if ts else "-"


def theme_count(day, theme):
    return sum(1 for s in data(day)["stocks"] if theme and theme in ((s.get("theme_tags_text") or "") + "|" + (s.get("theme") or "")))


def future(code, day):
    lb = None
    for d in days[didx[day]:]:
        s = pool(d).get(code)
        if s:
            lb = s["boards"]
        elif lb is not None:
            break
    return lb


rows = []
for i in range(2, len(days)):
    d, d1, d2 = days[i], days[i - 1], days[i - 2]
    cur, pre = pool(d), pool(d1)
    for code, s in cur.items():
        p = pre.get(code)
        if not p or hhmm(p.get("first_limit_ts")) != "09:25" or (p.get("turnover_rate") or 99) > 6.5 or (p.get("boards") or 0) < 2:
            continue
        if (s.get("turnover_rate") or 0) < 8:
            continue
        theme = p.get("theme")
        c2, c1 = theme_count(d2, theme), theme_count(d1, theme)
        trend = "降" if c1 < c2 else ("平" if c1 == c2 else "升")
        extra = (future(code, d) or 0) - s["boards"]
        rows.append((d, s["name"], theme, c2, c1, trend, s["boards"], extra))

for trend in ("降", "平", "升"):
    sub = [r for r in rows if r[5] == trend]
    if not sub:
        continue
    ex = [r[7] for r in sub]
    dist = Counter(min(e, 4) for e in ex)
    print(f"{trend}级  n={len(sub)}  extra=0:{dist[0]}  1:{dist[1]}  2:{dist[2]}  3:{dist[3]}  >=4:{dist[4]}  "
          f"再加>=2占比 {sum(1 for e in ex if e >= 2) / len(ex):.0%}  均值 {sum(ex) / len(ex):.2f}")

print("\n升级组里 extra>=2 的：")
for r in rows:
    if r[5] == "升" and r[7] >= 2:
        print(" ", r[0], r[1], r[2], f"{r[3]}->{r[4]}", f"{r[6]}板 extra={r[7]}")
print("\n降级组里 extra>=4 的：")
for r in rows:
    if r[5] == "降" and r[7] >= 4:
        print(" ", r[0], r[1], r[2], f"{r[3]}->{r[4]}", f"{r[6]}板 extra={r[7]}")
