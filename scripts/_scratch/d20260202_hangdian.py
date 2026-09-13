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


def comm(s):
    theme = str(s.get("theme") or "")
    tags = tags_of(s)
    blob = theme + " " + tags
    main = theme == "通信" or "通信" in theme
    attr = any(k in blob for k in ("通信", "光纤", "光缆", "光模块"))
    return main, attr, theme, tags


for d in ("2026-01-29", "2026-01-30", "2026-02-02", "2026-02-03"):
    p = ROOT / d / "zt_pool.json"
    if not p.exists():
        print(d, "NO FILE")
        continue
    data = load(d)
    print("=" * 8, d, "全场", data.get("count"), "最高", data.get("max_board"), "=" * 8)
    main_s, attr_s = [], []
    for s in data.get("stocks") or []:
        main, attr, theme, tags = comm(s)
        if main:
            main_s.append(s)
        if attr:
            attr_s.append(s)
    print("通信主", len(main_s), "属性含通信/光纤", len(attr_s))
    seen = set()
    rows = []
    for s in main_s + attr_s:
        code = str(s.get("code")).zfill(6)
        if code in seen:
            continue
        seen.add(code)
        rows.append(s)
    rows.sort(key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))))
    for s in rows:
        raw = s.get("raw") or []
        oc = s.get("open_count")
        if oc is None and len(raw) > 16:
            oc = raw[16]
        print(
            f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
            f"主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')} "
            f"首封={ts(s.get('first_limit_ts'))} 开板={oc}"
        )
    print()
