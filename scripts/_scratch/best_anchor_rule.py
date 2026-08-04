# -*- coding: utf-8 -*-
"""节点日定锚：用 T+1 连板/封板 判定「该锚顶还是锚底」。

目标：输出一条可执行规则 —— 何时用今日自然最高、何时用往下回退。
评价（不定票）：
  - 连板率：集合内 T+1 boards=T+1
  - 封板率：摸板条件下封住（没摸板不算）
  - 四案是否落入所选集合
  - 分叉日：顶≠底时，规则选的那侧是否优于另一侧
"""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT = ROOT / "data" / "kaipanla" / "ladder_daily" / "best_anchor_rule.md"

_cache: dict[str, dict] = {}
KNOWN = {
    "2025-12-24": "002361",
    "2026-04-01": "600488",
    "2026-04-10": "600743",
    "2026-07-20": "001258",
}


def bars(code: str) -> dict:
    if code in _cache:
        return _cache[code]
    p = CACHE / f"{code}.json"
    if not p.exists():
        _cache[code] = {}
        return {}
    try:
        _cache[code] = (json.loads(p.read_text(encoding="utf-8-sig")).get("bars") or {})
    except Exception:
        _cache[code] = {}
    return _cache[code]


def lim_pct(code: str) -> float:
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    return 10.0


def touch_seal_cont(code: str, day_t1: str, pools_m: dict, b0: int):
    s1 = pools_m.get(day_t1, {}).get(code)
    cont = bool(s1) and int(s1.get("boards") or 0) == b0 + 1
    bar = bars(code).get(day_t1)
    if bar and bar.get("high") is not None and bar.get("prev_close"):
        try:
            high, close, prev = float(bar["high"]), float(bar["close"]), float(bar["prev_close"])
            if prev <= 0:
                raise ValueError
            lp = lim_pct(code)
            limit_px = prev * (1 + lp / 100)
            tol = max(prev * 0.003, 0.02)
            touched = high + 1e-9 >= limit_px - tol
            sealed = close + 1e-9 >= limit_px - tol
            if cont:
                return True, True, True
            if s1 is not None:
                return True, True, cont
            return touched, sealed, cont
        except Exception:
            pass
    if s1 is not None:
        return True, True, cont
    if bar is None:
        return None, None, cont  # no data
    return False, False, cont


def metrics(members: list, t1: str, pools_m: dict):
    """return cont_rate, seal_rate(touch), n, n_touch, n_cont, n_seal"""
    if not members:
        return 0.0, 0.0, 0, 0, 0, 0
    n = len(members)
    n_touch = n_seal = n_cont = 0
    for s in members:
        b0 = int(s.get("boards") or 0)
        t, se, c = touch_seal_cont(s["code"], t1, pools_m, b0)
        if c:
            n_cont += 1
        if t is None:
            continue
        if not t:
            continue
        n_touch += 1
        if se:
            n_seal += 1
    cont_r = n_cont / n
    seal_r = n_seal / n_touch if n_touch else None
    return cont_r, seal_r, n, n_touch, n_cont, n_seal


def layer(stocks, day):
    h, highs = bt.natural_max(stocks, day)
    return h, list(highs)


# ---- decision rules: return ("top"|"down", members) ----

def rule_always_down(top, down, th, dh, dead_h, day):
    return "down", down


def rule_always_top(top, down, th, dh, dead_h, day):
    return "top", top if top else down


def rule_top_if_sole(top, down, th, dh, dead_h, day):
    if len(top) == 1:
        return "top", top
    return "down", down


def rule_top_if_sole_noyizi(top, down, th, dh, dead_h, day):
    if len(top) == 1 and not bt.is_yizi(top[0]):
        return "top", top
    return "down", down


def rule_top_if_near_thin(top, down, th, dh, dead_h, day):
    if top and th >= max((dead_h or 0) - 1, 2) and len(top) <= 2:
        return "top", top
    return "down", down


