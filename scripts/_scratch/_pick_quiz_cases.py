import sys
from datetime import datetime
sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import theme_fb_counts
import importlib.util
spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()

def ranks(stocks):
    fb = theme_fb_counts(stocks)
    items = sorted(fb.items(), key=lambda x: (-x[1], x[0]))
    rank, pc, pr = {}, None, 0
    for i, (t, c) in enumerate(items, 1):
        if c != pc:
            pr, pc = i, c
        rank[t] = pr
    return rank, fb, len(items)

def seal_str(s):
    ts = s.get("first_limit_ts")
    if not ts:
        return "?"
    t = datetime.fromtimestamp(int(ts))
    return t.strftime("%H:%M")

cases = []
for i in range(1, len(days)-1):
    prev, cur = days[i-1], days[i]
    ok, dead_h, dead, _ = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not ok:
        continue
    lad = bt.pick_ladder(pools[cur], cur)
    mem = lad.get("members") or set()
    layer = [s for s in pools[cur] if s["code"] in mem and not bt.is_gonggao(s, cur)]
    if len(layer) < 2 or len(layer) > 6:
        continue
    n_yizi = sum(1 for s in layer if bt.is_yizi(s))
    n_big = sum(1 for s in layer if (bt.amount_yi(s) or 0) >= 5)
    # prefer mixed: has yizi and has large, or 3-5 names
    score = 0
    if 1 <= n_yizi <= 2:
        score += 2
    if n_big >= 1:
        score += 2
    if 2 <= len(layer) <= 4:
        score += 1
    if lad.get("anchor_type") == "anchor_two":
        score -= 1  # still can include some
    cases.append((score, cur, dead_h, dead, lad, layer))

cases.sort(key=lambda x: -x[0])
# diversify dates
picked = []
used_months = set()
for sc, cur, dead_h, dead, lad, layer in cases:
    m = cur[:7]
    if len(picked) >= 6:
        break
    # skip pure boring
    if sc < 2:
        continue
    # diversify
    if sum(1 for p in picked if p[1][:7]==m) >= 2:
        continue
    picked.append((sc, cur, dead_h, dead, lad, layer))

# force include if not enough
if len(picked) < 6:
    for sc, cur, dead_h, dead, lad, layer in cases:
        if any(p[1]==cur for p in picked):
            continue
        picked.append((sc, cur, dead_h, dead, lad, layer))
        if len(picked) >= 6:
            break

for idx, (sc, cur, dead_h, dead, lad, layer) in enumerate(picked, 1):
    rk, fb, nth = ranks(pools[cur])
    an = lad.get("anchor") or {}
    print("=" * 72)
    print(f"案例 {idx}. 节点日 T=`{cur}`  断昨自然{dead_h}板 {[d['name']+str(d['boards']) for d in dead[:3]]}")
    print(f"往下锚: {lad.get('anchor_type')} → {lad.get('height')}板  锚点={an.get('name')}")
    print(f"层内 {len(layer)} 只（已去掉公告）— 你会打哪个？不打哪个？")
    layer = sorted(layer, key=lambda s: (-(bt.amount_yi(s) or 0), s["code"]))
    for s in layer:
        th = s.get("theme") or ""
        r = rk.get(th, nth+1)
        fbc = fb.get(th, 0)
        print(
            f"  - {s['name']} {s['boards']}板 | theme={th} 发酵排名#{r}(fb={fbc}) | "
            f"{'一字' if bt.is_yizi(s) else '换手'} | 额={bt.amount_yi(s)}亿 | 首封{seal_str(s)}"
            f"{' | ★锚点' if s['code']==an.get('code') else ''}"
        )
    print()
