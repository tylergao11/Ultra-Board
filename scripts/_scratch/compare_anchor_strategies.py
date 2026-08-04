# -*- coding: utf-8 -*-
"""多策略定锚对比：抓龙头覆盖 + 胜率（精确率）。

指标（事前可算规则，事后评估）：
- hit_layer: T+1~10 自然高标 ∈ 选出成员
- hit_anchor: 锚点本人 ∈ T+1~10 自然高标
- avg_n: 平均人数（越小越「准」）
- precision_proxy: hit_layer / avg_n  （层命中按人数摊薄）
- strict_win: 选出 n<=3 且 hit_layer（窄层真赢）
- sole_win: n==1 且 hit_layer
- known3: 神剑12-24 / 津药04-01 / 华远04-10 / 立新07-20 是否点中
"""
from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

OUT = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "ladder_daily" / "anchor_strategy_compare.md"

# 已知必对样本：断板日 → 真主升 code/name
KNOWN = {
    "2025-12-24": ("002361", "神剑股份"),  # 鹭燕断→神剑
    "2026-04-01": ("600488", "津药药业"),  # 神剑断→津药4进5
    "2026-04-10": ("600743", "华远控股"),  # 汇源断→华远4进5
    "2026-07-20": ("001258", "立新能源"),  # 美大层断→立新3进4
}


def empty(rule: str) -> dict:
    return {
        "rule": rule,
        "anchor_type": rule,
        "anchor": None,
        "height": None,
        "tier": [],
        "members": set(),
        "detail": "",
    }


def make_from_stocks(stocks: list, day: str, rule: str, anchor: dict | None = None) -> dict:
    if not stocks:
        return empty(rule)
    briefs = [bt._brief(s, day) for s in stocks]
    briefs.sort(key=lambda x: (-(x["amount_yi"] or 0), x["code"]))
    an = anchor or briefs[0]
    h = int(an["boards"])
    return {
        "rule": rule,
        "anchor_type": rule,
        "anchor": an,
        "height": h,
        "tier": briefs,
        "members": {x["code"] for x in briefs},
        "detail": f"{rule} n={len(briefs)} h≈{h} 锚={an['name']}",
    }


def today_nat_layer(stocks: list, day: str) -> tuple[int, list]:
    h, highs = bt.natural_max(stocks, day)
    return h, list(highs)


def top_k_by_amt(stocks: list, k: int) -> list:
    return sorted(stocks, key=lambda s: (-(bt.amount_yi(s) or 0), s["code"]))[:k]


def yizi_amt(s: dict) -> float:
    return bt.amount_yi(s) or 0.0


# ---------- strategies (all ex-ante) ----------

def s_down(stocks, day, **kw):
    """现行往下锚整层"""
    return bt.pick_ladder(stocks, day)


def s_nat_max(stocks, day, **kw):
    """今日自然最高整层"""
    h, layer = today_nat_layer(stocks, day)
    if not layer:
        return empty("nat_max")
    return make_from_stocks(layer, day, "nat_max")


def s_nat_max_top1(stocks, day, **kw):
    """今日自然最高额最大一只"""
    h, layer = today_nat_layer(stocks, day)
    if not layer:
        return empty("nat_max_top1")
    return make_from_stocks(top_k_by_amt(layer, 1), day, "nat_max_top1")


def s_fanpu_else_down(stocks, day, **kw):
    """独苗且无一字 → 今日自然最高；否则往下锚整层"""
    h, layer = today_nat_layer(stocks, day)
    if len(layer) == 1 and not bt.is_yizi(layer[0]):
        return make_from_stocks(layer, day, "fanpu_else_down")
    return bt.pick_ladder(stocks, day)


def s_fanpu_else_down_top2(stocks, day, **kw):
    """反扑独苗无一字用最高；否则往下锚层内额 Top2（控人数）"""
    h, layer = today_nat_layer(stocks, day)
    if len(layer) == 1 and not bt.is_yizi(layer[0]):
        return make_from_stocks(layer, day, "fanpu_else_down_top2")
    lad = bt.pick_ladder(stocks, day)
    if not lad["tier"]:
        return lad
    # reconstruct from codes
    codes = {x["code"] for x in lad["tier"]}
    raw = [s for s in stocks if s["code"] in codes]
    return make_from_stocks(top_k_by_amt(raw, 2), day, "fanpu_else_down_top2")


