# -*- coding: utf-8 -*-
import json
from datetime import datetime
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw"
KEYS = ("并购重组", "股权转让", "实控人变更", "实控人", "并购", "重组", "举牌")


def is_gonggao(s):
    t = (s.get("theme") or "").strip()
    return any(k in t for k in KEYS)


def is_yizi(s):
    raw = s.get("raw") or []
    try:
        o, h, low, c = s.get("open"), s.get("high"), s.get("low"), s.get("price")
        if None not in (o, h, low, c):
            o, h, low, c = float(o), float(h), float(low), float(c)
            if abs(o - c) < 0.02 and abs(h - c) < 0.02 and abs(low - c) < 0.02:
                return True
    except Exception:
        pass
    try:
        t = datetime.fromtimestamp(int(s["first_limit_ts"]))
        amp = float(raw[17] or 0) if len(raw) > 17 else 99
        return t.hour == 9 and t.minute == 25 and amp <= 0.01
    except Exception:
        return False


def amt(s):
    raw = s.get("raw") or []
    return round(raw[11] / 1e8, 2) if len(raw) > 11 else None


for d in ("2025-10-15", "2025-10-16", "2025-10-17"):
    zt = json.loads((RAW / d / "zt_pool.json").read_text(encoding="utf-8-sig"))
    stocks = sorted(zt["stocks"], key=lambda s: (-s["boards"], s["code"]))
    print("====", d, "max", zt.get("max_board"), "n", zt.get("count"))
    for s in stocks:
        if int(s["boards"]) < 2:
            continue
        tags = []
        if is_yizi(s):
            tags.append("一字")
        if is_gonggao(s):
            tags.append("公告")
        else:
            tags.append("自然")
        print(
            f"  {s['boards']}板 {s['name']:8} th={s.get('theme') or '-':12} "
            f"co={(s.get('concepts') or '')[:30]:30} 额={amt(s)} {'/'.join(tags)}"
        )
    print()
