# -*- coding: utf-8 -*-
import json
import sys
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


def load(day):
    p = ROOT / day / "zt_pool.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def tags_of(s):
    raw = s.get("raw") or []
    return str(s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "") or "")


def blob(s):
    return str(s.get("theme") or "") + " " + tags_of(s)


def oc_of(s):
    oc = s.get("open_count")
    raw = s.get("raw") or []
    if oc is None and len(raw) > 16:
        oc = raw[16]
    return oc


def yizi(s):
    first = ts(s.get("first_limit_ts"))
    oc = oc_of(s)
    to = float(s.get("turnover_rate") or 99)
    ok = first.startswith("09:25") and to <= 6.5 and oc in (0, None, 0)
    return ok, first, oc, to


def count_key(stocks, key):
    theme_n = sum(1 for s in stocks if key in str(s.get("theme") or ""))
    attr_n = sum(1 for s in stocks if key in blob(s))
    return theme_n, attr_n


print("=== 湖北广电轨迹 ===")
for d in ("2025-03-10", "2025-03-11", "2025-03-12", "2025-03-13", "2025-03-14"):
    data = load(d)
    if not data:
        continue
    hit = next((s for s in (data.get("stocks") or []) if s.get("name") == "湖北广电"), None)
    if not hit:
        print(f"{d} 不在  涨停{data.get('count')} 最高{data.get('max_board')}")
        continue
    ok, first, oc, to = yizi(hit)
    print(
        f"{d} {hit.get('boards')}板 {hit.get('boards_desc')} "
        f"{'一字' if ok else '开/松'} 主题={hit.get('theme')} 换手={to} 开板={oc} 首封={first}"
    )

prev = load("2025-03-12")
cur = load("2025-03-13")
nxt = load("2025-03-14")
ps, cs = prev.get("stocks") or [], cur.get("stocks") or []

print("\n3.12 涨停", prev.get("count"), "最高", prev.get("max_board"))
print("软件主标签", Counter(str(s.get("theme") or "?") for s in ps).most_common(10))
print("3.13 涨停", cur.get("count"), "最高", cur.get("max_board"))
print("软件主标签", Counter(str(s.get("theme") or "?") for s in cs).most_common(10))

print("\n-- 3.13 严口径一字 --")
yizis = []
for s in sorted(cs, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
    ok, first, oc, to = yizi(s)
    if ok:
        yizis.append(s)
        print(
            f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 {s.get('boards_desc')} "
            f"主题={s.get('theme')} 标签={tags_of(s)} 换手={to}"
        )

print("\n-- 3.13 09:25开板0 换手不论 2板+ --")
for s in sorted(cs, key=lambda x: (-int(x.get("boards") or 0), float(s.get("turnover_rate") or 99))):
    first = ts(s.get("first_limit_ts"))
    oc = oc_of(s)
    to = float(s.get("turnover_rate") or 99)
    if int(s.get("boards") or 0) < 2:
        continue
    if first.startswith("09:25") and oc in (0, None, 0):
        print(f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 换手={to} 标签={tags_of(s)}")

print("\n-- 一字软件主题 3.12→3.13 --")
for s in yizis:
    theme = str(s.get("theme") or "")
    pt, pa = count_key(ps, theme)
    ct, ca = count_key(cs, theme)
    print(
        f"  {s.get('name')} [{theme}] 软件主标签 {pt}→{ct}  自身属性 {pa}→{ca}"
    )

print("\n-- 3.14 这几只 --")
by = {s.get("name"): s for s in (nxt.get("stocks") or [])}
print("3.14 涨停", nxt.get("count"), "最高", nxt.get("max_board"))
for s in yizis:
    n = by.get(s.get("name"))
    if not n:
        print(f"  {s.get('name')} 不在")
        continue
    ok, first, oc, to = yizi(n)
    print(
        f"  {n.get('name')} {n.get('boards')}板 {n.get('boards_desc')} "
        f"{'一字' if ok else '开/松'} 主题={n.get('theme')} 换手={to} 开板={oc} 首封={first}"
    )
