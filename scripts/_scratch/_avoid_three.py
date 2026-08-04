import sys, json
from pathlib import Path
from collections import defaultdict
sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import build_rows, load_bars, lim_pct, theme_fb_counts
from reverse_zhaban_top_open import keep_top_open_per_group
import importlib.util
spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()
TARGETS = {
    ("2025-10-14", "澄星股份"),
    ("2026-03-31", "神州高铁"),
    ("2026-04-20", "华升股份"),
}

def detail(T, name):
    i = days.index(T)
    prev, t1 = days[i-1], days[i+1]
    ok, dead_h, dead, alive = bt.is_high_tier_dead(pools[prev], set(pools_m[T].keys()), prev)
    lad = bt.pick_ladder(pools[T], T)
    fb = theme_fb_counts(pools[T])
    # layer same boards
    s0 = next(s for s in pools[T] if s["name"]==name)
    code = s0["code"]
    b0 = int(s0["boards"])
    th = s0.get("theme")
    same = [s for s in pools[T] if int(s.get("boards") or 0)==b0]
    same_th = [s for s in same if (s.get("theme") or "")==th]
    print("="*70)
    print(T, name, code)
    print(f"  节点 dead_h={dead_h} dead={[x['name']+str(x['boards']) for x in dead]}")
    print(f"  往下锚 type={lad['anchor_type']} h={lad['height']} anchor={(lad.get('anchor') or {}).get('name')}")
    print(f"  本人 boards={b0} theme={th} fb={fb.get(th,0)} yizi={bt.is_yizi(s0)} amt={bt.amount_yi(s0)} natural={bt.is_natural(s0,T)}")
    print(f"  同高整层 n={len(same)}: {[(s['name'], bt.amount_yi(s), s.get('theme'), bt.is_yizi(s)) for s in sorted(same, key=lambda x: -(bt.amount_yi(x) or 0))]}")
    print(f"  同高同theme n={len(same_th)}: {[s['name'] for s in same_th]}")
    # T day bar
    bT = load_bars(code).get(T) or {}
    b1 = load_bars(code).get(t1) or {}
    print(f"  T日K: {bT}")
    print(f"  T+1日K: {b1}")
    s1 = pools_m.get(t1, {}).get(code)
    print(f"  T+1在涨停池={s1 is not None}", f"boards={s1.get('boards') if s1 else None}")
    if b1 and b1.get("prev_close"):
        prev = float(b1["prev_close"])
        lim = prev * (1+lim_pct(code)/100)
        print(f"  T+1 open%={b1.get('open_pct')} high={b1.get('high')} close={b1.get('close')} limit~{lim:.2f}")
        print(f"  振幅%={(float(b1['high'])-float(b1['low']))/prev*100:.1f} 上影/实体")
        # opened from limit: high>=lim and low < lim*0.995
        hi, lo, cl = float(b1["high"]), float(b1["low"]), float(b1["close"])
        touched = hi >= lim - max(prev*0.003, 0.02)
        sealed = cl >= lim - max(prev*0.003, 0.02)
        opened = lo < lim - max(prev*0.005, 0.03)  # 盘中离开过涨停价附近
        print(f"  摸板={touched} 封死={sealed} 盘中离开板(近似开板)={opened}")
    # peers open T+1
    print("  同高同theme 次日开盘:")
    for s in same_th:
        c = s["code"]
        bb = load_bars(c).get(t1) or {}
        print(f"    {s['name']} open%={bb.get('open_pct')} amtT={bt.amount_yi(s)} yizi={bt.is_yizi(s)}")

for T, name in sorted(TARGETS):
    detail(T, name)

# after filters: pit1 gone, only 换手 or 有开板, top open group
raw = build_rows(days, pools, pools_m)
kept, _ = keep_top_open_per_group(raw)
remain = [r for r in kept if not (r["fb"]>=3 and r["open_pct_T1"]<0)]
touch = [r for r in remain if r["touched"]]

# classify 一字开: open_pct >= 9.5 (main board ~10) or >=19 for chi next
def is_yizi_open(r):
    op = r["open_pct_T1"]
    code = r["code"]
    lim = lim_pct(code)
    return op >= lim - 0.5  # 接近涨停开

