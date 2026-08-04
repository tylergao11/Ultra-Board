import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()

for d in ["2025-12-22","2025-12-23","2025-12-24","2025-12-25"]:
    print("="*60, d)
    mx, highs = bt.natural_max(pools[d], d)
    print("natural_max", mx, [(h["name"], h["boards"], bt.amount_yi(h), bt.is_yizi(h)) for h in highs])
    # all >=4
    for s in sorted(pools[d], key=lambda x: -int(x.get("boards") or 0)):
        b=int(s.get("boards") or 0)
        if b < 3: continue
        print(f"  {s['name']} {b} nat={bt.is_natural(s,d)} gg={bt.is_gonggao(s,d)} yizi={bt.is_yizi(s)} theme={s.get('theme')!r} amt={bt.amount_yi(s)}")

# dead check 12-23 -> 12-24
prev, cur = "2025-12-23", "2025-12-24"
dead_ok, dead_h, dead, alive = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
print("\n=== is_high_tier_dead 23->24 ===")
print("dead_ok", dead_ok, "dead_h", dead_h)
print("dead", [(h["name"], h["boards"]) for h in dead])
print("alive", [(h["name"], h["boards"]) for h in alive])
# is 鹭燕 in 24 pool at all?
for s in pools[cur]:
    if "鹭燕" in s["name"] or "神剑" in s["name"] or "庄园" in s["name"]:
        print("24 pool", s["name"], s["boards"], s.get("theme"))

# also check if 12-24 is in node list
print("\n12-24 in picks nodes?")
# any node on 24
print("dead_ok means should be NODE" if dead_ok else "NOT node by rule")
if dead_ok:
    lad = bt.pick_ladder(pools[cur], cur)
    an = lad.get("anchor") or {}
    mx, highs = bt.natural_max(pools[cur], cur)
    print("pick", lad.get("anchor_type"), lad.get("height"), an.get("name"))
    print("nat high", mx, [h["name"] for h in highs])