def s_priority_quality_yizi(stocks, day, dead_h: int | None = None, **kw):
    """
    优先序：
    1) 今日自然最高若独苗无一字 → 用它
    2) 今日自然最高若有「够格自然一字」(额>=2亿) → 最高层整层
    3) 往下扫 h>=3：自然一字额>=2亿才锁层；重组不锁高层
    4) 否则今日自然最高 Top1
    5) 否则二板额 Top2
    """
    h, layer = today_nat_layer(stocks, day)
    if len(layer) == 1 and not bt.is_yizi(layer[0]):
        return make_from_stocks(layer, day, "quality_hybrid")
    if layer:
        fat_yizi = [
            s
            for s in layer
            if bt.is_natural(s, day) and bt.is_yizi(s) and yizi_amt(s) >= 2.0
        ]
        if fat_yizi:
            return make_from_stocks(layer, day, "quality_hybrid")

    by_h: dict[int, list] = defaultdict(list)
    for s in bt.ge2(stocks):
        by_h[int(s["boards"])].append(s)
    for hh in sorted(by_h.keys(), reverse=True):
        if hh < 3:
            continue
        L = by_h[hh]
        if bt.layer_all_gonggao(L, day):
            continue
        fat = [
            s
            for s in L
            if bt.is_natural(s, day) and bt.is_yizi(s) and yizi_amt(s) >= 2.0
        ]
        if fat:
            fat.sort(key=lambda s: -yizi_amt(s))
            return make_from_stocks(L, day, "quality_hybrid", bt._brief(fat[0], day))

    if layer:
        return make_from_stocks(top_k_by_amt(layer, 1), day, "quality_hybrid")
    two = [s for s in stocks if int(s.get("boards") or 0) == 2 and bt.is_natural(s, day)]
    if two:
        return make_from_stocks(top_k_by_amt(two, 2), day, "quality_hybrid")
    return empty("quality_hybrid")


def s_near_dead_sole(stocks, day, dead_h: int | None = None, **kw):
    """
    若今日自然最高 h_today >= dead_h-1 且（独苗 或 n<=2）→ 用今日最高层；
    否则往下锚。
    """
    h, layer = today_nat_layer(stocks, day)
    dh = dead_h or 0
    if layer and h >= max(dh - 1, 2) and len(layer) <= 2:
        return make_from_stocks(layer, day, "near_dead_sole")
    return bt.pick_ladder(stocks, day)


def s_max_amt_between(stocks, day, **kw):
    """
    比较：今日自然最高层 Top1 额 vs 往下锚层 Top1 额，选额更大的那一整层。
    """
    h, nat = today_nat_layer(stocks, day)
    lad = bt.pick_ladder(stocks, day)
    nat_top = max((yizi_amt(s) for s in nat), default=-1)
    down_top = 0.0
    if lad.get("tier"):
        down_top = max((x.get("amount_yi") or 0) for x in lad["tier"])
    if nat and nat_top >= down_top:
        return make_from_stocks(nat, day, "max_amt_layer")
    return lad if lad["rule"] != "empty" else make_from_stocks(nat, day, "max_amt_layer")


def s_union(stocks, day, **kw):
    """并集上界：今日最高 ∪ 往下锚（覆盖上限，不追求胜率）"""
    h, nat = today_nat_layer(stocks, day)
    lad = bt.pick_ladder(stocks, day)
    codes = set(lad.get("members") or set()) | {s["code"] for s in nat}
    raw = [s for s in stocks if s["code"] in codes]
    return make_from_stocks(raw, day, "union") if raw else empty("union")


def s_down_top1(stocks, day, **kw):
    """往下锚层内额 Top1（高精度窄）"""
    lad = bt.pick_ladder(stocks, day)
    if not lad.get("tier"):
        return lad
    codes = {x["code"] for x in lad["tier"]}
    raw = [s for s in stocks if s["code"] in codes]
    return make_from_stocks(top_k_by_amt(raw, 1), day, "down_top1")


