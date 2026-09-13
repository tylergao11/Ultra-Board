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


def kind(s):
    theme = str(s.get("theme") or "")
    tags = tags_of(s)
    blob = theme + " " + tags
    out = []
    if any(k in blob for k in ("石油", "石化", "油气", "原油")):
        out.append("石油")
    if "化工" in blob:
        out.append("化工")
    if any(k in blob for k in ("有色", "钨", "锡", "锑", "铜", "铝", "锌", "稀土")):
        out.append("有色")
    if "黄金" in blob:
        out.append("黄金")
    return out


def yizi(s):
    first = ts(s.get("first_limit_ts"))
    raw = s.get("raw") or []
    oc = s.get("open_count")
    if oc is None and len(raw) > 16:
        oc = raw[16]
    to = float(s.get("turnover_rate") or 99)
    open_p = s.get("open")
    price = s.get("price")
    return first.startswith("09:25") and to <= 6.5 and (oc in (0, None, "0") or oc == 0), first, oc, to, open_p, price


for d in ("2026-02-27", "2026-03-02"):
    data = load(d)
    print("=" * 8, d, "=" * 8)
    rows = []
    for s in data.get("stocks") or []:
        ks = kind(s)
        if not ks:
            continue
        is_yz, first, oc, to, open_p, price = yizi(s)
        rows.append((s, ks, is_yz, first, oc, to, open_p, price))
    rows.sort(key=lambda x: (-int(x[0].get("boards") or 0), x[3]))
    print("石油/化工/有色/黄金", len(rows))
    print("-- 一字候选 --")
    for s, ks, is_yz, first, oc, to, open_p, price in rows:
        if not is_yz:
            continue
        print(
            f"  一字 {s.get('name')} {s.get('boards')}板 类={ks} 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={to} 首封={first} 开板={oc} 开={open_p} 收={price}"
        )
    print("-- 2板+ --")
    for s, ks, is_yz, first, oc, to, open_p, price in rows:
        if int(s.get("boards") or 0) < 2:
            continue
        mark = "一字" if is_yz else ""
        print(
            f"  {s.get('name')} {s.get('boards')}板 {mark} 类={ks} 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={to} 首封={first} 开板={oc}"
        )
    print("-- 09:25 首封但换手/开板不像一字 --")
    for s, ks, is_yz, first, oc, to, open_p, price in rows:
        if is_yz or not first.startswith("09:25"):
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 类={ks} 主题={s.get('theme')} "
            f"换手={to} 开板={oc} 开={open_p} 收={price} 属性={tags_of(s)}"
        )
    print()
