import importlib.util
from collections import defaultdict

spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)
spec2 = importlib.util.spec_from_file_location("cmp", "scripts/_scratch/compare_anchor_strategies.py")
cmp = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(cmp)

days, pools, pools_m = bt.load_days()
KNOWN = cmp.KNOWN
hit = hit_a = strict = sole = sn = known_ok = 0
n = 0
by_type = defaultdict(int)
for i in range(1, len(days)):
    prev, cur = days[i - 1], days[i]
    ok, dh, dead, _ = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not ok:
        continue
    n += 1
    lad = bt.pick_ladder(pools[cur], cur)
    mem = lad.get("members") or set()
    fut = cmp.future_nat_codes(days, pools, i + 1, 10) if i + 1 < len(days) else set()
    sn += len(mem)
    if mem & fut:
        hit += 1
    an = lad.get("anchor") or {}
    if an.get("code") in fut:
        hit_a += 1
    if (mem & fut) and len(mem) <= 3:
        strict += 1
    if (mem & fut) and len(mem) == 1:
        sole += 1
    if cur in KNOWN and KNOWN[cur][0] in mem:
        known_ok += 1
    by_type[lad.get("anchor_type") or "?"] += 1

print("YOUR ORIGINAL = pick_ladder (down)")
print("nodes", n)
print("layer_hit", hit, n, f"{hit/n:.1%}")
print("anchor_hit", hit_a, n, f"{hit_a/n:.1%}")
print("avg_n", round(sn / n, 2))
print("strict", strict, f"{strict/n:.1%}")
print("sole_win", sole, f"{sole/n:.1%}")
print("known4", known_ok, "/4")
print("by_type", dict(by_type))
