# -*- coding: utf-8 -*-
"""复盘静态认主升：5 套流程回测。

目标：节点日往下锚层内选出 1 只真主升（或弃权）。
评价（有 GT 的节点）：
  - 命中率 hit = pick==GT
  - 失败率 fail = pick 且 pick!=GT
  - 弃权率 abstain
  - 覆盖 recall = hit / 有GT天数
  - 精确 precision = hit / (hit+fail)

GT：层内自然票在 T+1~T+10 的「未来强度」最大者
  strength = 1000*曾进自然最高天数 + 10*期间最高板 + 是否T+1连板
  仅当 strength 明显（曾自然最高 或 最高板>=max(boards_T+1,3)）才标 GT。
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import importlib.util
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferment_open_seal_grid import theme_fb_counts

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

OUT = Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "ladder_daily" / "zhusheng_strategy_race.md"
OUT_JSON = OUT.with_suffix(".json")


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
    ts = s.get("first_limit_ts")
    if ts is None:
        return 10**9
    try:
        t = datetime.fromtimestamp(int(ts))
        return (t.hour - 9) * 3600 + (t.minute - 30) * 60 + t.second
    except Exception:
        return 10**9


def layer_candidates(pools, cur, lad) -> list:
    mem = lad.get("members") or set()
    out = []
    for s in pools[cur]:
        if s["code"] not in mem:
            continue
        if bt.is_gonggao(s, cur):
            continue
        if not bt.is_natural(s, cur):
            continue
        out.append(s)
    return out


def future_strength(code, b0, days, pools, pools_m, i0, horizon=10):
    max_b = b0
    nat_days = 0
    cont1 = False
    for j in range(i0 + 1, min(i0 + 1 + horizon, len(days))):
        d = days[j]
        s = pools_m[d].get(code)
        if not s:
            continue
        b = int(s.get("boards") or 0)
        max_b = max(max_b, b)
        if j == i0 + 1 and b == b0 + 1:
            cont1 = True
        mx, highs = bt.natural_max(pools[d], d)
        if mx > 0 and any(h["code"] == code for h in highs):
            nat_days += 1
    return nat_days * 1000 + max_b * 10 + (1 if cont1 else 0), max_b, nat_days, cont1


def build_nodes():
    days, pools, pools_m = bt.load_days()
    nodes = []
    for i in range(1, len(days) - 1):
        prev, cur = days[i - 1], days[i]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue
        lad = bt.pick_ladder(pools[cur], cur)
        cands = layer_candidates(pools, cur, lad)
        if not cands:
            continue
        ranks, fb, n_th = theme_rank_map(pools[cur])
        # enrich
        enriched = []
        for s in cands:
            th = (s.get("theme") or "").strip() or "（无）"
            code = s["code"]
            b0 = int(s.get("boards") or 0)
            st, max_b, nat_d, cont1 = future_strength(
                code, b0, days, pools, pools_m, i
            )
            enriched.append(
                {
                    "code": code,
                    "name": s.get("name"),
                    "boards": b0,
                    "theme": th,
                    "rank": ranks.get(th, n_th + 1),
                    "fb": fb.get(th, 0),
                    "yizi": bt.is_yizi(s),
                    "amt": bt.amount_yi(s) or 0.0,
                    "seal_sec": first_seal_sec(s),
                    "is_anchor": code == (lad.get("anchor") or {}).get("code"),
                    "strength": st,
                    "fut_max_b": max_b,
                    "fut_nat_days": nat_d,
                    "cont1": cont1,
                }
            )
        # GT
        best = max(enriched, key=lambda x: x["strength"])
        has_gt = best["fut_nat_days"] > 0 or best["fut_max_b"] >= max(
            best["boards"] + 1, 3
        )
        # 若全员 strength 很弱则无 GT
        if best["strength"] < 30 and best["fut_nat_days"] == 0:
            has_gt = False
        gt = best if has_gt else None
        # 同强度并列取额大
        if gt:
            tops = [x for x in enriched if x["strength"] == best["strength"]]
            gt = max(tops, key=lambda x: x["amt"])

        nodes.append(
            {
                "T": cur,
                "dead_h": dead_h,
                "height": lad.get("height"),
                "anchor_type": lad.get("anchor_type"),
                "cands": enriched,
                "gt": gt,
            }
        )
    return nodes


# ---------- 5 strategies ----------

def pick_A_max_amount(cands, node):
    """amount_king: 层内自然额最大"""
    if not cands:
        return None
    return max(cands, key=lambda x: (x["amt"], -x["seal_sec"]))


def pick_B_ferment_rank_then_amount(cands, node):
    """hot_rank_space: 发酵 rank<=3 里额最大；否则弃权或退回额最大偏保守→退回层内 rank 最好再额"""
    hot = [c for c in cands if c["rank"] <= 3]
    pool = hot if hot else cands
    # 优先非一字大额
    space = [c for c in pool if not c["yizi"] and c["amt"] >= 3]
    if space:
        return max(space, key=lambda x: (x["amt"], -x["rank"], -x["seal_sec"]))
    return max(pool, key=lambda x: (-x["rank"], x["amt"], -x["seal_sec"]))


def pick_C_early_seal_anchor_bias(cands, node):
    """early_seal_leader: 早封优先；并列锚点/额"""
    if not cands:
        return None
    return min(
        cands,
        key=lambda x: (
            x["seal_sec"],
            0 if x["is_anchor"] else 1,
            -x["amt"],
        ),
    )


def pick_D_yizi_pin_space_hybrid(cands, node):
    """yizi_pin_space_hybrid: 有一字+大额换手→换手；仅一字→一字；否则额最大"""
    yizi = [c for c in cands if c["yizi"]]
    space = [c for c in cands if (not c["yizi"]) and c["amt"] >= 5]
    if yizi and space:
        # 换手里取额最大且 rank 不太烂
        space2 = [c for c in space if c["rank"] <= 15]
        pool = space2 if space2 else space
        return max(pool, key=lambda x: (x["amt"], -x["rank"], -x["seal_sec"]))
    if len(yizi) == 1 and not space:
        return yizi[0]
    if yizi and not space:
        return min(yizi, key=lambda x: (x["seal_sec"], -x["amt"]))
    # 无一字
    nat_space = [c for c in cands if c["amt"] >= 3]
    pool = nat_space if nat_space else cands
    return max(pool, key=lambda x: (x["amt"], -x["seal_sec"]))


def pick_E_conservative(cands, node):
    """conservative_precision: 高置信才选，否则弃权"""
    if not cands:
        return None
    yizi = [c for c in cands if c["yizi"]]
    space = [c for c in cands if (not c["yizi"]) and c["amt"] >= 8]
    # 经典结构：一字+大额换手 → 换手且 rank<=6 或额碾压
    if yizi and space:
        top = max(space, key=lambda x: x["amt"])
        if top["rank"] <= 6 or top["amt"] >= 10:
            return top
        return None  # 结构像但不够强
    # 热门早封换手
    hot_early = [
        c
        for c in cands
        if (not c["yizi"])
        and c["rank"] <= 3
        and c["seal_sec"] <= 600
        and c["amt"] >= 5
    ]
    if len(hot_early) == 1:
        return hot_early[0]
    if len(hot_early) > 1:
        return max(hot_early, key=lambda x: x["amt"])
    # 单一字且是锚且 rank<=5
    if len(cands) == 1 and cands[0]["yizi"] and cands[0]["is_anchor"]:
        if cands[0]["rank"] <= 5:
            return cands[0]
        return None
    return None


STRATS = [
    ("A_amount_king", "层内额最大", pick_A_max_amount),
    ("B_hot_rank_space", "热发酵优先再大额换手", pick_B_ferment_rank_then_amount),
    ("C_early_seal", "最早首封(+锚/额)", pick_C_early_seal_anchor_bias),
    ("D_yizi_space_hybrid", "一字定高+大额换手取空间", pick_D_yizi_pin_space_hybrid),
    ("E_conservative", "高置信才选否则弃权", pick_E_conservative),
]


def eval_all(nodes):
    results = {}
    details = {sid: [] for sid, _, _ in STRATS}
    for sid, name, fn in STRATS:
        hit = fail = abstain = no_gt = 0
        for node in nodes:
            gt = node["gt"]
            pick = fn(node["cands"], node)
            if gt is None:
                no_gt += 1
                # 有 pick 算软失败？不计入主指标
                details[sid].append(
                    {"T": node["T"], "pick": pick["name"] if pick else None, "gt": None, "ok": None}
                )
                continue
            if pick is None:
                abstain += 1
                details[sid].append(
                    {"T": node["T"], "pick": None, "gt": gt["name"], "ok": False, "kind": "abstain"}
                )
                continue
            if pick["code"] == gt["code"]:
                hit += 1
                details[sid].append(
                    {"T": node["T"], "pick": pick["name"], "gt": gt["name"], "ok": True}
                )
            else:
                fail += 1
                details[sid].append(
                    {
                        "T": node["T"],
                        "pick": pick["name"],
                        "gt": gt["name"],
                        "ok": False,
                        "kind": "wrong",
                    }
                )
        labeled = hit + fail + abstain
        results[sid] = {
            "name": name,
            "hit": hit,
            "fail": fail,
            "abstain": abstain,
            "no_gt": no_gt,
            "labeled": labeled,
            "hit_rate": hit / labeled if labeled else 0,
            "fail_rate": fail / labeled if labeled else 0,
            "abstain_rate": abstain / labeled if labeled else 0,
            "precision": hit / (hit + fail) if (hit + fail) else 0,
            "recall_among_labeled": hit / labeled if labeled else 0,
        }
    return results, details


def main():
    nodes = build_nodes()
    n_gt = sum(1 for n in nodes if n["gt"])
    results, details = eval_all(nodes)

    # 已知人工案例核对
    human = {
        "2025-10-30": "合富中国",  # 用户认可
        "2025-11-10": "孚日股份",
        "2025-11-21": "梦天家居",
        "2025-12-04": "安记食品",
        "2026-03-19": "华电辽能",  # 与深华发结构，空间侧
    }

    lines = [
        "# 复盘静态认主升：5 套流程赛马",
        "",
        f"节点总数 **{len(nodes)}**；有 GT 标签 **{n_gt}** 天。",
        "",
        "**GT**：往下锚层自然票中，T+1~10「未来强度」最大"
        "（曾为自然最高天数优先，其次期间最高板，再次 T+1 连板）。",
        "",
        "**指标**（在有 GT 的节点上）",
        "- hit：选中 = GT",
        "- fail：选了但选错",
        "- abstain：弃权（未选）",
        "- precision = hit/(hit+fail)",
        "- 抓主升率 ≈ hit/有GT天数",
        "",
        "## 总榜",
        "",
        "| 策略 | hit | fail | abstain | 抓取率hit/GT | 失败率fail/GT | precision |",
        "|------|-----|------|---------|--------------|---------------|-----------|",
    ]

    ranked = sorted(
        results.items(),
        key=lambda x: (-x[1]["hit"], x[1]["fail"], -x[1]["precision"]),
    )
    for sid, r in ranked:
        L = r["labeled"] or 1
        lines.append(
            f"| **{sid}** {r['name']} | {r['hit']} | {r['fail']} | {r['abstain']} | "
            f"{r['hit']/L:.1%} | {r['fail']/L:.1%} | {r['precision']:.1%} |"
        )

    lines += ["", "## 策略一句话", ""]
    desc = {
        "A_amount_king": "层内成交额最大。",
        "B_hot_rank_space": "发酵 rank≤3 的换手大额优先，否则 rank 最好再比额。",
        "C_early_seal": "首封最早；并列锚点、额。",
        "D_yizi_space_hybrid": "有一字+≥5亿换手→取换手空间；否则一字或额最大。",
        "E_conservative": "仅经典结构或热门早封大额才选，否则弃权。",
    }
    for sid, _, _ in STRATS:
        lines.append(f"- `{sid}`：{desc[sid]}")

    lines += ["", "## 人工案例核对（用户教过的）", ""]
    lines.append("| T | 用户主升 | " + " | ".join(s[0] for s in STRATS) + " |")
    lines.append("|---|" + "|".join(["------"] * (1 + len(STRATS))) + "|")
    for T, uname in human.items():
        node = next((n for n in nodes if n["T"] == T), None)
        if not node:
            continue
        cells = []
        for sid, _, fn in STRATS:
            p = fn(node["cands"], node)
            mark = "—" if p is None else p["name"]
            ok = "✓" if p and p["name"] == uname else ("∅" if p is None else "×")
            cells.append(f"{ok}{mark}")
        lines.append(f"| {T} | {uname} | " + " | ".join(cells) + " |")

    # 谁 fail 最少且 hit 多
    best_hit = max(results.items(), key=lambda x: (x[1]["hit"], -x[1]["fail"]))
    best_prec = max(
        ((s, r) for s, r in results.items() if r["hit"] + r["fail"] >= 10),
        key=lambda x: (x[1]["precision"], x[1]["hit"]),
        default=(None, None),
    )
    lines += [
        "",
        "## 结论",
        "",
        f"- **抓主升最多**：`{best_hit[0]}` hit={best_hit[1]['hit']} fail={best_hit[1]['fail']}",
    ]
    if best_prec[0]:
        lines.append(
            f"- **失败率低/精确高**：`{best_prec[0]}` precision={best_prec[1]['precision']:.1%} "
            f"(hit={best_prec[1]['hit']} fail={best_prec[1]['fail']} abstain={best_prec[1]['abstain']})"
        )
    lines.append(
        "- 复盘目标是静态认主升；本赛马 **不含次日开盘**。"
    )

    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    OUT_JSON.write_text(
        json.dumps({"results": results, "n_nodes": len(nodes), "n_gt": n_gt}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