def s_hybrid_fanpu_quality_top1(stocks, day, dead_h: int | None = None, **kw):
    """
    综合（偏胜率）：
    1) 独苗无一字今日最高 → 该票
    2) 今日最高 n<=2 且 h>=3 → 层内额最大 1 只
    3) 往下有自然一字额>=3亿 → 该一字本人
    4) 往下锚层 Top1
    """
    h, layer = today_nat_layer(stocks, day)
    if len(layer) == 1 and not bt.is_yizi(layer[0]):
        return make_from_stocks(layer, day, "hybrid_prec")
    if layer and len(layer) <= 2 and h >= 3:
        return make_from_stocks(top_k_by_amt(layer, 1), day, "hybrid_prec")

    by_h: dict[int, list] = defaultdict(list)
    for s in bt.ge2(stocks):
        by_h[int(s["boards"])].append(s)
    for hh in sorted(by_h.keys(), reverse=True):
        if hh < 3:
            continue
        fat = [
            s
            for s in by_h[hh]
            if bt.is_natural(s, day) and bt.is_yizi(s) and yizi_amt(s) >= 3.0
        ]
        if fat:
            return make_from_stocks(top_k_by_amt(fat, 1), day, "hybrid_prec")

    lad = bt.pick_ladder(stocks, day)
    if lad.get("tier"):
        codes = {x["code"] for x in lad["tier"]}
        raw = [s for s in stocks if s["code"] in codes]
        return make_from_stocks(top_k_by_amt(raw, 1), day, "hybrid_prec")
    if layer:
        return make_from_stocks(top_k_by_amt(layer, 1), day, "hybrid_prec")
    return empty("hybrid_prec")


def s_near_ceiling_nat_else_structure(stocks, day, dead_h: int | None = None, **kw):
    """AgentA: 近死绝高且(独苗/≤2/有一字)→今日最高整层，否则 pick_ladder；二板>4 则 Top3。"""
    H = dead_h or 0
    h, nat = today_nat_layer(stocks, day)
    if nat and h >= 3 and h >= H - 1:
        sole = len(nat) == 1
        has_yizi = any(bt.is_yizi(s) for s in nat)
        thin = len(nat) <= 2
        if has_yizi or sole or thin:
            return make_from_stocks(nat, day, "near_ceiling")
    lad = bt.pick_ladder(stocks, day)
    if lad.get("height") == 2 and len(lad.get("members") or []) > 4:
        codes = lad["members"]
        raw = [
            s
            for s in stocks
            if s["code"] in codes and bt.is_natural(s, day)
        ]
        if not raw:
            raw = [s for s in stocks if s["code"] in codes]
        return make_from_stocks(top_k_by_amt(raw, 3), day, "near_ceiling")
    return lad


def s_natmax_turnover_override(stocks, day, dead_h: int | None = None, **kw):
    """AgentB: 换手自然最高够额则锁最高层；否则够格一字；否则过滤往下。"""
    TH_SOLE, TH_LAYER, TH_YIZI = 2.0, 5.0, 1.0
    h, L = today_nat_layer(stocks, day)
    if L and h >= 3:
        turnover = [s for s in L if not bt.is_yizi(s)]
        A = max((yizi_amt(s) for s in L), default=0)
        if turnover:
            if len(L) == 1 and yizi_amt(L[0]) >= TH_SOLE:
                return make_from_stocks(L, day, "turnover_override")
            if len(L) >= 2 and A >= TH_LAYER:
                return make_from_stocks(L, day, "turnover_override")
        fat_y = [s for s in L if bt.is_yizi(s) and yizi_amt(s) >= TH_YIZI]
        if fat_y:
            return make_from_stocks(L, day, "turnover_override")

    by_h: dict[int, list] = defaultdict(list)
    for s in bt.ge2(stocks):
        by_h[int(s["boards"])].append(s)
    for hh in sorted(by_h.keys(), reverse=True):
        if hh < 3:
            continue
        Lh = [s for s in by_h[hh] if bt.is_natural(s, day)]
        if not Lh:
            continue
        yizi = [s for s in Lh if bt.is_yizi(s) and yizi_amt(s) >= TH_YIZI]
        if yizi:
            return make_from_stocks(Lh, day, "turnover_override", bt._brief(top_k_by_amt(yizi, 1)[0], day))
        turn = [s for s in Lh if (not bt.is_yizi(s)) and yizi_amt(s) >= TH_SOLE]
        if turn:
            return make_from_stocks(Lh, day, "turnover_override", bt._brief(top_k_by_amt(turn, 1)[0], day))
    two = [s for s in stocks if int(s.get("boards") or 0) == 2 and bt.is_natural(s, day)]
    if two:
        return make_from_stocks(top_k_by_amt(two, 3), day, "turnover_override")
    return empty("turnover_override")


