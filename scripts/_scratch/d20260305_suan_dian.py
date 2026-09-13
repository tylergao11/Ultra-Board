# -*- coding: utf-8 -*-
import json
import sys
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


def hit(s):
    blob = str(s.get("theme") or "") + " " + tags_of(s) + " " + str(s.get("name") or "")
    keys = []
    if any(k in blob for k in ("算力", "人工智能", "AI", "东数西算")):
        keys.append("算")
    if any(k in blob for k in ("电力", "电网", "变压器", "绿电", "充电", "储能")):
        keys.append("电")
    return keys


for d in ("2026-03-04", "2026-03-05", "2026-03-06"):
    data = load(d)
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), "=" * 8)
    rows = []
    for s in data.get("stocks") or []:
        ks = hit(s)
        if not ks:
            continue
        rows.append((s, ks))
    rows.sort(key=lambda x: (-int(x[0].get("boards") or 0), ts(x[0].get("first_limit_ts"))))
    for s, ks in rows:
        both = "算电" if ("算" in ks and "电" in ks) else "".join(ks)
        print(
            f"  [{both}] {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={s.get('turnover_rate')} "
            f"首封={ts(s.get('first_limit_ts'))} 开板={oc_of(s)}"
        )
    print()
