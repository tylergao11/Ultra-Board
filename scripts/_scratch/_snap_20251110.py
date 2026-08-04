# -*- coding: utf-8 -*-
import importlib.util
import json
from datetime import datetime
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, m = bt.load_days()
RAW = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw"

for d in ("2025-11-07", "2025-11-10", "2025-11-11"):
    if d not in pools:
        print(d, "missing")
        continue
    stocks = sorted(pools[d], key=lambda s: (-s["boards"], s["code"]))
    mx, highs = bt.natural_max(stocks, d)
    print("====", d, "自然高标", mx, [h["name"] for h in highs])
    for s in stocks:
        if s["boards"] < 2:
            continue
        tags = []
        if bt.is_yizi(s):
            tags.append("一字")
        if bt.is_gonggao(s, d):
            tags.append("公告")
        else:
            tags.append("自然")
        raw = s.get("raw") or []
        r17 = raw[17] if len(raw) > 17 else None
        ts = s.get("first_limit_ts")
        hm = ""
        if ts:
            try:
                t = datetime.fromtimestamp(int(ts))
                hm = t.strftime("%H:%M:%S")
            except Exception:
                pass
        print(
            f"  {s['boards']}板 {s['name']:8} 额={bt.amount_yi(s)} "
            f"th={s.get('theme')} {'/'.join(tags)} 封={hm} r17={r17} "
            f"OHLC={s.get('open')}/{s.get('high')}/{s.get('low')}/{s.get('price')}"
        )
    lad = bt.pick_ladder(pools[d], d)
    print(
        "  >> pick",
        lad["anchor_type"],
        lad["anchor"]["name"] if lad["anchor"] else None,
        "h=",
        lad["height"],
    )
    print()
