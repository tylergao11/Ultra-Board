import sys
from pathlib import Path
sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import theme_fb_counts, open_pct_t1
import importlib.util
spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()
NAMES = ["合富中国", "瑞尔特", "深华发", "华电辽能"]

def theme_rank(stocks, th):
    fb = theme_fb_counts(stocks)
    items = sorted(fb.items(), key=lambda x: (-x[1], x[0]))
    rank = {}
    prev_c, prev_r = None, 0
    for i, (t, c) in enumerate(items, 1):
        if c != prev_c:
            prev_r, prev_c = i, c
        rank[t] = prev_r
    th = th or "（无）"
    if th in rank:
        return rank[th], fb.get(th, 0), len(items)
    return len(items)+1, 0, len(items)

print("=== 四票完整在池路径 ===")
for name in NAMES:
    print("\n", name)
    for d in days:
        for s in pools[d]:
            if name in s["name"] or s["name"] == name:
                print(f"  {d} {s['name']} {s['boards']}板 theme={s.get('theme')!r} "
                      f"yizi={bt.is_yizi(s)} amt={bt.amount_yi(s)} "
                      f"首封={s.get('first_limit_ts')}")

print("\n=== 节点日里出现它们（往下锚层）===")
for i in range(1, len(days)-1):
    prev, cur = days[i-1], days[i]
    t1 = days[i+1]
    ok, dead_h, dead, _ = bt.is_high_tier_dead(pools[prev], set(pools_m[cur].keys()), prev)
    if not ok:
        continue
    lad = bt.pick_ladder(pools[cur], cur)
    mem = lad.get("members") or set()
    for s in pools[cur]:
        if s["code"] not in mem:
            continue
        if not any(n in s["name"] for n in NAMES):
            continue
        th = s.get("theme") or ""
        rnk, fbc, nth = theme_rank(pools[cur], th)
        an = lad.get("anchor") or {}
        s1 = pools_m.get(t1, {}).get(s["code"])
        cont = bool(s1) and int(s1.get("boards") or 0) == int(s["boards"])+1
        op = open_pct_t1(str(s["code"]).zfill(6), t1, s1)
        print(f"{cur} 断{dead_h}{[x['name'] for x in dead][:2]} | "
              f"{s['name']} {s['boards']}板 theme={th} rank=#{rnk} fb={fbc} "
              f"yizi={bt.is_yizi(s)} amt={bt.amount_yi(s)} "
              f"锚={an.get('name')}/{lad.get('anchor_type')} h={lad.get('height')} "
              f"本人是锚={s['code']==an.get('code')} | "
              f"T+1开={op} 连板={cont}")
        # 同层成员
        layer = [x for x in pools[cur] if x["code"] in mem]
        print("   层内:", [(x["name"], x["boards"], bt.amount_yi(x), x.get("theme"), bt.is_yizi(x)) 
                          for x in sorted(layer, key=lambda z: -(bt.amount_yi(z) or 0))])
