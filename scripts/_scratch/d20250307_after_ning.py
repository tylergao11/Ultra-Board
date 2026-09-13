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


days = sorted(
    p.name
    for p in ROOT.iterdir()
    if p.is_dir() and p.name >= "2025-03-04" and p.name <= "2025-03-12"
)
print("days", days)
for d in days:
    data = load(d)
    if not data:
        continue
    hit = next((s for s in (data.get("stocks") or []) if s.get("name") == "宁水集团"), None)
    if hit:
        ok, first, oc, to = yizi(hit)
        print(
            f"{d} 宁水 {hit.get('boards')}板 {hit.get('boards_desc')} "
            f"{'一字' if ok else ''} 主题={hit.get('theme')} 换手={to} 开板={oc} 首封={first}"
        )
    else:
        print(f"{d} 宁水 不在  涨停{data.get('count')} 最高{data.get('max_board')}")
