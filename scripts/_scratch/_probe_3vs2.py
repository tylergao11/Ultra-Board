import sys
sys.path.insert(0, "scripts/_scratch")
import backtest_main_ladder as bt

days, pools, pools_m = bt.load_days()

# Critical node days user implies: 3-board lock vs 2-board fallback
focus = [
    ("立新能源", "2026-07-17"),
    ("津药药业", "2026-03-26"),
    ("华远控股", "2026-04-08"),
    ("华远控股", "2026-04-10"),
    ("津药药业", "2026-03-31"),
]

for name, d in focus:
    print("=" * 70)
    print(name, "NODE?", d)
    g = bt.ge2(pools[d])
    by_h = {}
    for s in g:
        by_h.setdefault(int(s["boards"]), []).append(s)
    lad = bt.pick_ladder(pools[d], d)
    an = lad["anchor"]
    print(f"  PICK: {lad['anchor_type']} h={lad['height']} anchor={an['name'] if an else None} "
          f"yizi={an.get('is_yizi') if an else None} amt={an.get('amount_yi') if an else None}")
    for h in sorted(by_h.keys(), reverse=True):
        if h < 2:
            continue
        layer = sorted(by_h[h], key=lambda s: -(bt.amount_yi(s) or 0))
        print(f"  -- {h}板 n={len(layer)} --")
        for s in layer:
            tags = []
            if bt.is_yizi(s):
                tags.append("一字")
            if bt.is_gonggao(s, d):
                tags.append("公告")
            if bt.is_reorg(s):
                tags.append("重组")
            mark = "*" if s["name"] == name else " "
            print(f"   {mark} {s['name']} {s['boards']}板 theme={s.get('theme')!r} "
                  f"amt={bt.amount_yi(s)} {'/'.join(tags)}")
