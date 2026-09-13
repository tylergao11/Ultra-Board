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


def side(s):
    blob = str(s.get("theme") or "") + " " + tags_of(s)
    suan = any(k in blob for k in ("算力",))
    dian = any(k in blob for k in ("电力", "智能电网", "变压器", "绿色电力"))
    if suan and dian:
        return "算电"
    if suan:
        return "算"
    if dian:
        return "电"
    return None


data = load("2026-03-05")
print("3.5 只留算力/电力")
rows = []
for s in data.get("stocks") or []:
    k = side(s)
    if not k:
        continue
    rows.append((s, k))
rows.sort(key=lambda x: (-int(x[0].get("boards") or 0), ts(x[0].get("first_limit_ts"))))
for s, k in rows:
    first = ts(s.get("first_limit_ts"))
    oc = oc_of(s)
    to = float(s.get("turnover_rate") or 99)
    yz = first.startswith("09:25") and to <= 6.5 and oc in (0, None, 0)
    print(
        f"  [{k}] {s.get('name')} {s.get('boards')}板 {'一字' if yz else ''} "
        f"主题={s.get('theme')} 属性={tags_of(s)} 换手={to} 首封={first} 开板={oc}"
    )
