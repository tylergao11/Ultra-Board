import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()
day_i = {d: i for i, d in enumerate(days)}

# Find when each stock was on 2-board / climbing, and what ladder pick was on nearby node days
targets = {
    "立新能源": "001258",
    "津药药业": "600488",
    "华远控股": "600743",
}

# Nodes from same logic as list
nodes = []
for i in range(1, len(days)):
    prev, cur = days[i - 1], days[i]
    dead_ok, mx, dead, alive = bt.is_high_tier_dead(
        pools[prev], set(pools_m[cur].keys()), prev
    )
    if not dead_ok:
        continue
    lad = bt.pick_ladder(pools[cur], cur)
    nodes.append((cur, prev, mx, dead, lad))

print("=== 三票连板路径 + 同期节点锚点 ===\n")
for name, code in targets.items():
    print("=" * 70)
    print(name, code)
    path = []
    for d in days:
        for s in pools[d]:
            if s.get("code") == code or s.get("name") == name:
                path.append((d, s))
                break
    for d, s in path:
        b = int(s.get("boards") or 0)
        yz = bt.is_yizi(s)
        gg = bt.is_gonggao(s, d)
        print(f"  {d}  {b}板  theme={s.get('theme')!r}  yizi={yz}  gg={gg}  amt={s.get('amount')}")
    # node days while stock is in pool at 2+ or just before its rise
    print("  --- 附近节点 ---")
    path_days = {d for d, _ in path}
    for cur, prev, mx, dead, lad in nodes:
        # show if within 15 days of any path day or stock in tier
        in_tier = any(m.get("name") == name or m.get("code") == code for m in lad.get("tier") or [])
        stock_today = None
        for s in pools[cur]:
            if s.get("code") == code or s.get("name") == name:
                stock_today = s
                break
        # relevant: stock at 2-3 boards around node, or name in dead, or close to path
        show = in_tier or stock_today or any(abs(day_i[cur] - day_i[pd]) <= 3 for pd in path_days if pd in day_i)
        if not show:
            continue
        an = lad.get("anchor") or {}
        print(
            f"  NODE {cur} dead_h={mx} anchor={an.get('name')}({lad.get('anchor_type')}) "
            f"h={lad.get('height')} n={len(lad.get('members') or [])} "
            f"stock_today={stock_today.get('boards') if stock_today else None}板 in_tier={in_tier}"
        )
        # list 3-board and 2-board natural yizi / reorg briefly
        by_h = {}
        for s in pools[cur]:
            by_h.setdefault(int(s.get("boards") or 0), []).append(s)
        for h in sorted(by_h.keys(), reverse=True)[:6]:
            layer = by_h[h]
            nat = [x for x in layer if bt.is_natural(x, cur)]
            yizi = [x for x in nat if bt.is_yizi(x)]
            reorg = [x for x in layer if bt.is_reorg(x)] if hasattr(bt, "is_reorg") else []
            print(f"    {h}板层 n={len(layer)} nat={len(nat)} yizi={[x['name'] for x in yizi]} "
                  f"gg={[x['name'] for x in layer if bt.is_gonggao(x,cur)][:4]}")
