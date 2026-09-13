# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")
WANT = ("湖北广电", "国脉科技", "南兴股份", "佳都科技")


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


for d in ("2025-03-06", "2025-03-07", "2025-03-10", "2025-03-11", "2025-03-12"):
    data = load(d)
    if not data:
        continue
    print("=" * 6, d, "涨停", data.get("count"), "最高", data.get("max_board"), "=" * 6)
    by = {s.get("name"): s for s in (data.get("stocks") or [])}
    for name in WANT:
        s = by.get(name)
        if not s:
            print(f"  {name} 不在")
            continue
        ok, first, oc, to = yizi(s)
        print(
            f"  {name} {s.get('boards')}板 {s.get('boards_desc')} "
            f"{'一字' if ok else '开/松'} 主题={s.get('theme')} "
            f"换手={to} 开板={oc} 首封={first} 标签={tags_of(s)}"
        )
