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


def bucket(s):
    theme = str(s.get("theme") or "")
    tags = tags_of(s)
    blob = theme + " " + tags
    keys = []
    if any(k in blob for k in ("化工", "石化", "煤化工", "磷化工")):
        keys.append("化工")
    if any(k in blob for k in ("石油", "油气", "原油")):
        keys.append("石油")
    if any(k in blob for k in ("算力", "人工智能", "AI", "通信", "芯片", "光纤", "光模块", "CPO")):
        keys.append("科技")
    return theme, tags, keys


for d in ("2026-02-13", "2026-02-24"):
    data = load(d)
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), data.get("board_counts"), "=" * 8)
    themes = Counter(str(s.get("theme") or "?") for s in data.get("stocks") or [])
    print("主标签", themes.most_common(15))
    chem, oil, tech = [], [], []
    for s in data.get("stocks") or []:
        theme, tags, keys = bucket(s)
        row = s
        if "化工" in keys:
            chem.append(row)
        if "石油" in keys:
            oil.append(row)
        if "科技" in keys:
            tech.append(row)
    print("化工", len(chem), "石油", len(oil), "科技向", len(tech))

    def show(title, xs, min_b=1):
        xs = sorted(xs, key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))))
        print("--", title, "--")
        for s in xs:
            if int(s.get("boards") or 0) < min_b:
                continue
            raw = s.get("raw") or []
            oc = s.get("open_count")
            if oc is None and len(raw) > 16:
                oc = raw[16]
            print(
                f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
                f"主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')} "
                f"首封={ts(s.get('first_limit_ts'))} 开板={oc}"
            )

    print("-- 2板及以上全场 --")
    rows = sorted(
        data.get("stocks") or [],
        key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))),
    )
    for s in rows:
        if int(s.get("boards") or 0) < 2:
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
            f"主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')} "
            f"首封={ts(s.get('first_limit_ts'))}"
        )
    show("化工2板+", chem, 2)
    show("石油2板+", oil, 2)
    show("科技向全部", tech, 1)
    print()
