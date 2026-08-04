import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()

def find(d, name):
    for s in pools.get(d, []):
        if s["name"] == name:
            return s
    return None

print("=== 汇源 / 华远 路径 ===")
for d in days:
    a, b = find(d, "汇源通信"), find(d, "华远控股")
    if not a and not b:
        continue
    def fmt(s):
        if not s: return "-"
        return f"{s['boards']}板 yizi={bt.is_yizi(s)} theme={s.get('theme')!r} amt={bt.amount_yi(s)}"
    print(f"{d}  汇源:{fmt(a)}  |  华远:{fmt(b)}")

print("\n=== 汇源断相关节点 ===")
for i in range(1, len(days)):
    prev, cur = days[i-1], days[i]
    dead_ok, mx, dead, alive = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not dead_ok:
        continue
    names = [h["name"] for h in dead]
    if "汇源" in "".join(names) or any("汇源" in n for n in names):
        lad = bt.pick_ladder(pools[cur], cur)
        an = lad.get("anchor") or {}
        print(f"NODE {cur} 死绝层={[ (h['name'], h['boards']) for h in dead ]}")
        print(f"  pick: {lad.get('anchor_type')} h={lad.get('height')} anchor={an.get('name')}")
        print(f"  华远当日: {fmt(find(cur,'华远控股'))}")
        # 4板层
        layer4 = [s for s in pools[cur] if int(s.get("boards") or 0)==4]
        print(f"  当日4板层: {[(s['name'], bt.amount_yi(s), '一字' if bt.is_yizi(s) else '', s.get('theme')) for s in layer4]}")
