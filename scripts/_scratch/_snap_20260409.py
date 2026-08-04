# -*- coding: utf-8 -*-
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, m = bt.load_days()

for d in ("2026-04-08", "2026-04-09", "2026-04-10"):
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
        print(
            f"  {s['boards']}板 {s['name']:8} 额={bt.amount_yi(s)} "
            f"th={s.get('theme')} co={(s.get('concepts') or '')[:32]} "
            f"{'/'.join(tags)}"
        )
    dead_ok, h, dead, alive = bt.is_high_tier_dead(
        pools.get("2026-04-08", []), set(m.get(d, {}).keys()), "2026-04-08"
    )
    if d == "2026-04-09":
        print(
            "  dead_check from 04-08:",
            dead_ok,
            "h=",
            h,
            "dead=",
            [x["name"] for x in dead],
            "alive=",
            [x["name"] for x in alive],
        )
        lad = bt.pick_ladder(pools[d], d)
        print("  pick", lad["detail"], [x["name"] for x in lad["tier"]])
    print()
