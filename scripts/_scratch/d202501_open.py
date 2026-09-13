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
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


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
    return first.startswith("09:25") and to <= 6.5 and oc in (0, None, 0), first, oc, to


def show(s):
    is_yz, first, oc, to = yizi(s)
    print(
        f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
        f"{'一字' if is_yz else ''} 主题={s.get('theme')} 属性={tags_of(s)} "
        f"换手={to} 首封={first} 开板={oc} "
        f"开={s.get('open')} 低={s.get('low')} 开幅={s.get('open_pct')}"
    )


for d in ("2025-01-02", "2025-01-03"):
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    stocks = data.get("stocks") or []
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(10))
    print("-- 2板+ --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        show(s)
    print("-- 一字 --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if yizi(s)[0]:
            show(s)
