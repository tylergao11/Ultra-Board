# -*- coding: utf-8 -*-
"""事前(T日)特征 → 次日连板概率。不用 T+1 开盘价。"""
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import theme_fb_counts
import importlib.util

spec = importlib.util.spec_from_file_location("bt", "scripts/_scratch/backtest_main_ladder.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()


def theme_rank_map(stocks):
    fb = theme_fb_counts(stocks)
    items = sorted(fb.items(), key=lambda x: (-x[1], x[0]))
    rank, prev_c, prev_r = {}, None, 0
    for i, (th, c) in enumerate(items, 1):
        if c != prev_c:
            prev_r, prev_c = i, c
        rank[th] = prev_r
    return rank, fb, len(items)


def first_seal_sec(s):
    """首封距 9:30 秒；越小越早。09:25 一字 ≈ -300。"""
    ts = s.get("first_limit_ts")
    if ts is None:
        return None
    try:
        t = datetime.fromtimestamp(int(ts))
        # seconds from 9:30
        return (t.hour - 9) * 3600 + (t.minute - 30) * 60 + t.second
    except Exception:
        return None


def seal_bucket(sec):
    if sec is None:
        return "无首封"
    if sec <= -200:  # ~09:25-09:26
        return "竞价/一字级"
    if sec <= 0:
        return "9:30前"
    if sec <= 600:  # 10:00
        return "开盘10分钟内"
    if sec <= 1800:
        return "10:00-10:30"
    if sec <= 5400:
        return "午前"
    return "午后及更晚"


rows = []
for i in range(1, len(days) - 1):
    prev, cur = days[i - 1], days[i]
    t1 = days[i + 1]
    ok, dead_h, dead, _ = bt.is_high_tier_dead(
        pools[prev], set(pools_m[cur].keys()), prev
    )
    if not ok:
        continue
    lad = bt.pick_ladder(pools[cur], cur)
    mem = lad.get("members") or set()
    if not mem:
        continue
    ranks, fb, n_th = theme_rank_map(pools[cur])
    # competition within same boards + theme
    # also same theme any boards ge2
    layer = [s for s in pools[cur] if s["code"] in mem]
    # amount rank in ladder layer
    layer_sorted = sorted(layer, key=lambda s: -(bt.amount_yi(s) or 0))
    amt_rank = {s["code"]: i + 1 for i, s in enumerate(layer_sorted)}

    # theme ge2 peers
    theme_ge2 = defaultdict(list)
    for s in pools[cur]:
        if int(s.get("boards") or 0) < 2:
            continue
        if bt.is_gonggao(s, cur):
            continue
        th = (s.get("theme") or "").strip() or "（无）"
        theme_ge2[th].append(s)

    for s in layer:
        if bt.is_gonggao(s, cur):
            continue
        code = str(s["code"]).zfill(6)
        th = (s.get("theme") or "").strip() or "（无）"
        b = int(s.get("boards") or 0)
        s1 = pools_m.get(t1, {}).get(code)
        cont = bool(s1) and int(s1.get("boards") or 0) == b + 1
        rnk = ranks.get(th, n_th + 1)
        fbc = fb.get(th, 0)
        peers_tier = [
            x
            for x in layer
            if ((x.get("theme") or "").strip() or "（无）") == th
        ]
        peers_theme = theme_ge2.get(th, [])
        # first seal rank among same theme ge2 (earlier better)
        seals = []
        for x in peers_theme:
            sec = first_seal_sec(x)
            if sec is not None:
                seals.append((sec, x["code"]))
        seals.sort()
        seal_rank = None
        for j, (sec, c) in enumerate(seals, 1):
            if c == code:
                seal_rank = j
                break
        my_sec = first_seal_sec(s)
        # amount rank among same theme ge2
        th_sorted = sorted(peers_theme, key=lambda x: -(bt.amount_yi(x) or 0))
        th_amt_rank = next(
            (j + 1 for j, x in enumerate(th_sorted) if x["code"] == code), None
        )

        rows.append(
            {
                "T": cur,
                "name": s.get("name"),
                "code": code,
                "boards": b,
                "theme": th,
                "rank": rnk,
                "fb": fbc,
                "n_themes": n_th,
                "yizi": bt.is_yizi(s),
                "amt": bt.amount_yi(s),
                "amt_rank_layer": amt_rank.get(code),
                "n_layer": len(layer),
                "n_same_theme_tier": len(peers_tier),
                "n_theme_ge2": len(peers_theme),
                "first_seal_sec": my_sec,
                "seal_bucket": seal_bucket(my_sec),
                "seal_rank_theme": seal_rank,
                "n_seal_theme": len(seals),
                "th_amt_rank": th_amt_rank,
                "anchor_type": lad.get("anchor_type"),
                "down_h": lad.get("height"),
                "dead_h": dead_h,
                "is_anchor": code == (lad.get("anchor") or {}).get("code"),
                "cont": cont,
            }
        )

# same tier theme top amount only? user wants prediction without open - for fair eval use all down ladder or top amt in theme tier by T-day amount
# Use: within (T, boards, theme) keep max amount on T (not T+1 open) as "竞争龙头"
groups = defaultdict(list)
for r in rows:
    groups[(r["T"], r["boards"], r["theme"])].append(r)
comp = []
for g, items in groups.items():
    items = sorted(items, key=lambda x: (-(x["amt"] or 0), x["code"]))
    best = dict(items[0])
    best["group_n"] = len(items)
    comp.append(best)

print(f"全锚层票 {len(rows)}  同梯队同theme留T日额最大 {len(comp)}")
print(f"全样本连板率 {sum(r['cont'] for r in rows)/len(rows):.1%}")
print(f"竞争龙头连板率 {sum(r['cont'] for r in comp)/len(comp):.1%}")


def show(data, key_fn, title, min_n=8):
    print(f"\n=== {title} ===")
    buckets = defaultdict(list)
    for r in data:
        buckets[key_fn(r)].append(r)
    rows_out = []
    for k, sub in buckets.items():
        if len(sub) < min_n:
            continue
        rate = sum(x["cont"] for x in sub) / len(sub)
        rows_out.append((rate, len(sub), k))
    rows_out.sort(reverse=True)
    for rate, n, k in rows_out:
        print(f"  {k}: n={n} 连板率={rate:.1%}")
    return rows_out


data = comp  # 竞争龙头

show(data, lambda r: f"R{r['rank']}" if r["rank"] <= 5 else ("R6-10" if r["rank"] <= 10 else "R11+"), "发酵排名", 10)
show(data, lambda r: "R1" if r["rank"]==1 else ("R2-3" if r["rank"]<=3 else ("R4-6" if r["rank"]<=6 else "R7+")), "发酵排名分档", 15)
show(data, lambda r: r["seal_bucket"], "首封时间", 10)
show(data, lambda r: f"theme内首封第{r['seal_rank_theme']}" if r["seal_rank_theme"] and r["seal_rank_theme"]<=3 else ("theme内首封4+" if r["seal_rank_theme"] else "无"), "同板块首封排名", 8)
show(data, lambda r: f"同theme≥2板共{r['n_theme_ge2']}" if r["n_theme_ge2"]<=3 else ("4-6家" if r["n_theme_ge2"]<=6 else "7+家"), "同板块连板竞争家数", 10)
show(data, lambda r: "独苗同梯队theme" if r["n_same_theme_tier"]==1 else f"同梯队同theme{r['n_same_theme_tier']}家", "同梯队同属性竞争", 8)
show(data, lambda r: f"层内额第{r['amt_rank_layer']}" if r["amt_rank_layer"] and r["amt_rank_layer"]<=3 else "层内额4+", "往下锚层内额排名", 10)
show(data, lambda r: r["anchor_type"], "锚类型", 10)
show(data, lambda r: "锚点本人" if r["is_anchor"] else "非锚点", "是否锚点", 20)
show(data, lambda r: "一字" if r["yizi"] else "换手", "板型", 20)
show(data, lambda r: f"判定{r['down_h']}板", "梯队高度", 10)

# combos
print("\n=== 组合：排名 × 首封 ===")
for rlab, rp in [("R1-3", lambda r: r["rank"]<=3), ("R4+", lambda r: r["rank"]>=4)]:
    for slab, sp in [
        ("早封(竞价/10分内)", lambda r: r["first_seal_sec"] is not None and r["first_seal_sec"]<=600),
        ("晚封", lambda r: r["first_seal_sec"] is not None and r["first_seal_sec"]>600),
    ]:
        sub = [r for r in data if rp(r) and sp(r)]
        if len(sub) < 10:
            continue
        print(f"  {rlab}×{slab}: n={len(sub)} 连板={sum(r['cont'] for r in sub)/len(sub):.1%}")

print("\n=== 组合：排名 × 同板块首封第1 ===")
for rlab, rp in [("R1-3", lambda r: r["rank"]<=3), ("R4+", lambda r: r["rank"]>=4)]:
    for slab, sp in [
        ("板块首封第1", lambda r: r["seal_rank_theme"]==1),
        ("非第1", lambda r: r["seal_rank_theme"] and r["seal_rank_theme"]>1),
    ]:
        sub = [r for r in data if rp(r) and sp(r)]
        if len(sub) < 8:
            continue
        print(f"  {rlab}×{slab}: n={len(sub)} 连板={sum(r['cont'] for r in sub)/len(sub):.1%}")

print("\n=== 组合：R1-3 × 层内额第1 × 早封 ===")
sub = [r for r in data if r["rank"]<=3 and r["amt_rank_layer"]==1 and r["first_seal_sec"] is not None and r["first_seal_sec"]<=600]
print(f"  n={len(sub)} 连板={sum(r['cont'] for r in sub)/len(sub):.1%}" if sub else "  n=0")
sub2 = [r for r in data if r["rank"]>=7 and (r["amt_rank_layer"] or 99)>=3]
print(f"  冷且层内额弱: n={len(sub2)} 连板={sum(r['cont'] for r in sub2)/len(sub2):.1%}" if sub2 else "")

# simple score: can we separate?
print("\n=== 简单打分分层（无开盘）===")
# score: rank high better (low number), seal early, amt rank 1, theme seal rank 1
def score(r):
    sc = 0
    if r["rank"] == 1: sc += 3
    elif r["rank"] <= 3: sc += 2
    elif r["rank"] <= 6: sc += 1
    if r["seal_rank_theme"] == 1: sc += 2
    elif r["seal_rank_theme"] == 2: sc += 1
    if r["first_seal_sec"] is not None and r["first_seal_sec"] <= 0: sc += 2
    elif r["first_seal_sec"] is not None and r["first_seal_sec"] <= 600: sc += 1
    if r["amt_rank_layer"] == 1: sc += 1
    if r["yizi"]: sc += 1
    if r["n_same_theme_tier"] == 1: sc += 0  # neutral
    return sc

for lo, hi, lab in [(0, 2, "低分0-2"), (3, 4, "中分3-4"), (5, 6, "高分5-6"), (7, 99, "很高≥7")]:
    sub = [r for r in data if lo <= score(r) <= hi]
    if len(sub) < 5:
        continue
    print(f"  {lab}: n={len(sub)} 连板={sum(r['cont'] for r in sub)/len(sub):.1%}")

# three pits scores
print("\n=== 三坑货事前分 ===")
for r in rows:
    if r["name"] in ("澄星股份", "神州高铁", "华升股份") and r["T"] in (
        "2025-10-14", "2026-03-31", "2026-04-20"
    ):
        print(
            r["T"], r["name"], f"cont={r['cont']}", f"rank={r['rank']}",
            f"seal_bucket={r['seal_bucket']}", f"seal_rank_theme={r['seal_rank_theme']}",
            f"amt_rank_layer={r['amt_rank_layer']}", f"n_theme_ge2={r['n_theme_ge2']}",
            f"score={score(r)}", f"yizi={r['yizi']}", f"amt={r['amt']}"
        )
