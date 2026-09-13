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


def oc_of(s):
    oc = s.get("open_count")
    raw = s.get("raw") or []
    if oc is None and len(raw) > 16:
        oc = raw[16]
    return oc


def tags_of(s):
    raw = s.get("raw") or []
    return str(s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "") or "")


def yizi(s):
    first = ts(s.get("first_limit_ts"))
    oc = oc_of(s)
    to = float(s.get("turnover_rate") or 99)
    ok = first.startswith("09:25") and to <= 6.5 and oc in (0, None, 0)
    return ok, first, oc, to


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


for d in ("2025-03-03", "2025-03-04", "2025-03-05"):
    data = load(d)
    stocks = data.get("stocks") or []
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(12))
    print("-- 严口径一字 --")
    n = 0
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        ok, first, oc, to = yizi(s)
        if not ok:
            continue
        n += 1
        print(
            f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 "
            f"主题={s.get('theme')} 标签={tags_of(s)[:40]} "
            f"换手={to} 开板={oc} 首封={first}"
        )
    if n == 0:
        print("  无")
    print("-- 09:25开板0 换手不论 2板+ --")
    for s in sorted(stocks, key=lambda x: (-int(x.get("boards") or 0), float(s.get("turnover_rate") or 99))):
        first = ts(s.get("first_limit_ts"))
        oc = oc_of(s)
        to = float(s.get("turnover_rate") or 99)
        if int(s.get("boards") or 0) < 2:
            continue
        if first.startswith("09:25") and oc in (0, None, 0):
            flag = "严一字" if to <= 6.5 else f"换手{to}"
            print(
                f"  {s.get('name')} {s.get('boards')}板 {flag} "
                f"主题={s.get('theme')} 换手={to}"
            )
