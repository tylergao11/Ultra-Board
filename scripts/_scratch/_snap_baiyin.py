# -*- coding: utf-8 -*-
import json
from datetime import datetime
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw"


def yizi(s):
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


for d in [
    "2026-01-20",
    "2026-01-21",
    "2026-01-22",
    "2026-01-23",
    "2026-01-26",
    "2026-01-27",
    "2026-01-28",
    "2026-01-29",
]:
    p = RAW / d / "zt_pool.json"
    if not p.exists():
        print(d, "missing")
        continue
    zt = json.loads(p.read_text(encoding="utf-8-sig"))
    stocks = sorted(zt["stocks"], key=lambda s: (-s["boards"], s["code"]))
    print("====", d, "最高", zt.get("max_board"))
    for s in stocks:
        if s["boards"] < 2 and s["name"] not in ("盈方微", "白银有色", "湖南白银"):
            continue
        mark = ""
        if s["name"] in ("盈方微", "白银有色", "湖南白银"):
            mark = " <<<"
        print(
            f"  {s['boards']}板 {s['name']:8} theme={s.get('theme') or '-':10} "
            f"额={amt(s)}亿 {'一字' if yizi(s) else '':4}{mark}"
        )
