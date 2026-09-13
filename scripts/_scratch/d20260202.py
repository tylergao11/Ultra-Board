# -*- coding: utf-8 -*-
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
CN = timezone(timedelta(hours=8))
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


def sent(day):
    p = ROOT / day / "sentiment.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("info") or {}


for d in ("2026-01-30", "2026-02-02"):
    data = load(d)
    info = sent(d)
    print("=" * 8, d, "=" * 8)
    print(
        "涨停",
        data.get("count"),
        "最高",
        data.get("max_board"),
        "梯队",
        data.get("board_counts"),
        "情绪",
        info.get("sign"),
        "跌停",
        info.get("DT"),
        "实际上涨/下跌",
        info.get("SZJS"),
        info.get("XDJS"),
    )
    themes = Counter()
    for s in data.get("stocks") or []:
        themes[str(s.get("theme") or "?")] += 1
    print("主标签家数", themes.most_common(12))
    print("-- 2板及以上 --")
    rows = sorted(
        data.get("stocks") or [],
        key=lambda s: (-int(s.get("boards") or 0), ts(s.get("first_limit_ts"))),
    )
    for s in rows:
        if int(s.get("boards") or 0) < 2:
            continue
        raw = s.get("raw") or []
        oc = s.get("open_count")
        if oc is None and len(raw) > 16:
            oc = raw[16]
        tags = s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "")
        print(
            f"  {s.get('name')} {s.get('code')} {s.get('boards')}板 {s.get('boards_desc') or ''} "
            f"主题={s.get('theme')} 属性={tags} 换手={s.get('turnover_rate')} "
            f"首封={ts(s.get('first_limit_ts'))} 开板={oc} "
            f"开={s.get('open')} 收={s.get('price')}"
        )
    print()
