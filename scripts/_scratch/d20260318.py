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


def tech(s):
    blob = str(s.get("theme") or "") + " " + tags_of(s)
    return any(
        k in blob
        for k in ("算力", "人工智能", "AI", "通信", "芯片", "光模块", "CPO", "消费电子")
    )


def dian(s):
    blob = str(s.get("theme") or "") + " " + tags_of(s)
    return any(k in blob for k in ("电力", "风电", "电网", "绿色电力", "光伏"))


for d in ("2026-03-17", "2026-03-18"):
    data = load(d)
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in data.get("stocks") or []).most_common(12))
    print("-- 一字 --")
    rows = sorted(
        data.get("stocks") or [],
        key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))),
    )
    for s in rows:
        is_yz, first, oc, to = yizi(s)
        if not is_yz:
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={to} 首封={first}"
        )
    print("-- 2板+ --")
    for s in rows:
        if int(s.get("boards") or 0) < 2:
            continue
        is_yz, first, oc, to = yizi(s)
        print(
            f"  {s.get('name')} {s.get('boards')}板 {'一字' if is_yz else ''} "
            f"主题={s.get('theme')} 属性={tags_of(s)} 换手={to} 首封={first} 开板={oc}"
        )
    tech_s = [s for s in data.get("stocks") or [] if tech(s)]
    dian_s = [s for s in data.get("stocks") or [] if dian(s)]
    print("科技向", len(tech_s), "电/风电/电网向", len(dian_s))
    print("-- 科技向2板+ --")
    for s in sorted(tech_s, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))}"
        )
    print("-- 电/风电 --")
    for s in sorted(dian_s, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        print(
            f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} "
            f"属性={tags_of(s)} 换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))} 开板={oc_of(s)}"
        )
    print()
