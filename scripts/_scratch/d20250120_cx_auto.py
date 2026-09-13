# -*- coding: utf-8 -*-
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(r"C:\Ai\Ultra-Board\data\kaipanla\raw")


def load(day):
    return json.loads((ROOT / day / "zt_pool.json").read_text(encoding="utf-8"))


def tags_of(s):
    raw = s.get("raw") or []
    return str(s.get("theme_tags_text") or (raw[12] if len(raw) > 12 else "") or "")


def blob(s):
    return str(s.get("theme") or "") + " " + tags_of(s)


from datetime import datetime, timezone, timedelta
CN = timezone(timedelta(hours=8))


def ts(v):
    if not v:
        return ""
    return datetime.fromtimestamp(int(v), CN).strftime("%H:%M")


for d in ("2025-01-16", "2025-01-17", "2025-01-20"):
    data = load(d)
    stocks = data.get("stocks") or []
    cx_theme = [s for s in stocks if str(s.get("theme") or "") in ("消费电子", "AI眼镜", "端侧AI")]
    cx_tag = [s for s in stocks if any(k in blob(s) for k in ("消费电子", "AI眼镜", "VR/AR", "端侧AI"))]
    car_theme = [s for s in stocks if "汽车" in str(s.get("theme") or "")]
    car_tag = [s for s in stocks if any(k in blob(s) for k in ("汽车", "汽车零部件", "新能源汽车"))]
    print("=" * 8, d, "涨停", data.get("count"), "=" * 8)
    print("主标签", Counter(str(s.get("theme") or "?") for s in stocks).most_common(10))
    print(f"消费电子相关主 {len(cx_theme)} 标签 {len(cx_tag)} | 汽车主 {len(car_theme)} 标签 {len(car_tag)}")
    print("-- 消费电子标签 --")
    for s in sorted(cx_tag, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        print(f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')}")
    print("-- 汽车标签 --")
    for s in sorted(car_tag, key=lambda x: (-int(x.get("boards") or 0), ts(x.get("first_limit_ts")))):
        print(f"  {s.get('name')} {s.get('boards')}板 主题={s.get('theme')} 属性={tags_of(s)} 换手={s.get('turnover_rate')}")