def rule_top_if_near_sole(top, down, th, dh, dead_h, day):
    if top and th >= max((dead_h or 0) - 1, 2) and len(top) == 1:
        return "top", top
    return "down", down


def rule_top_if_near_sole_noy(top, down, th, dh, dead_h, day):
    if (
        top
        and th >= max((dead_h or 0) - 1, 2)
        and len(top) == 1
        and not bt.is_yizi(top[0])
    ):
        return "top", top
    return "down", down


def rule_top_if_h_ge3_sole(top, down, th, dh, dead_h, day):
    if top and th >= 3 and len(top) == 1:
        return "top", top
    return "down", down


def rule_compare_size_prefer_top_thin(top, down, th, dh, dead_h, day):
    """若顶层 n<=2 且高度>=3 用顶，否则底（不看 dead_h）"""
    if top and th >= 3 and len(top) <= 2:
        return "top", top
    return "down", down


def rule_oracle(top, down, th, dh, dead_h, day, t1, pools_m):
    """上界：选连板率更高的一侧（并列取封板率，再取顶）"""
    cr_t, sr_t, *_ = metrics(top, t1, pools_m)
    cr_d, sr_d, *_ = metrics(down, t1, pools_m)
    # prefer higher cont; tie seal; tie top if thin
    st_t = (cr_t, sr_t if sr_t is not None else -1, 1 if len(top) <= 2 else 0)
    st_d = (cr_d, sr_d if sr_d is not None else -1, 0)
    if st_t >= st_d and top:
        return "top", top
    return "down", down


RULES = [
    ("always_down", "永远往下", rule_always_down),
    ("always_top", "永远今日最高", rule_always_top),
    ("sole", "独苗→顶否则底", rule_top_if_sole),
    ("sole_noyizi", "独苗无一字→顶否则底", rule_top_if_sole_noyizi),
    ("near_thin", "近死绝且n≤2→顶否则底", rule_top_if_near_thin),
    ("near_sole", "近死绝且独苗→顶否则底", rule_top_if_near_sole),
    ("near_sole_noy", "近死绝+独苗无一字→顶否则底", rule_top_if_near_sole_noy),
    ("h3_sole", "h≥3独苗→顶否则底", rule_top_if_h_ge3_sole),
    ("h3_thin", "h≥3且n≤2→顶否则底", rule_compare_size_prefer_top_thin),
]


