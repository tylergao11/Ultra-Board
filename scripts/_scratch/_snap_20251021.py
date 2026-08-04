# -*- coding: utf-8 -*-
import json
from pathlib import Path

import importlib.util

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

RAW = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw"

for d in ("2025-10-20", "2025-10-21", "2025-10-22"):
    zt = json.loads((RAW / d / "zt_pool.json").read_text(encoding="utf-8-sig"))
    stocks = sorted(zt["stocks"], key=lambda s: (-s["boards"], s["code"]))
    mx, highs = bt.natural_max(stocks)
    print("====", d, "自然高标", mx, [h["name"] for h in highs])
    for s in stocks:
        if s["boards"] < 2:
            continue
        tags = []
        if bt.is_yizi(s):
            tags.append("一字")
        if bt.is_gonggao(s):
            tags.append("公告")
        else:
            tags.append("自然")
        a = bt.amount_yi(s)
        print(
            f"  {s['boards']}板 {s['name']:8} 额={a} {'/'.join(tags)} "
            f"th={s.get('theme')} co={(s.get('concepts') or '')[:28]}"
        )
    print()

# 10-20 自然高标所在层
prev = json.loads((RAW / "2025-10-20" / "zt_pool.json").read_text(encoding="utf-8-sig"))[
    "stocks"
]
mx, highs = bt.natural_max(prev)
h = mx
layer = [s for s in prev if int(s["boards"]) == h]
print("10-20 自然最高板高", h, "整层:")
for s in layer:
    print(
        " ",
        s["name"],
        s["boards"],
        "公告" if bt.is_gonggao(s) else "自然",
        bt.amount_yi(s),
    )
cur_codes = {
    s["code"]
    for s in json.loads((RAW / "2025-10-21" / "zt_pool.json").read_text(encoding="utf-8-sig"))[
        "stocks"
    ]
}
print("层内今日仍在池:", [s["name"] for s in layer if s["code"] in cur_codes])
print("层内今日不在池:", [s["name"] for s in layer if s["code"] not in cur_codes])
