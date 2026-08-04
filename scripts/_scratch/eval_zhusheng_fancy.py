# -*- coding: utf-8 -*-
"""复盘静态认主升 · 第二轮花活 5 套（缩量/放量/晋级/综合分/投票）。

与 eval_zhusheng_strategies 同一 GT：
  strength = 1000*自然最高天数 + 10*未来最高板 + T+1连板
指标：
  hit = 选对 GT（抓主升）
  wrong = 选错（点错率，不是炸板）
  abstain = 弃权
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

OUT = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "kaipanla"
    / "ladder_daily"
    / "zhusheng_fancy_race.md"
)


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
        mem = lad.get("members") or set()
        ranks, fb, n_th = theme_rank_map(pools[cur])
        prev_map = pools_m[prev]
        cands = []
        raw = []
        for s in pools[cur]:
            if s["code"] not in mem:
                continue
            if bt.is_gonggao(s, cur) or not bt.is_natural(s, cur):
                continue
            code = s["code"]
            b0 = int(s.get("boards") or 0)
            amt = bt.amount_yi(s) or 0.0
            sp = prev_map.get(code)
            prev_amt = bt.amount_yi(sp) if sp else None
            prev_b = int(sp.get("boards") or 0) if sp else None
            # 相对昨日量：有昨日则 amt/prev_amt；无昨日（新晋）= None → 用 1.0 中性或标 new
            if prev_amt and prev_amt > 0:
                vol_ratio = amt / prev_amt
            else:
                vol_ratio = None  # 新票/无昨
            promoted = prev_b is not None and b0 == prev_b + 1
            th = (s.get("theme") or "").strip() or "（无）"
            tr = s.get("turnover_rate")
            try:
                tr = float(tr) if tr is not None else None
            except (TypeError, ValueError):
                tr = None
            st, max_b, nat_d, cont1 = future_strength(
                code, b0, days, pools, pools_m, i
            )
            item = {
                "code": code,
                "name": s.get("name"),
                "boards": b0,
                "theme": th,
                "rank": ranks.get(th, n_th + 1),
                "fb": fb.get(th, 0),
                "yizi": bt.is_yizi(s),
                "amt": amt,
                "seal_sec": first_seal_sec(s),
                "is_anchor": code == (lad.get("anchor") or {}).get("code"),
                "vol_ratio": vol_ratio,
                "is_new": prev_amt is None,
                "promoted": promoted,
                "turnover": tr,
                "strength": st,
                "fut_max_b": max_b,
                "fut_nat_days": nat_d,
            }
            raw.append(item)
        if not raw:
            continue
        max_amt = max(x["amt"] for x in raw) or 1e-6
        for x in raw:
            x["amt_share"] = x["amt"] / max_amt
            x["shrink"] = (
                x["vol_ratio"] is not None and x["vol_ratio"] < 0.85
            )
            x["expand"] = (
                x["vol_ratio"] is not None and x["vol_ratio"] > 1.25
            )
            # 缩量分：一字缩量钉好；换手缩量差
            if x["yizi"] and x["shrink"]:
                x["ideal_pin"] = True
            else:
                x["ideal_pin"] = False
            if (not x["yizi"]) and (x["expand"] or x["is_new"] or x["amt"] >= 8):
                x["ideal_space"] = True
            else:
                x["ideal_space"] = False

        best = max(raw, key=lambda x: x["strength"])
        has_gt = best["fut_nat_days"] > 0 or best["fut_max_b"] >= max(
            best["boards"] + 1, 3
        )
        if best["strength"] < 30 and best["fut_nat_days"] == 0:
            has_gt = False
        gt = None
        if has_gt:
            tops = [x for x in raw if x["strength"] == best["strength"]]
            gt = max(tops, key=lambda x: x["amt"])

        nodes.append(
            {
                "T": cur,
                "dead_h": dead_h,
                "height": lad.get("height"),
                "anchor_type": lad.get("anchor_type"),
                "cands": raw,
                "gt": gt,
            }
        )
    return nodes


# ---- F~J fancy picks ----

def pick_F_volume_structure(cands, node):
    """缩量一字钉 + 放量/大额换手空间；否则综合。"""
    yizi = [c for c in cands if c["yizi"]]
    space = [c for c in cands if not c["yizi"]]
    pins = [c for c in yizi if c["ideal_pin"] or c["amt"] < 2]
    spaces = [
        c
        for c in space
        if c["ideal_space"] or c["amt"] >= 5
    ]
    if pins and spaces:
        # 空间：优先放量，再额，再 rank
        return max(
            spaces,
            key=lambda x: (
                1 if x["expand"] else 0,
                x["amt"],
                -x["rank"],
                -x["seal_sec"],
            ),
        )
    if spaces:
        return max(spaces, key=lambda x: (x["amt"], -x["rank"]))
    if yizi:
        # 有发酵的一字
        hot_y = [c for c in yizi if c["rank"] <= 5]
        pool = hot_y if hot_y else yizi
        return max(pool, key=lambda x: (-x["rank"], x["amt"]))
    return max(cands, key=lambda x: x["amt"])


def pick_G_promote_expand(cands, node):
    """晋级放量优先；新晋大额；缩量换手降权。"""
    def score(c):
        s = 0.0
        s += c["amt"]  # 基础额
        if c["promoted"] and c["expand"]:
            s += 50
        if c["promoted"]:
            s += 15
        if c["expand"]:
            s += 20
        if c["is_new"] and c["amt"] >= 5:
            s += 25
        if c["yizi"] and c["shrink"]:
            s -= 10  # 钉高减分，不当主升
        if (not c["yizi"]) and c["shrink"] and c["amt"] < 8:
            s -= 30  # 缩量弱换手
        if c["rank"] <= 3:
            s += 12
        if c["rank"] >= 11:
            s -= 15
        if c["seal_sec"] <= 600:
            s += 8
        if c["is_anchor"] and c["yizi"]:
            s -= 5
        return s

    return max(cands, key=score)


def pick_H_composite_weird(cands, node):
    """综合花活分：相对死绝、额占比、首封、晋级、发酵。"""
    H = node["dead_h"] or 0

    def score(c):
        s = 0.0
        # 相对死绝：略低于断高更好（深切空间），同高也行
        rel = c["boards"] - H
        if rel == -1:
            s += 15
        elif rel <= -2:
            s += 20
        elif rel == 0:
            s += 8
        s += 40 * c["amt_share"]
        s += max(0, 25 - c["rank"] * 2)  # rank1=23
        if c["seal_sec"] <= 0:
            s += 15
        elif c["seal_sec"] <= 600:
            s += 10
        elif c["seal_sec"] > 5400:
            s -= 10
        if c["promoted"]:
            s += 10
        if c["expand"]:
            s += 12
        if c["yizi"] and c["amt"] < 2:
            s -= 18  # 薄一字钉
        if not c["yizi"] and c["amt"] >= 5:
            s += 10
        if c["is_anchor"] and not c["yizi"]:
            s += 8
        return s

    return max(cands, key=score)


def pick_I_precision_fancy(cands, node):
    """高置信：过滤后只剩清晰龙才选。"""
    # 过滤冷门弱结构
    pool = []
    for c in cands:
        if c["rank"] >= 15 and c["amt"] < 8:
            continue
        if c["yizi"] and c["rank"] >= 8 and c["amt"] < 3:
            continue
        # 量能或发酵至少一项突出
        hot = c["rank"] <= 3
        fat = c["amt"] >= 8 or c["expand"] or (c["is_new"] and c["amt"] >= 5)
        early = c["seal_sec"] <= 600
        if not (hot or fat or (early and c["amt"] >= 5)):
            continue
        pool.append(c)
    if not pool:
        return None
    yizi = [c for c in pool if c["yizi"]]
    space = [c for c in pool if not c["yizi"]]
    if yizi and space:
        sp = [c for c in space if c["amt"] >= 5]
        if sp:
            top = max(sp, key=lambda x: x["amt"])
            # 需要相对一字有优势
            if top["amt"] >= 3 or top["rank"] <= 5:
                return top
    if len(space) == 1:
        return space[0]
    if space:
        return max(space, key=lambda x: (x["amt"], -x["rank"], -x["seal_sec"]))
    hot_y = [c for c in yizi if c["rank"] <= 3]
    if len(hot_y) == 1:
        return hot_y[0]
    if len(pool) == 1:
        return pool[0]
    return None  # 不硬选


def pick_J_vote(cands, node):
    """多规则投票，并列空间优先于一字。"""
    # 各规则提名
    votes = defaultdict(int)

    # rule1 额最大
    a = max(cands, key=lambda x: x["amt"])
    votes[a["code"]] += 1
    # rule2 最早首封
    e = min(cands, key=lambda x: x["seal_sec"])
    votes[e["code"]] += 1
    # rule3 发酵最好再额
    h = min(cands, key=lambda x: (x["rank"], -x["amt"]))
    votes[h["code"]] += 1
    # rule4 放量/新晋大额
    expanders = [c for c in cands if c["expand"] or (c["is_new"] and c["amt"] >= 5)]
    if expanders:
        x = max(expanders, key=lambda z: z["amt"])
        votes[x["code"]] += 1
    # rule5 非一字最大额
    space = [c for c in cands if not c["yizi"]]
    if space:
        s = max(space, key=lambda z: z["amt"])
        votes[s["code"]] += 1
    # rule6 锚点（非公告已滤）
    anchors = [c for c in cands if c["is_anchor"]]
    if anchors:
        votes[anchors[0]["code"]] += 1

    if not votes:
        return max(cands, key=lambda x: x["amt"])
    max_v = max(votes.values())
    leaders = [c for c in cands if votes[c["code"]] == max_v]
    if len(leaders) == 1:
        return leaders[0]
    # 并列：空间优先
    sp = [c for c in leaders if not c["yizi"]]
    if sp:
        return max(sp, key=lambda x: x["amt"])
    # 仍并列弃权？用户要抓主升，投票并列取额
    return max(leaders, key=lambda x: x["amt"])


# 上一轮冠军对照
def pick_D_classic(cands, node):
    yizi = [c for c in cands if c["yizi"]]
    space = [c for c in cands if (not c["yizi"]) and c["amt"] >= 5]
    if yizi and space:
        space2 = [c for c in space if c["rank"] <= 15]
        pool = space2 if space2 else space
        return max(pool, key=lambda x: (x["amt"], -x["rank"], -x["seal_sec"]))
    if yizi and not space:
        return min(yizi, key=lambda x: (x["seal_sec"], -x["amt"]))
    return max(cands, key=lambda x: (x["amt"], -x["seal_sec"]))


STRATS = [
    ("D0_classic_hybrid", "上轮冠军:一字钉+大额空间", pick_D_classic),
    ("F_vol_structure", "缩量钉+放量/大额空间", pick_F_volume_structure),
    ("G_promote_expand", "晋级放量/新晋大额打分", pick_G_promote_expand),
    ("H_composite_weird", "相对死绝+额占比+首封综合", pick_H_composite_weird),
    ("I_precision_fancy", "过滤后高置信才选", pick_I_precision_fancy),
    ("J_vote_ensemble", "多规则投票(空间破并列)", pick_J_vote),
]


def main():
    nodes = build_nodes()
    n_gt = sum(1 for n in nodes if n["gt"])
    results = {}
    for sid, name, fn in STRATS:
        hit = wrong = abstain = 0
        for node in nodes:
            gt = node["gt"]
            if gt is None:
                continue
            pick = fn(node["cands"], node)
            if pick is None:
                abstain += 1
            elif pick["code"] == gt["code"]:
                hit += 1
            else:
                wrong += 1
        L = hit + wrong + abstain
        results[sid] = {
            "name": name,
            "hit": hit,
            "wrong": wrong,
            "abstain": abstain,
            "labeled": L,
            "hit_rate": hit / L if L else 0,
            "wrong_rate": wrong / L if L else 0,
            "precision": hit / (hit + wrong) if (hit + wrong) else 0,
        }

    human = {
        "2025-10-30": "合富中国",
        "2025-11-10": "孚日股份",
        "2025-11-21": "梦天家居",
        "2025-12-04": "安记食品",
        "2026-03-19": "华电辽能",
    }

    lines = [
        "# 复盘认主升 · 第二轮花活赛马（缩量/放量/投票等）",
        "",
        f"节点 {len(nodes)}，有 GT **{n_gt}** 天。",
        "",
        "**点对率 hit** = 选中事后主升（不是炸板）。",
        "**点错率 wrong** = 选了但选错。",
        "",
        "## 总榜",
        "",
        "| 策略 | hit | wrong | abstain | 点对率 | 点错率 | precision |",
        "|------|-----|-------|---------|--------|--------|-----------|",
    ]
    ranked = sorted(
        results.items(),
        key=lambda x: (-x[1]["hit"], x[1]["wrong"], -x[1]["precision"]),
    )
    for sid, r in ranked:
        L = r["labeled"] or 1
        lines.append(
            f"| **{sid}** {r['name']} | {r['hit']} | {r['wrong']} | {r['abstain']} | "
            f"**{r['hit']/L:.1%}** | {r['wrong']/L:.1%} | {r['precision']:.1%} |"
        )

    lines += ["", "## 人工案例", ""]
    header = "| T | 用户 | " + " | ".join(s[0].split("_")[0] for s in STRATS) + " |"
    lines.append(header)
    lines.append("|---|" + "|".join(["---"] * (1 + len(STRATS))) + "|")
    for T, uname in human.items():
        node = next((n for n in nodes if n["T"] == T), None)
        if not node:
            continue
        cells = []
        for sid, _, fn in STRATS:
            p = fn(node["cands"], node)
            if p is None:
                cells.append("∅")
            elif p["name"] == uname:
                cells.append("✓")
            else:
                cells.append("×" + p["name"][:4])
        lines.append(f"| {T} | {uname} | " + " | ".join(cells) + " |")

    best = ranked[0]
    lines += [
        "",
        "## 结论",
        "",
        f"- **点对最多**：`{best[0]}` hit={best[1]['hit']} ({best[1]['hit']/max(best[1]['labeled'],1):.1%})",
        f"- 相对上轮冠军 D0：见榜首是否超过 classic hybrid",
        "- 花活特征：相对昨日缩量/放量、是否晋级、新晋、额占比、相对死绝高、多规则投票",
        "",
        f"明细逻辑见 `eval_zhusheng_fancy.py`",
    ]

    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
