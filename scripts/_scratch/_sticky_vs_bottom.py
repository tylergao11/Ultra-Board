# -*- coding: utf-8 -*-
"""验证：今日自然最高粘性 vs 往下锚从底抓全程"""
import importlib.util
from collections import defaultdict
from pathlib import Path

spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()

def nat_max_set(d):
    mx, highs = bt.natural_max(pools[d], d)
    return mx, {s["code"] for s in highs}, {s["code"]: s for s in highs}

# --- 1) 全样本：今日在自然最高 → 明日是否仍在自然最高 / 是否晋级仍最高 ---
stay = 0
promo_stay = 0  # 晋级且仍是自然最高一员
still_in_pool = 0
n_pairs = 0
sole_stay = 0
sole_n = 0

# 非最高的2板 → 后面成自然最高？
from_two = 0
from_two_hit = 0

for i in range(len(days) - 1):
    d, nd = days[i], days[i + 1]
    mx, codes, mp = nat_max_set(d)
    if mx <= 0 or not codes:
        continue
    nmx, ncodes, _ = nat_max_set(nd)
    n_pairs += 1
    inter = codes & ncodes
    if inter:
        stay += 1
    # any of today's max still in pool tomorrow
    if any(c in pools_m[nd] for c in codes):
        still_in_pool += 1
    # sole
    if len(codes) == 1:
        sole_n += 1
        c = next(iter(codes))
        if c in ncodes:
            sole_stay += 1
        s = mp[c]
        # 晋级
        t = pools_m[nd].get(c)
        if t and int(t.get("boards") or 0) == int(s.get("boards") or 0) + 1 and c in ncodes:
            promo_stay += 1  # count among all? only sole path below
    # 2板自然 not at max? if max is 2, skip. if max>2, 2板 later become max
    if mx > 2:
        twos = [s for s in pools[d] if int(s.get("boards") or 0) == 2 and bt.is_natural(s, d)]
        for s in twos:
            from_two += 1
            code = s["code"]
            # within 10 days become natural max member
            ok = False
            for j in range(i + 1, min(i + 11, len(days))):
                _, mc, _ = nat_max_set(days[j])
                if code in mc:
                    ok = True
                    break
            if ok:
                from_two_hit += 1

# sole promo_stay recount properly
sole_promo_and_max = 0
for i in range(len(days) - 1):
    d, nd = days[i], days[i + 1]
    mx, codes, mp = nat_max_set(d)
    if len(codes) != 1:
        continue
    c = next(iter(codes))
    s = mp[c]
    t = pools_m[nd].get(c)
    _, ncodes, _ = nat_max_set(nd)
    if t and int(t.get("boards") or 0) == int(s.get("boards") or 0) + 1 and c in ncodes:
        sole_promo_and_max += 1

# --- 2) 节点日专项 ---
node_stay = node_n = 0
node_sole_stay = node_sole = 0
node_down_early = 0  # 往下锚层成员在节点日 boards < today_nat_h
node_down_later_max = 0  # 且10日内成自然最高
node_nat_later = 0
node_both = 0
node_only_down = 0
node_only_nat = 0

