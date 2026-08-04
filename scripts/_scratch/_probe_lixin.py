import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()

def find(d, name=None, code=None):
    for s in pools.get(d, []):
        if name and s["name"]==name: return s
        if code and s.get("code")==code: return s
    return None

print("=== 立新能源 路径 + 当日自然最高 ===")
for d in days:
    s = find(d, "立新能源")
    if not s: continue
    mx, highs = bt.natural_max(pools[d], d)
    hn = [h["name"]+str(h["boards"]) for h in highs[:5]]
    print(f"{d} 立新{s['boards']}板 yizi={bt.is_yizi(s)} theme={s.get('theme')!r} amt={bt.amount_yi(s)} | 自然高标={mx} {hn}")

print("\n=== 立新连板窗口附近节点 ===")
for i in range(1, len(days)):
    prev, cur = days[i-1], days[i]
    if cur < "2026-07-14" or cur > "2026-07-28":
        continue
    dead_ok, mx, dead, alive = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    lad = bt.pick_ladder(pools[cur], cur)
    an = lad.get("anchor") or {}
    lx = find(cur, "立新能源")
    prev_lx = find(prev, "立新能源")
    if not dead_ok and not lx and not prev_lx:
        continue
    print(f"--- {cur} node={dead_ok} ---")
    if dead_ok:
        print(f"  死绝 h={mx} {[(h['name'], h['boards'], 'N' if bt.is_natural(h,prev) else 'G') for h in dead]}")
        print(f"  pick: {lad.get('anchor_type')} h={lad.get('height')} {an.get('name')}")
    if lx:
        print(f"  立新当日 {lx['boards']}板 amt={bt.amount_yi(lx)}")
    # show heights >=2 with names
    by = {}
    for s in pools[cur]:
        b=int(s.get("boards") or 0)
        if b>=2: by.setdefault(b, []).append(s)
    for h in sorted(by.keys(), reverse=True)[:6]:
        layer=sorted(by[h], key=lambda x: -(bt.amount_yi(x) or 0))
        print(f"  {h}板: {[(s['name'], bt.amount_yi(s), 'Y' if bt.is_yizi(s) else '', s.get('theme')) for s in layer[:8]]}")
