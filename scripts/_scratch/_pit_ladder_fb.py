import sys
from collections import Counter, defaultdict
sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import build_rows
from reverse_zhaban_top_open import keep_top_open_per_group
import importlib.util
spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()
raw = build_rows(days, pools, pools_m)
# need extra fields: anchor relationship - rebuild from pick
# build_rows already has dead_h, down_h

kept, _ = keep_top_open_per_group(raw)
# drop pit1
remain = [r for r in kept if not (r["fb"] >= 3 and r["open_pct_T1"] < 0)]

# enrich: is_anchor_height (boards==down_h), rel to dead
for r in remain:
    dh = r.get("down_h") or 0
    H = r.get("dead_h") or 0
    b = r["boards_T"]
    r["at_anchor_h"] = (b == dh)
    r["rel_dead"] = b - H  # negative = lower than broken high
    r["rel_dead_lab"] = (
        "同高0" if b == H else
        "H-1" if b == H - 1 else
        "深切<=H-2" if b <= H - 2 else
        "高于断"
    )
    # ladder role
    if b == dh:
        r["ladder_role"] = "锚高层(判定高度)"
    elif b > dh:
        r["ladder_role"] = "高于往下锚?"  # shouldn't happen often
    else:
        r["ladder_role"] = "锚层内但非? wait boards is the tier"
    # actually whole set is same down tier - all have boards in the tier members which are ALL at height down_h
    # Wait - pick_ladder members are ALL stocks at the chosen height. So boards_T should equal down_h for all!
    
touch = [r for r in remain if r["touched"]]
zha = [r for r in touch if r["zhaban"]]

print("检查: boards vs down_h 是否总相等")
eq = sum(1 for r in remain if r["boards_T"] == r["down_h"])
print(f"boards==down_h: {eq}/{len(remain)}")
ne = [(r["T"], r["name"], r["boards_T"], r["down_h"], r["dead_h"]) for r in remain if r["boards_T"] != r["down_h"]]
print("不等样本", len(ne), ne[:5])

# So 几板 == 往下锚判定的高度！用户说跟节点梯队判定有关 - 就是 down_h 选在了哪一层
print("\n=== 按 往下锚高度 down_h（=梯队判定高度）炸板率 ===")
for h in sorted(set(r["down_h"] for r in touch if r["down_h"])):
    sub = [r for r in touch if r["down_h"] == h]
    z = sum(1 for r in sub if r["zhaban"])
    print(f"  判定锚在{h}板: 摸{len(sub)} 炸{z} 炸板率{z/len(sub):.1%}")

print("\n=== 按 锚类型 anchor - need re-fetch ===")
# re-add anchor_type from days
# rebuild with anchor type
rows2 = []
for i in range(1, len(days)-1):
    prev, cur = days[i-1], days[i]
    t1 = days[i+1]
    ok, dead_h, dead, _ = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not ok: continue
    lad = bt.pick_ladder(pools[cur], cur)
    mem = lad.get("members") or set()
    for s in pools[cur]:
        if s["code"] not in mem: continue
        code = str(s["code"]).zfill(6)
        # find in remain by T+code
        pass

# map from kept remain
from ferment_open_seal_grid import theme_fb_counts, open_pct_t1, touch_seal_t1
enriched = []
for i in range(1, len(days)-1):
    prev, cur = days[i-1], days[i]
    t1 = days[i+1]
    ok, dead_h, dead, _ = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not ok: continue
    lad = bt.pick_ladder(pools[cur], cur)
    mem = set(lad.get("members") or set())
    if not mem: continue
    fbmap = theme_fb_counts(pools[cur])
    an = lad.get("anchor") or {}
    for s in pools[cur]:
        if s["code"] not in mem: continue
        if bt.is_gonggao(s, cur): continue
        code = str(s["code"]).zfill(6)
        th = (s.get("theme") or "").strip() or "（无）"
        fb = int(fbmap.get(th, 0))
        op = open_pct_t1(code, t1, pools_m.get(t1,{}).get(code))
        if op is None: continue
        touched, sealed = touch_seal_t1(code, t1, pools_m, int(s.get("boards") or 0))
        if touched is None: continue
        b = int(s.get("boards") or 0)
        enriched.append({
            "T": cur, "code": code, "name": s.get("name"),
            "boards": b, "down_h": lad.get("height"), "dead_h": dead_h,
            "anchor_type": lad.get("anchor_type"),
            "is_anchor": code == an.get("code"),
            "theme": th, "fb": fb, "open": op,
            "yizi": bt.is_yizi(s), "amt": bt.amount_yi(s),
            "touched": touched, "sealed": sealed,
            "zhaban": bool(touched and not sealed),
            "rel": b - dead_h if dead_h else None,
        })

kept2, drop = keep_top_open_per_group([
    {**r, "boards_T": r["boards"], "open_pct_T1": r["open"], "amount_yi": r["amt"],
     "touched": r["touched"], "sealed": r["sealed"], "zhaban": r["zhaban"],
     "yizi": r["yizi"], "cont": False, "dead_h": r["dead_h"], "down_h": r["down_h"]}
    for r in enriched
])
# re-merge fields
# keep_top returns with boards_T; match back
by = {(r["T"], r["code"]): r for r in enriched}
final = []
for r in kept2:
    e = by.get((r["T"], r["code"]))
    if not e: continue
    if e["fb"] >= 3 and e["open"] < 0:
        continue  # pit1
    final.append(e)