for i in range(1, len(days)):
    prev, cur = days[i - 1], days[i]
    dead_ok, dead_h, dead, _ = bt.is_high_tier_dead(
        pools[prev], set(pools_m[cur].keys()), prev
    )
    if not dead_ok:
        continue
    mx, codes, mp = nat_max_set(cur)
    lad = bt.pick_ladder(pools[cur], cur)
    down = lad.get("members") or set()
    # next day stickiness on node
    if i + 1 < len(days):
        _, ncodes, _ = nat_max_set(days[i + 1])
        node_n += 1
        if codes & ncodes:
            node_stay += 1
        if len(codes) == 1:
            node_sole += 1
            if next(iter(codes)) in ncodes:
                node_sole_stay += 1

    # 10d future max set
    fut = set()
    for j in range(i + 1, min(i + 11, len(days))):
        _, mc, _ = nat_max_set(days[j])
        fut |= mc

    nat_hit = bool(codes & fut)
    down_hit = bool(down & fut)
    if nat_hit:
        node_nat_later += 1
    if down_hit:
        node_down_later_max += 1
    if nat_hit and down_hit:
        node_both += 1
    if down_hit and not nat_hit:
        node_only_down += 1
    if nat_hit and not down_hit:
        node_only_nat += 1

    # 从底：往下锚里 boards < mx 的票，后来成最高
    early = []
    for s in pools[cur]:
        if s["code"] in down and int(s.get("boards") or 0) < mx and bt.is_natural(s, cur):
            early.append(s["code"])
    if early:
        node_down_early += 1
        if set(early) & fut:
            # already counted in only_down-ish
            pass

# 节点日：往下独有命中里，锚点高度分布
only_down_cases = []
for i in range(1, len(days)):
    prev, cur = days[i - 1], days[i]
    dead_ok, _, _, _ = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not dead_ok:
        continue
    mx, codes, _ = nat_max_set(cur)
    lad = bt.pick_ladder(pools[cur], cur)
    down = lad.get("members") or set()
    fut = set()
    names_fut = {}
    for j in range(i + 1, min(i + 11, len(days))):
        _, highs = bt.natural_max(pools[days[j]], days[j])
        for h in highs:
            fut.add(h["code"])
            names_fut[h["code"]] = h["name"]
    if (down & fut) and not (codes & fut):
        # who
        winners = down & fut
        # their boards on node day
        bs = []
        for s in pools[cur]:
            if s["code"] in winners:
                bs.append((s["name"], s["boards"], bt.amount_yi(s)))
        only_down_cases.append((cur, lad.get("height"), lad.get("anchor_type"), bs))

print("=" * 60)
print("1) 粘性：今日自然最高 → 明日仍是自然最高成员")
print(f"   全交易日对: {stay}/{n_pairs} = {stay/n_pairs:.1%}")
print(f"   独苗自然最高 → 明日仍最高: {sole_stay}/{sole_n} = {sole_stay/sole_n:.1%}")
print(f"   独苗且次日晋级并仍最高: {sole_promo_and_max}/{sole_n} = {sole_promo_and_max/sole_n:.1%}")
print(f"   节点日 今日最高→明日仍最高: {node_stay}/{node_n} = {node_stay/node_n:.1%}")
print(f"   节点日 独苗→明日仍最高: {node_sole_stay}/{node_sole} = {node_sole_stay/node_sole:.1%}")

print()
print("2) 2板自然（当时不是最高）→ 10日内成为自然最高成员")
print(f"   {from_two_hit}/{from_two} = {from_two_hit/from_two:.1%}  (样本=非最高日的每个2板自然票·日)")

print()
print("3) 节点日：两条路径 10日命中")
nn = node_n
print(f"   节点数 {nn}")
print(f"   今日自然最高层 hit: {node_nat_later}/{nn} = {node_nat_later/nn:.1%}")
print(f"   往下锚层 hit:       {node_down_later_max}/{nn} = {node_down_later_max/nn:.1%}")
print(f"   两边都中: {node_both}  仅最高: {node_only_nat}  仅往下: {node_only_down}")

print()
print("4) 仅往下能抓到、最高层抓不到的案例（底部/换帅）数=", len(only_down_cases))
for c in only_down_cases[:12]:
    print(f"   {c[0]} down_h={c[1]} {c[2]} winners_on_node={c[3]}")
if len(only_down_cases) > 12:
    print(f"   ... +{len(only_down_cases)-12}")

# 节点日：今日最高成员 在节点日的板高 vs 后来最高
print()
print("5) 语义")
print("   今日最高粘性高 = 更容易「接着做」而不是「从零挖」")
print("   往下锚仅有命中 = 换帅/中军从低位起来，原方法价值在这")