def s_natmax_sole_topamt(stocks, day, **kw):
    """AgentC: 只打今日自然最高，独苗全收，多票额Top≤3；2板拥挤只Top1~2。"""
    h, L = today_nat_layer(stocks, day)
    if not L:
        return empty("natmax_topamt")
    L = sorted(L, key=lambda s: (-(bt.amount_yi(s) or 0), s["code"]))
    if len(L) == 1:
        return make_from_stocks(L, day, "natmax_topamt")
    # demote thin yizi if fat non-yizi exists
    filtered = []
    for s in L:
        if bt.is_yizi(s) and yizi_amt(s) < 2.0:
            fat = [
                x
                for x in L
                if (not bt.is_yizi(x)) and yizi_amt(x) >= max(5.0, 3 * yizi_amt(s))
            ]
            if fat:
                continue
        filtered.append(s)
    if not filtered:
        filtered = L
    if h == 2 and len(L) >= 4:
        k = 1
        if len(filtered) >= 2 and yizi_amt(filtered[1]) >= 0.5 * yizi_amt(filtered[0]):
            k = 2
        return make_from_stocks(filtered[:k], day, "natmax_topamt")
    k = min(3, len(filtered))
    return make_from_stocks(filtered[:k], day, "natmax_topamt")


STRATEGIES = [
    ("down", "现行往下锚整层", s_down),
    ("nat_max", "今日自然最高整层", s_nat_max),
    ("nat_max_top1", "今日自然最高额Top1", s_nat_max_top1),
    ("fanpu_else_down", "反扑优先否则往下整层", s_fanpu_else_down),
    ("fanpu_else_down_top2", "反扑优先否则往下Top2", s_fanpu_else_down_top2),
    ("near_dead_sole", "近死绝高且≤2只用最高否则往下", s_near_dead_sole),
    ("near_ceiling", "AgentA 近顶薄层否则结构往下", s_near_ceiling_nat_else_structure),
    ("turnover_override", "AgentB 换手最高够额覆盖", s_natmax_turnover_override),
    ("natmax_topamt", "AgentC 最高层独苗/额Top≤3", s_natmax_sole_topamt),
    ("max_amt_layer", "最高层Top1额 vs 往下Top1额 选整层", s_max_amt_between),
    ("quality_hybrid", "够格一字/反扑混合整层", s_priority_quality_yizi),
    ("hybrid_prec", "反扑+窄选Top1（偏胜率）", s_hybrid_fanpu_quality_top1),
    ("down_top1", "往下锚Top1", s_down_top1),
    ("union", "并集上界（覆盖）", s_union),
]


def future_nat_codes(days, pools, start_idx: int, horizon: int = 10) -> set[str]:
    codes = set()
    for j in range(start_idx, min(start_idx + horizon, len(days))):
        d = days[j]
        mx, highs = bt.natural_max(pools[d], d)
        if mx > 0:
            codes |= {s["code"] for s in highs}
    return codes