# 盘中是否开板: low not at limit
def left_limit(r):
    b = load_bars(r["code"]).get(r["T1"]) or {}
    if not b or not b.get("prev_close"):
        return None
    prev = float(b["prev_close"])
    lim = prev * (1+lim_pct(r["code"])/100)
    lo = float(b["low"])
    return lo < lim - max(prev*0.005, 0.03)

print("\n" + "="*70)
print("三例同类：近板开(open>=9) + 炸 + 删水下后")
near_z = [r for r in touch if r["zhaban"] and r["open_pct_T1"]>=9]
print(f"n={len(near_z)}")
for r in sorted(near_z, key=lambda x: -x["open_pct_T1"]):
    left = left_limit(r)
    yo = is_yizi_open(r)
    print(f"  {r['T']} {r['name']} {r['boards_T']}板 fb={r['fb']} open={r['open_pct_T1']:.1f}% "
          f"amt={r['amount_yi']} yizi板={r['yizi']} 开盘贴板={yo} 盘中离开板={left} {r['theme']}")

# avoid rules test
print("\n=== 规避规则效果（摸板子集，已删发酵水下，同组开最高）===")
base_z = sum(1 for r in touch if r["zhaban"])
print(f"基线 摸{len(touch)} 炸{base_z} 率{base_z/len(touch):.1%}")

def test(pred, name):
    # pred True = KILL (avoid)
    left = [r for r in touch if not pred(r)]
    killed = [r for r in touch if pred(r)]
    z_left = sum(1 for r in left if r["zhaban"])
    # how many of 3 targets killed
    tnames = {"澄星股份", "神州高铁", "华升股份"}
    kill_t = [r for r in killed if r["name"] in tnames]
    save_t = [r for r in left if r["name"] in tnames and r["zhaban"]]
    print(f"{name}")
    print(f"  杀掉摸板{len(killed)} 剩摸{len(left)} 剩炸{z_left} 炸板率{z_left/len(left) if left else 0:.1%}")
    print(f"  三例杀掉{[r['name'] for r in kill_t]} 仍漏炸三例{[r['name'] for r in save_t]}")

# rules
test(lambda r: r["open_pct_T1"]>=9 and r["fb"]>=3, "R1 近板且中高发酵fb>=3")
test(lambda r: r["open_pct_T1"]>=9 and 3<=r["fb"]<=5, "R2 近板且中发酵fb3-5")
test(lambda r: r["open_pct_T1"]>=9 and r["boards_T"]>=3 and r["fb"]>=3, "R3 近板+>=3板+fb>=3")
test(lambda r: r["open_pct_T1"]>=9 and (r["amount_yi"] or 99)<2 and r["yizi"], "R4 近板一字小额<2（澄星型）")
test(lambda r: r["open_pct_T1"]>=9 and ((r["amount_yi"] or 99)<2 or (3<=r["fb"]<=5)), "R5 近板且(小额<2 或 fb3-5)")
test(lambda r: r["open_pct_T1"]>=9.5 and not r["yizi"] and r["fb"]>=3, "R6 换手近板+fb>=3（神州华升型）")
test(lambda r: r["open_pct_T1"]>=9 and (r["yizi"] and (r["amount_yi"] or 99)<2 or (not r["yizi"] and r["fb"]>=3)),
     "R7 近板+(一字小额 或 换手中高发酵)")

# among near open, what separates seal vs zha
print("\n=== 近板开>=9 封 vs 炸 ===")
near = [r for r in touch if r["open_pct_T1"]>=9]
print("摸", len(near), "炸", sum(1 for r in near if r["zhaban"]), "封", sum(1 for r in near if r["sealed"]))
for lab, pred in [
    ("炸", lambda r: r["zhaban"]),
    ("封", lambda r: r["sealed"]),
]:
    sub=[r for r in near if pred(r)]
    if not sub: continue
    print(lab, "n", len(sub),
          "均fb", sum(r["fb"] for r in sub)/len(sub),
          "均额", sum((r["amount_yi"] or 0) for r in sub)/len(sub),
          "一字占比", sum(1 for r in sub if r["yizi"])/len(sub),
          "均板", sum(r["boards_T"] for r in sub)/len(sub),
          "fb3-5占比", sum(1 for r in sub if 3<=r["fb"]<=5)/len(sub),
          "fb>=6占比", sum(1 for r in sub if r["fb"]>=6)/len(sub),
          "fb0占比", sum(1 for r in sub if r["fb"]==0)/len(sub))
