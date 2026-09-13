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


for d in ("2025-01-17", "2025-01-20"):
    data = load(d)
    stocks = data.get("stocks") or []
    print("=" * 8, d, "涨停", data.get("count"), "最高", data.get("max_board"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(12))
    dw_theme = [s for s in stocks if str(s.get("theme") or "") in ("智能电网", "电力", "电气设备")]
    dw_tag = [s for s in stocks if any(k in blob(s) for k in ("智能电网", "电气设备", "绿色电力"))]
    tx_theme = [s for s in stocks if str(s.get("theme") or "") == "通信"]
    tx_tag = [s for s in stocks if "通信" in blob(s) or "光纤" in blob(s)]
    print(f"电网/电力主 {len(dw_theme)} 标签 {len(dw_tag)} | 通信主 {len(tx_theme)} 标签 {len(tx_tag)}")
    print("-- 电网标签 --")
    for s in sorted(dw_tag, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        print(f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))}")
    print("-- 通信标签 2板+ --")
    for s in sorted(tx_tag, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        if int(s.get("boards") or 0) < 2:
            continue
        print(f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')} 首封={ts(s.get('first_limit_ts'))}")
