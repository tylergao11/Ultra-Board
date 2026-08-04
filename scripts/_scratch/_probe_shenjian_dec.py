import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()

def find(d, name):
    for s in pools.get(d, []):
        if s["name"] == name:
            return s
    return None

print("=== 2025-12 神剑路径 + 自然高标 ===")
for d in days:
    if not d.startswith("2025-12"):
        continue
    s = find(d, "神剑股份")
    mx, highs = bt.natural_max(pools[d], d)
    hn = [(h["name"], h["boards"]) for h in highs]
    if s or mx >= 5:
        line = f"{d} 自然高={mx}{hn[:4]}"
        if s:
            line += f" | 神剑{s['boards']} yizi={bt.is_yizi(s)} amt={bt.amount_yi(s)} theme={s.get('theme')}"
        print(line)

print("\n=== 12月节点 ===")
for i in range(1, len(days)):
    prev, cur = days[i-1], days[i]
    if not cur.startswith("2025-12") and not prev.startswith("2025-12"):
        continue
    if cur < "2025-12-01" or cur > "2026-01-05":
        continue
    dead_ok, dead_h, dead, alive = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not dead_ok:
        continue
    mx, highs = bt.natural_max(pools[cur], cur)
    nat = [s for s in pools[cur] if int(s.get("boards") or 0)==mx and bt.is_natural(s, cur)]
    lad = bt.pick_ladder(pools[cur], cur)
    an = lad.get("anchor") or {}
    nd = days[days.index(cur)+1] if days.index(cur)+1 < len(days) else None
    def promo(s):
        if not nd: return False
        for t in pools.get(nd, []):
            if t["code"]==s["code"]:
                return int(t["boards"])==int(s["boards"])+1
        return False
    print(f"NODE {cur} 死绝{dead_h} {[h['name']+str(h['boards']) for h in dead]}")
    print(f"  自然最高{mx} n={len(nat)} {[s['name']+str(s['boards'])+'/'+str(bt.amount_yi(s)) for s in nat]} 晋级={[s['name'] for s in nat if promo(s)]}")
    print(f"  往下={lad.get('anchor_type')} {lad.get('height')} {an.get('name')}")
    sj = find(cur, "神剑股份")
    print(f"  神剑当日: {sj['boards'] if sj else None}板")
