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


GROUPS = {
    "算力": ("算力",),
    "农业食品": ("农业", "乳业", "食品饮料"),
}

for d in ("2025-02-21", "2025-02-24", "2025-02-25"):
    data = load(d)
    stocks = data.get("stocks") or []
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(10))
    for name, keys in GROUPS.items():
        theme_n = sum(1 for s in stocks if any(k in str(s.get("theme") or "") for k in keys))
        tag_n = sum(1 for s in stocks if any(k in blob(s) for k in keys))
        print(f"  {name}: 主标签 {theme_n}  主题或标签 {tag_n}")
        rows = [s for s in stocks if any(k in blob(s) for k in keys)]
        rows = sorted(rows, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts"))))
        for s in rows:
            if int(s.get("boards") or 0) < 2 and name == "算力":
                continue
            ok, first, oc, to = yizi(s)
            mark = "一字" if ok else ""
            print(
                f"    {s.get('name')} {s.get('boards')}板 {mark} "
                f"主题={s.get('theme')} 换手={to} 开板={oc} 首封={first}"
            )
        if name == "农业食品":
            for s in rows:
                ok, first, oc, to = yizi(s)
                if int(s.get("boards") or 0) < 2:
                    print(
                        f"    {s.get('name')} {s.get('boards')}板 "
                        f"主题={s.get('theme')} 换手={to} 首封={first}"
                    )
