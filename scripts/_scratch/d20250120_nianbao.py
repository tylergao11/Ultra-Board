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


for d in ("2025-01-16", "2025-01-17", "2025-01-20"):
    data = load(d)
    stocks = data.get("stocks") or []
    nb_theme = [s for s in stocks if str(s.get("theme") or "") == "年报增长"]
    nb_tag = [s for s in stocks if "年报" in blob(s)]
    rb = [s for s in stocks if "机器人" in blob(s)]
    print("=" * 8, d, "涨停", data.get("count"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(8))
    print(f"年报主 {len(nb_theme)} 年报标签 {len(nb_tag)} | 机器人标签 {len(rb)}")
    print("-- 年报主标签 --")
    for s in sorted(nb_theme, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        print(
            f"  {s.get('name')} {s.get('boards')}板 属性={tags_of(s)} "
            f"换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))}"
        )
    print("-- 机器人 2板+ --")
    for s in sorted(rb, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        print(
            f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 属性={tags_of(s)} "
            f"换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))}"
        )