touch = [r for r in final if r["touched"]]
zha = [r for r in touch if r["zhaban"]]
print("\n最终样本 摸", len(touch), "炸", len(zha))

def rate(rows, pred, name):
    sub = [r for r in rows if pred(r)]
    if len(sub) < 2:
        return
    z = sum(1 for r in sub if r["zhaban"])
    oth = [r for r in rows if not pred(r)]
    zo = sum(1 for r in oth if r["zhaban"]) / len(oth) if oth else 0
    print(f"{name}: n摸={len(sub)} 炸={z} 炸板率={z/len(sub):.1%} | 其余炸板率={zo:.1%}")

print("\n=== 梯队判定相关 ===")
rate(touch, lambda r: r["anchor_type"]=="anchor_nat_yizi", "锚类型=自然一字")
rate(touch, lambda r: r["anchor_type"]=="anchor_reorg", "锚类型=重组")
rate(touch, lambda r: r["anchor_type"]=="anchor_two", "锚类型=二板兜底")
rate(touch, lambda r: r["is_anchor"], "本人是锚点票")
rate(touch, lambda r: not r["is_anchor"], "本人非锚点(同层跟风)")
rate(touch, lambda r: r["down_h"]==2, "判定高度=2板")
rate(touch, lambda r: r["down_h"]==3, "判定高度=3板")
rate(touch, lambda r: r["down_h"]>=4, "判定高度>=4板")

print("\n=== 相对断高 ===")
rate(touch, lambda r: r["rel"]==0, "boards==死绝高(同高)")
rate(touch, lambda r: r["rel"]==-1, "H-1")
rate(touch, lambda r: r["rel"] is not None and r["rel"]<=-2, "深切<=H-2")

print("\n=== 发酵 ===")
rate(touch, lambda r: r["fb"]==0, "fb=0")
rate(touch, lambda r: r["fb"] in (1,2), "fb=1-2")
rate(touch, lambda r: 3<=r["fb"]<=5, "fb=3-5中发酵")
rate(touch, lambda r: r["fb"]>=6, "fb>=6热")

print("\n=== 交叉：判定高度 × 发酵 ===")
for hlab, hp in [("锚高2", lambda r: r["down_h"]==2), ("锚高3", lambda r: r["down_h"]==3), ("锚高>=4", lambda r: r["down_h"]>=4)]:
    for flab, fp in [("fb0", lambda r: r["fb"]==0), ("fb1-2", lambda r: r["fb"] in (1,2)), ("fb3-5", lambda r: 3<=r["fb"]<=5), ("fb>=6", lambda r: r["fb"]>=6)]:
        sub = [r for r in touch if hp(r) and fp(r)]
        if len(sub)<3: continue
        z=sum(1 for r in sub if r["zhaban"])
        print(f"  {hlab}×{flab}: 摸{len(sub)} 炸{z} 率{z/len(sub):.0%}")

print("\n=== 交叉：锚类型 × 发酵 ===")
for at in ["anchor_nat_yizi", "anchor_reorg", "anchor_two"]:
    for flab, fp in [("fb0-2", lambda r: r["fb"]<=2), ("fb3-5", lambda r: 3<=r["fb"]<=5), ("fb>=6", lambda r: r["fb"]>=6)]:
        sub = [r for r in touch if r["anchor_type"]==at and fp(r)]
        if len(sub)<3: continue
        z=sum(1 for r in sub if r["zhaban"])
        print(f"  {at}×{flab}: 摸{len(sub)} 炸{z} 率{z/len(sub):.0%}")

print("\n=== 交叉：锚类型 × 开盘近板 ===")
for at in ["anchor_nat_yizi", "anchor_reorg", "anchor_two"]:
    sub = [r for r in touch if r["anchor_type"]==at and r["open"]>=9]
    if len(sub)<3: continue
    z=sum(1 for r in sub if r["zhaban"])
    print(f"  {at}×开>=9: 摸{len(sub)} 炸{z} 率{z/len(sub):.0%}")

print("\n=== 用户三例的梯队字段 ===")
for r in final if False else touch:
    pass
for r in enriched:
    if r["name"] in ("澄星股份", "神州高铁", "华升股份") or "澄星" in (r["name"] or "") or "神州" in (r["name"] or "") or r["name"]=="华升股份":
        if r["T"] in ("2025-10-14", "2026-03-31", "2026-04-20"):
            print(r["T"], r["name"], "boards", r["boards"], "down_h", r["down_h"], "dead_h", r["dead_h"],
                  "type", r["anchor_type"], "is_anchor", r["is_anchor"], "fb", r["fb"], "open", r["open"], "zha", r["zhaban"])

print("\n=== 剩余炸板: anchor_type 分布 ===")
print(Counter(r["anchor_type"] for r in zha))
print("剩余炸板 down_h", Counter(r["down_h"] for r in zha))
print("剩余炸板 fb桶", Counter(
    "0" if r["fb"]==0 else "1-2" if r["fb"]<=2 else "3-5" if r["fb"]<=5 else ">=6" for r in zha
))
print("封板对照 down_h", Counter(r["down_h"] for r in touch if r["sealed"]))
print("封板对照 type", Counter(r["anchor_type"] for r in touch if r["sealed"]))
