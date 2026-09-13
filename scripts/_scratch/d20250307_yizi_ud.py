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


def count_key(stocks, key):
    theme_n = sum(1 for s in stocks if key in str(s.get("theme") or ""))
    attr_n = sum(1 for s in stocks if key in blob(s))
    return theme_n, attr_n


prev = load("2025-03-06")
cur = load("2025-03-07")
ps, cs = prev.get("stocks") or [], cur.get("stocks") or []

print("3.6 涨停", prev.get("count"), "最高", prev.get("max_board"))
print("软件主标签", Counter(str(s.get("theme") or "?") for s in ps).most_common(8))
print("3.7 涨停", cur.get("count"), "最高", cur.get("max_board"))
print("软件主标签", Counter(str(s.get("theme") or "?") for s in cs).most_common(8))

print("\n-- 3.7 严口径一字 --")
yizis = []
for s in sorted(cs, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
    ok, first, oc, to = yizi(s)
    if ok:
        yizis.append(s)
        print(
            f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 {s.get('boards_desc')} "
            f"主题={s.get('theme')} 标签={tags_of(s)} 换手={to} 开板={oc}"
        )

print("\n-- 3.7 09:25开板0 换手不论 2板+ --")
for s in sorted(cs, key=lambda x: (-int(x.get("boards") or 0), float(s.get("turnover_rate") or 99))):
    first = ts(s.get("first_limit_ts"))
    oc = oc_of(s)
    to = float(s.get("turnover_rate") or 99)
    if int(s.get("boards") or 0) < 2:
        continue
    if first.startswith("09:25") and oc in (0, None, 0):
        print(f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 换手={to} 标签={tags_of(s)}")

print("\n-- 一字各自属性 3.6→3.7 --")
seen = set()
for s in yizis:
    theme = str(s.get("theme") or "")
    keys = []
    if theme:
        keys.append(theme.replace("概念", "") if False else theme)
    # 软件主标签用完整 theme；自身属性再拆标签
    attr_keys = [theme] if theme else []
    for part in [p.strip() for p in tags_of(s).replace("、", ",").replace("，", ",").split(",") if p.strip()]:
        if part not in attr_keys:
            attr_keys.append(part)
    # 只报软件主标签 + 标签里各属性的两套家数
    print(f"{s.get('name')} 软件主题={theme} 标签={tags_of(s)}")
    for k in attr_keys:
        if not k or k in seen and False:
            pass
        pt, pa = count_key(ps, k)
        ct, ca = count_key(cs, k)
        print(f"  [{k}] 软件主标签 {pt}→{ct}  自身属性 {pa}→{ca}")
    seen.add(theme)