def main():
    days, pools, pools_m = bt.load_days()
    nodes = []
    for i in range(1, len(days) - 1):
        prev, cur = days[i - 1], days[i]
        t1 = days[i + 1]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue
        th, top = layer(pools[cur], cur)
        lad = bt.pick_ladder(pools[cur], cur)
        down = [s for s in pools[cur] if s["code"] in (lad.get("members") or set())]
        nodes.append(
            {
                "T": cur,
                "t1": t1,
                "dead_h": dead_h,
                "th": th,
                "top": top,
                "down": down,
                "dh": lad.get("height"),
                "same": set(x["code"] for x in top)
                == set(x["code"] for x in down),
            }
        )

    # oracle + rules stats
    results = {}
    for rid, rname, fn in RULES + [("oracle", "事后最优侧(上界)", None)]:
        results[rid] = {
            "name": rname,
            "n": 0,
            "n_all": 0,
            "n_cont": 0,
            "n_touch": 0,
            "n_seal": 0,
            "pick_top": 0,
            "known": 0,
            "diverge_n": 0,
            "diverge_pick_better_cont": 0,  # vs other side
            "node_cont_sum": 0.0,
        }

    diverge_cases = []  # for analysis when top wins

    for node in nodes:
        top, down = node["top"], node["down"]
        t1 = node["t1"]
        cr_t, sr_t, nt, ntt, nct, nst = metrics(top, t1, pools_m)
        cr_d, sr_d, nd, ntd, ncd, nsd = metrics(down, t1, pools_m)
        codes_top = {s["code"] for s in top}
        codes_down = {s["code"] for s in down}
        diverge = codes_top != codes_down and top and down

        for rid, rname, fn in RULES:
            if fn is None:
                continue
            side, mem = fn(
                top, down, node["th"], node["dh"], node["dead_h"], node["T"]
            )
            cr, sr, n, n_touch, n_cont, n_seal = metrics(mem, t1, pools_m)
            a = results[rid]
            a["n"] += 1
            a["n_all"] += n
            a["n_cont"] += n_cont
            a["n_touch"] += n_touch
            a["n_seal"] += n_seal
            a["node_cont_sum"] += cr
            if side == "top":
                a["pick_top"] += 1
            if node["T"] in KNOWN and KNOWN[node["T"]] in {s["code"] for s in mem}:
                a["known"] += 1
            if diverge:
                a["diverge_n"] += 1
                # is picked side cont better or equal than other?
                other = down if side == "top" else top
                cr_o, *_ = metrics(other, t1, pools_m)
                if cr + 1e-9 >= cr_o:
                    a["diverge_pick_better_cont"] += 1

        # oracle
        side, mem = rule_oracle(
            top, down, node["th"], node["dh"], node["dead_h"], node["T"], t1, pools_m
        )
        cr, sr, n, n_touch, n_cont, n_seal = metrics(mem, t1, pools_m)
        a = results["oracle"]
        a["n"] += 1
        a["n_all"] += n
        a["n_cont"] += n_cont
        a["n_touch"] += n_touch
        a["n_seal"] += n_seal
        a["node_cont_sum"] += cr
        if side == "top":
            a["pick_top"] += 1
        if node["T"] in KNOWN and KNOWN[node["T"]] in {s["code"] for s in mem}:
            a["known"] += 1

        if diverge:
            # record when top has strictly better cont
            if cr_t > cr_d + 1e-9:
                diverge_cases.append(
                    {
                        "T": node["T"],
                        "dead_h": node["dead_h"],
                        "th": node["th"],
                        "dh": node["dh"],
                        "top_n": len(top),
                        "sole": len(top) == 1,
                        "noyizi": len(top) == 1 and not bt.is_yizi(top[0]),
                        "near": node["th"] >= max((node["dead_h"] or 0) - 1, 2),
                        "cr_t": cr_t,
                        "cr_d": cr_d,
                        "names": [s["name"] for s in top],
                    }
                )

    # reverse: among days top beats down on cont, what features?
    n_top_better = len(diverge_cases)
    if n_top_better:
        f_sole = sum(1 for x in diverge_cases if x["sole"]) / n_top_better
        f_noy = sum(1 for x in diverge_cases if x["noyizi"]) / n_top_better
        f_near = sum(1 for x in diverge_cases if x["near"]) / n_top_better
        f_near_sole = sum(
            1 for x in diverge_cases if x["near"] and x["sole"]
        ) / n_top_better
        f_h3_sole = sum(
            1 for x in diverge_cases if x["th"] >= 3 and x["sole"]
        ) / n_top_better
    else:
        f_sole = f_noy = f_near = f_near_sole = f_h3_sole = 0

    # false positive rate of each gate: when gate says top, is cont_top >= cont_down?
    gate_quality = []
    for rid, rname, fn in RULES:
        if rid.startswith("always"):
            continue
        tp = fp = 0  # top pick correct/wrong vs cont
        for node in nodes:
            top, down = node["top"], node["down"]
            if not top or not down:
                continue
            side, _ = fn(
                top, down, node["th"], node["dh"], node["dead_h"], node["T"]
            )
            if side != "top":
                continue
            cr_t, *_ = metrics(top, node["t1"], pools_m)
            cr_d, *_ = metrics(down, node["t1"], pools_m)
            if cr_t + 1e-9 >= cr_d:
                tp += 1
            else:
                fp += 1
        gate_quality.append((rid, rname, tp, fp, tp / (tp + fp) if tp + fp else 0))

    lines = []
    lines.append("# 节点日定锚：哪条规则更能「锚到对的一侧」\n")
    lines.append(
        "评价只看 **T+1 连板率 / 摸板封板率** + **四案是否进集合**。"
        "规则形态：`若条件则锚今日自然最高整层，否则锚往下回退层`（**二选一**，不是并集）。\n"
    )
    lines.append(f"节点 n={len(nodes)}（需有 T+1）\n")

    lines.append("## 1. 反推：顶连板优于底时，长什么样\n")
    lines.append(
        f"顶底集合不同且 **顶连板率 > 底** 的节点：**{n_top_better}** 次\n"
    )
    if n_top_better:
        lines.append("| 特征 | 占这些日的比例 |")
        lines.append("|------|----------------|")
        lines.append(f"| 独苗 | {f_sole:.0%} |")
        lines.append(f"| 独苗且无一字 | {f_noy:.0%} |")
        lines.append(f"| 近死绝 h≥H-1 | {f_near:.0%} |")
        lines.append(f"| 近死绝且独苗 | {f_near_sole:.0%} |")
        lines.append(f"| h≥3 且独苗 | {f_h3_sole:.0%} |")
        lines.append("")
        lines.append("样例：")
        for x in diverge_cases[:10]:
            lines.append(
                f"- `{x['T']}` 死{x['dead_h']} 顶{x['th']}n={x['top_n']} "
                f"{x['names']} cont顶{x['cr_t']:.0%}>底{x['cr_d']:.0%} "
                f"sole={x['sole']} near={x['near']}"
            )
        lines.append("")

    lines.append("## 2. 正推：各判定规则表现\n")
    lines.append(
        "| 规则 | 连板率 | 封板率(封/摸) | 选顶% | 四案 | 分叉日选对侧%* | 节点均连板 |"
    )
    lines.append(
        "|------|--------|---------------|-------|------|----------------|------------|"
    )

    rows = []
    for rid, rname, _ in RULES + [("oracle", "事后最优侧(上界)", None)]:
        a = results[rid]
        n = a["n"] or 1
        cont = a["n_cont"] / a["n_all"] if a["n_all"] else 0
        seal = a["n_seal"] / a["n_touch"] if a["n_touch"] else 0
        pick_top = a["pick_top"] / n
        div = a.get("diverge_n") or 0
        div_ok = (
            a.get("diverge_pick_better_cont", 0) / div if div else None
        )
        rows.append((cont, seal, a["known"], rid, rname, a, pick_top, div_ok))
    rows.sort(key=lambda x: (-x[0], -x[1], -x[2]))

    for cont, seal, known, rid, rname, a, pick_top, div_ok in rows:
        div_s = f"{div_ok:.0%}" if div_ok is not None else "-"
        lines.append(
            f"| **{rid}** {rname} | {a['n_cont']}/{a['n_all']}={cont:.1%} | "
            f"{a['n_seal']}/{a['n_touch']}={seal:.1%} | {pick_top:.0%} | "
            f"{known}/4 | {div_s} | {a['node_cont_sum']/(a['n'] or 1):.1%} |"
        )
    lines.append("")
    lines.append(
        "\\*分叉日选对侧：顶底集合不同时，所选侧连板率 ≥ 另一侧的比例。\n"
    )

    lines.append("## 3. 门控精度：一旦选顶，顶是否真不弱于底（连板）\n")
    lines.append("| 规则 | 选顶次数 | 顶≥底 | 顶<底 | 选顶正确率 |")
    lines.append("|------|----------|-------|-------|------------|")
    gate_quality.sort(key=lambda x: -x[4])
    for rid, rname, tp, fp, rate in gate_quality:
        lines.append(
            f"| {rid} {rname} | {tp+fp} | {tp} | {fp} | {rate:.0%} |"
        )
    lines.append("")

    # pick recommended: max cont among known>=3, then seal, prefer sparse top picks with high gate quality
    viable = [
        (cont, seal, known, rid, rname, a, pick_top, div_ok)
        for cont, seal, known, rid, rname, a, pick_top, div_ok in rows
        if rid != "oracle"
    ]
    # score: 100*cont + 50*seal + 20*known/4 + 30*div_ok - 10*pick_top_extreme
    def score(row):
        cont, seal, known, rid, rname, a, pick_top, div_ok = row
        d = div_ok if div_ok is not None else 0.5
        # penalize always_top if known ok but cont low already in cont
        return 100 * cont + 40 * seal + 25 * (known / 4) + 30 * d

    best = max(viable, key=score)
    # also best known=4
    known4 = [r for r in viable if r[2] >= 4]
    best_k4 = max(known4, key=score) if known4 else best

    lines.append("## 4. 结论：节点日该用哪条\n")
    lines.append(f"### 推荐规则：`{best_k4[3]}` — {best_k4[4]}\n")
    a = best_k4[5]
    lines.append(
        f"- 连板率 **{a['n_cont']}/{a['n_all']}={best_k4[0]:.1%}**"
        f"（永远往下 {results['always_down']['n_cont']/results['always_down']['n_all']:.1%}；"
        f"永远最高 {results['always_top']['n_cont']/results['always_top']['n_all']:.1%}；"
        f"事后最优上界 {results['oracle']['n_cont']/results['oracle']['n_all']:.1%}）\n"
        f"- 封板率 **{best_k4[1]:.1%}**\n"
        f"- 四案 **{best_k4[2]}/4**\n"
        f"- 选顶比例 {best_k4[6]:.0%}（不是天天追最高）\n"
    )
    lines.append("### 执行伪代码\n")
    lines.append("```")
    lines.append("断板日 T:")
    lines.append("  Down = pick_ladder 往下回退整层")
    lines.append("  Top  = 今日自然最高整层")
    lines.append("  H    = 昨死绝自然高度")
    lines.append("  Ht   = 今日自然最高高度")
    lines.append("")
    if best_k4[3] == "near_sole_noy":
        lines.append("  if Top 独苗 and 非一字 and Ht >= H-1:")
        lines.append("      锚 = Top   # 反扑")
    elif best_k4[3] == "near_sole":
        lines.append("  if Top 独苗 and Ht >= H-1:")
        lines.append("      锚 = Top")
    elif best_k4[3] == "near_thin":
        lines.append("  if len(Top)<=2 and Ht >= H-1:")
        lines.append("      锚 = Top")
    elif best_k4[3] == "sole_noyizi":
        lines.append("  if Top 独苗 and 非一字:")
        lines.append("      锚 = Top")
    elif best_k4[3] == "h3_thin":
        lines.append("  if len(Top)<=2 and Ht >= 3:")
        lines.append("      锚 = Top")
    else:
        lines.append(f"  # 见规则 {best_k4[3]}")
        lines.append("  if <条件>: 锚 = Top")
    lines.append("  else:")
    lines.append("      锚 = Down  # 回退")
    lines.append("```\n")

    lines.append("### 能否「精准」？\n")
    o = results["oracle"]
    lines.append(
        f"- 事后知道 T+1 再选侧，连板率上界约 "
        f"**{o['n_cont']}/{o['n_all']}={o['n_cont']/o['n_all']:.1%}**\n"
        f"- 任何事前规则都到不了 100%；四案要求会逼你在部分日选顶\n"
        f"- **精准含义**：在「回退 vs 反扑」二选一上，用可观察特征逼近事后更优侧\n"
        f"- 若允许 **双锚并集** 不二选一，覆盖更高但不是「判定到一个锚」\n"
    )

    # compare top-3 by score
    ranked = sorted(viable, key=score, reverse=True)[:5]
    lines.append("### 综合分 Top 规则\n")
    for i, row in enumerate(ranked, 1):
        cont, seal, known, rid, rname, a, pick_top, div_ok = row
        lines.append(
            f"{i}. `{rid}` {rname}: 连板{cont:.1%} 封板{seal:.1%} "
            f"四案{known}/4 选顶{pick_top:.0%} score={score(row):.1f}"
        )

    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
