import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt
days, pools, pools_m = bt.load_days()

# 12-23 24 detail: 鹭燕 vs 神剑
for d in ["2025-12-22","2025-12-23","2025-12-24","2025-12-25","2025-12-26","2025-12-29"]:
    mx, highs = bt.natural_max(pools[d], d)
    print(d, "nat", mx, [(h["name"], h["boards"], bt.amount_yi(h)) for h in highs])
    for name in ["神剑股份","鹭燕医药","庄园牧场","锋龙股份","大业股份"]:
        for s in pools[d]:
            if s["name"]==name:
                print(f"  {name} {s['boards']} yizi={bt.is_yizi(s)} amt={bt.amount_yi(s)}")
