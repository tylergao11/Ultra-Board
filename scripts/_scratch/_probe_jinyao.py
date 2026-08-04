import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()

def find(d, name):
    for s in pools.get(d, []):
        if s["name"] == name:
            return s
    return None

names = ["美诺华", "神剑股份", "津药药业"]
print("=== 路径 ===")
for d in days:
    row = {n: find(d, n) for n in names}
    if not any(row.values()):
        continue
    def fmt(s):
        if not s: return "-"
        return f"{s['boards']}板 yizi={bt.is_yizi(s)} theme={s.get('theme')!r} amt={bt.amount_yi(s)}"
    print(f"{d}  美诺华:{fmt(row['美诺华'])}  神剑:{fmt(row['神剑股份'])}  津药:{fmt(row['津药药业'])}")

print("\n=== 含美诺华/神剑 死绝节点 ===")
for i in range(1, len(days)):
    prev, cur = days[i-1], days[i]
    dead_ok, mx, dead, alive = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not dead_ok:
        continue
    dn = [h["name"] for h in dead]
    if not any(x in dn for x in ["美诺华", "神剑股份"]):
        continue
    lad = bt.pick_ladder(pools[cur], cur)
    an = lad.get("anchor") or {}
    print(f"NODE {cur} 死绝={[(h['name'], h['boards']) for h in dead]}")
    print(f"  pick: {lad.get('anchor_type')} h={lad.get('height')} {an.get('name')}")
    jy = find(cur, "津药药业")
    print(f"  津药当日: {jy['boards'] if jy else None}板 amt={bt.amount_yi(jy) if jy else None} theme={jy.get('theme') if jy else None}")
    for h in sorted({int(s['boards']) for s in pools[cur] if int(s.get('boards') or 0)>=2}, reverse=True)[:5]:
        layer = [s for s in pools[cur] if int(s['boards'])==h]
        print(f"  {h}板: {[(s['name'], bt.amount_yi(s), 'Y' if bt.is_yizi(s) else '', s.get('theme')) for s in sorted(layer, key=lambda x: -(bt.amount_yi(x) or 0))]}")