def main() -> int:
    days, pools, pools_m = bt.load_days()
    # collect nodes
    nodes = []
    for i in range(1, len(days)):
        prev, cur = days[i - 1], days[i]
        dead_ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not dead_ok:
            continue
        nodes.append((cur, prev, dead_h, dead, i))

    stats = {
        sid: {
            "n": 0,
            "hit": 0,
            "hit_anchor": 0,
            "sum_n": 0,
            "strict": 0,
            "sole_win": 0,
            "known_ok": 0,
            "empty": 0,
        }
        for sid, _, _ in STRATEGIES
    }
    known_detail = {sid: {} for sid, _, _ in STRATEGIES}

    for cur, prev, dead_h, dead, idx in nodes:
        fut = future_nat_codes(days, pools, idx + 1, 10) if idx + 1 < len(days) else set()
        for sid, _name, fn in STRATEGIES:
            pick = fn(pools[cur], cur, dead_h=dead_h)
            st = stats[sid]
            st["n"] += 1
            mem = pick.get("members") or set()
            if not mem:
                st["empty"] += 1
                continue
            st["sum_n"] += len(mem)
            hit = bool(mem & fut)
            if hit:
                st["hit"] += 1
            an = pick.get("anchor") or {}
            ac = an.get("code")
            if ac and ac in fut:
                st["hit_anchor"] += 1
            if hit and len(mem) <= 3:
                st["strict"] += 1
            if hit and len(mem) == 1:
                st["sole_win"] += 1
            if cur in KNOWN:
                code, name = KNOWN[cur]
                ok = code in mem
                known_detail[sid][cur] = ok
                if ok:
                    st["known_ok"] += 1

    # score: prioritize known + hit_anchor + strict, penalize fat n
    lines = [
        "# 定锚策略对比（抓龙头 + 胜率）",
        "",
        f"节点 **{len(nodes)}**；评估窗 T+1~10 自然高标。",
        "",
        "**指标**",
        "- `hit`：选出集合与后续自然高标有交集（覆盖）",
        "- `hit_anchor`：锚点本人成为后续自然高标（更像胜率）",
        "- `avg_n`：平均人数",
        "- `prec≈hit/avg_n`：命中摊薄（层越肥越亏）",
        "- `strict`：n≤3 且 hit",
        "- `sole_win`：n=1 且 hit",
        "- `known`：四案 神剑12-24 / 津药04-01 / 华远04-10 / 立新07-20",
        "",
        "| 策略 | hit | hit锚 | avg_n | prec≈ | strict | sole | known4 | 综合分* |",
        "|------|-----|-------|-------|-------|--------|------|--------|---------|",
    ]

    rows_score = []
    for sid, name, _ in STRATEGIES:
        st = stats[sid]
        n = st["n"] or 1
        hit_r = st["hit"] / n
        ha_r = st["hit_anchor"] / n
        avg_n = st["sum_n"] / max(n - st["empty"], 1)
        prec = hit_r / avg_n if avg_n else 0
        strict_r = st["strict"] / n
        sole_r = st["sole_win"] / n
        known_r = st["known_ok"] / len(KNOWN)
        # 综合：覆盖 + 2*锚点胜率 + 1.5*窄胜 + 3*known - 0.03*avg_n
        score = (
            100 * hit_r
            + 200 * ha_r
            + 150 * strict_r
            + 80 * sole_r
            + 300 * known_r
            - 3 * avg_n
        )
        rows_score.append((score, sid, name, st, hit_r, ha_r, avg_n, prec, strict_r, sole_r, known_r))

    rows_score.sort(key=lambda x: -x[0])
    for score, sid, name, st, hit_r, ha_r, avg_n, prec, strict_r, sole_r, known_r in rows_score:
        lines.append(
            f"| **{sid}** {name} | {st['hit']}/{st['n']}={hit_r:.0%} | "
            f"{st['hit_anchor']}/{st['n']}={ha_r:.0%} | {avg_n:.1f} | {prec:.3f} | "
            f"{st['strict']}({strict_r:.0%}) | {st['sole_win']}({sole_r:.0%}) | "
            f"{st['known_ok']}/4 | {score:.0f} |"
        )

    lines.append("")
    lines.append("\\*综合分 = 100·hit + 200·hit锚 + 150·strict + 80·sole + 300·known4 − 3·avg_n（可调权重）")
    lines.append("")
    lines.append("## 四案明细（是否点中真主升）")
    lines.append("")
    header = "| 策略 | " + " | ".join(KNOWN.keys()) + " |"
    lines.append(header)
    lines.append("|------|" + "|".join(["------"] * len(KNOWN)) + "|")
    for score, sid, name, st, *_ in rows_score:
        cells = []
        for d in KNOWN:
            ok = known_detail[sid].get(d)
            cells.append("✅" if ok else "❌")
        lines.append(f"| {sid} | " + " | ".join(cells) + " |")

    lines.append("")
    lines.append("## 简读")
    best = rows_score[0]
    best_known = max(rows_score, key=lambda x: x[3]["known_ok"])
    best_anchor = max(rows_score, key=lambda x: x[3]["hit_anchor"] / max(x[3]["n"], 1))
    best_prec = max(rows_score, key=lambda x: x[7])  # prec
    lines.append(f"- 综合分最高：`{best[1]}`（{best[2]}）")
    lines.append(f"- 四案全中最多：`{best_known[1]}` = {best_known[3]['known_ok']}/4")
    lines.append(f"- 锚点本人胜率最高：`{best_anchor[1]}`")
    lines.append(f"- prec≈ 最高：`{best_prec[1]}`")
    lines.append(f"- `union` 只做覆盖上界，不当交易规则。")
    lines.append("")

    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
