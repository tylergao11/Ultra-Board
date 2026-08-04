# -*- coding: utf-8 -*-
"""节点日 T 事前连板打分（不用次日开盘）。

特征 → 加权得分 → 分层连板率。
权重：先给初值，再网格/坐标下降调参，目标=最大化
  (高分档连板率 - 低分档连板率) 且 高分档样本量够。

样本：节点日纯往下锚层；同梯队同 theme 留 T 日额最大（竞争龙头）。
"""
from __future__ import annotations

import csv
import itertools
import json
import random
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

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
OUT_CSV = OUT_DIR / "exante_cont_scores.csv"
OUT_MD = OUT_DIR / "exante_cont_scores.md"
OUT_W = OUT_DIR / "exante_cont_weights.json"


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
        return None
    try:
        t = datetime.fromtimestamp(int(ts))
        return (t.hour - 9) * 3600 + (t.minute - 30) * 60 + t.second
    except Exception:
        return None


def build_dataset():
    days, pools, pools_m = bt.load_days()
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
        layer = [s for s in pools[cur] if s["code"] in mem]
        layer_sorted = sorted(layer, key=lambda s: -(bt.amount_yi(s) or 0))
        amt_rank = {s["code"]: j + 1 for j, s in enumerate(layer_sorted)}

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
            cont = 1 if (s1 and int(s1.get("boards") or 0) == b + 1) else 0
            rnk = ranks.get(th, n_th + 1)
            peers_tier = [
                x
                for x in layer
                if ((x.get("theme") or "").strip() or "（无）") == th
            ]
            peers_theme = theme_ge2.get(th, [])
            seals = []
            for x in peers_theme:
                sec = first_seal_sec(x)
                if sec is not None:
                    seals.append((sec, x["code"]))
            seals.sort()
            seal_rank = next(
                (j for j, (_, c) in enumerate(seals, 1) if c == code), None
            )
            my_sec = first_seal_sec(s)
            rows.append(
                {
                    "T": cur,
                    "T1": t1,
                    "code": code,
                    "name": s.get("name") or "",
                    "boards": b,
                    "theme": th,
                    "rank": rnk,
                    "fb": fb.get(th, 0),
                    "yizi": 1 if bt.is_yizi(s) else 0,
                    "amt": bt.amount_yi(s),
                    "amt_rank_layer": amt_rank.get(code) or 99,
                    "n_same_theme_tier": len(peers_tier),
                    "n_theme_ge2": len(peers_theme),
                    "first_seal_sec": my_sec,
                    "seal_rank_theme": seal_rank or 99,
                    "anchor_type": lad.get("anchor_type") or "",
                    "down_h": lad.get("height"),
                    "dead_h": dead_h,
                    "is_anchor": 1
                    if code == (lad.get("anchor") or {}).get("code")
                    else 0,
                    "cont": cont,
                }
            )

    # 同梯队同 theme：T 日额最大
    groups = defaultdict(list)
    for r in rows:
        groups[(r["T"], r["boards"], r["theme"])].append(r)
    out = []
    for items in groups.values():
        items = sorted(items, key=lambda x: (-(x["amt"] or 0), x["code"]))
        out.append(items[0])
    return out


# ---------- 特征分项（0~满分，再乘权重）----------
# 每项返回 (feature_name, points 0~1 或 0~max_raw)


def feat_rank(r):
    k = r["rank"]
    if k == 1:
        return 1.0
    if k <= 3:
        return 0.85
    if k <= 6:
        return 0.45
    if k <= 10:
        return 0.25
    return 0.1


def feat_seal_time(r):
    sec = r["first_seal_sec"]
    if sec is None:
        return 0.2
    if sec <= -200:
        return 1.0  # 竞价一字级
    if sec <= 0:
        return 0.85
    if sec <= 600:
        return 0.55
    if sec <= 1800:
        return 0.35
    if sec <= 5400:
        return 0.2
    return 0.1


def feat_seal_rank(r):
    k = r["seal_rank_theme"]
    if k == 1:
        return 1.0
    if k == 2:
        return 0.55
    if k == 3:
        return 0.35
    return 0.15


def feat_is_anchor(r):
    return 1.0 if r["is_anchor"] else 0.25


def feat_yizi(r):
    return 1.0 if r["yizi"] else 0.35


def feat_down_h(r):
    h = r["down_h"] or 0
    if h == 3:
        return 1.0
    if h == 4:
        return 0.75
    if h >= 5:
        return 0.55
    if h == 2:
        return 0.35
    return 0.3


def feat_anchor_type(r):
    t = r["anchor_type"]
    if t == "anchor_nat_yizi":
        return 0.9
    if t == "anchor_reorg":
        return 0.85
    if t == "anchor_two":
        return 0.25
    return 0.4


def feat_theme_compete(r):
    # 同梯队同 theme 独苗更好
    n = r["n_same_theme_tier"]
    if n <= 1:
        return 1.0
    if n == 2:
        return 0.35
    return 0.2


def feat_amt_rank(r):
    k = r["amt_rank_layer"]
    if k == 1:
        return 0.7  # 数据里第1略怪，给中等
    if k == 2:
        return 1.0
    if k == 3:
        return 0.9
    return 0.4


FEATURE_FUNCS = {
    "rank": feat_rank,  # 发酵排名
    "seal_time": feat_seal_time,  # 首封早晚
    "seal_rank": feat_seal_rank,  # 同板块首封第几
    "is_anchor": feat_is_anchor,  # 是否锚点
    "yizi": feat_yizi,  # 一字
    "down_h": feat_down_h,  # 梯队判定高度
    "anchor_type": feat_anchor_type,  # 一字/重组/二板
    "theme_compete": feat_theme_compete,  # 同层同属性竞争
    "amt_rank": feat_amt_rank,  # 层内额排名
}

# 初值权重（凭区分度手开）
INIT_WEIGHTS = {
    "rank": 2.0,
    "seal_time": 3.0,
    "seal_rank": 2.5,
    "is_anchor": 2.5,
    "yizi": 2.0,
    "down_h": 1.5,
    "anchor_type": 1.5,
    "theme_compete": 1.5,
    "amt_rank": 1.0,
}


def max_raw_score(weights) -> float:
    """各特征取满分 1.0 时的加权和 = 权重之和（满分映射到 100）。"""
    return sum(float(weights.get(k, 0.0) or 0.0) for k in FEATURE_FUNCS) or 1.0


def score_one(r, weights):
    """返回 (score_100, detail_pts_100)。满分 100。"""
    raw_total = 0.0
    raw_detail = {}
    for k, fn in FEATURE_FUNCS.items():
        v = fn(r)
        w = float(weights.get(k, 0.0) or 0.0)
        raw_detail[k] = v * w
        raw_total += v * w
    cap = max_raw_score(weights)
    scale = 100.0 / cap
    total = raw_total * scale
    detail = {k: round(v * scale, 2) for k, v in raw_detail.items()}
    return total, detail


def bin_rates(rows, weights, edges=None):
    """返回 [(lab, n, rate, mean_score)]"""
    scored = []
    for r in rows:
        sc, _ = score_one(r, weights)
        scored.append((sc, r["cont"]))
    if not scored:
        return []
    scores = [s for s, _ in scored]
    if edges is None:
        # 四分位
        ss = sorted(scores)
        n = len(ss)
        edges = [
            ss[0] - 1e-6,
            ss[max(0, n // 4 - 1)],
            ss[max(0, n // 2 - 1)],
            ss[max(0, 3 * n // 4 - 1)],
            ss[-1] + 1e-6,
        ]
    bins = defaultdict(list)
    labs = ["Q1低", "Q2", "Q3", "Q4高"]
    for sc, c in scored:
        for i in range(4):
            if edges[i] < sc <= edges[i + 1]:
                bins[labs[i]].append((sc, c))
                break
    out = []
    for lab in labs:
        sub = bins.get(lab) or []
        if not sub:
            out.append((lab, 0, 0.0, 0.0))
            continue
        rate = sum(c for _, c in sub) / len(sub)
        ms = sum(s for s, _ in sub) / len(sub)
        out.append((lab, len(sub), rate, ms))
    return out, scored


def objective(rows, weights, min_high_n=25):
    """最大化 Q4连板率 - Q1连板率，Q4样本太少则罚。"""
    bins, scored = bin_rates(rows, weights)
    by = {lab: (n, rate) for lab, n, rate, _ in bins}
    q1 = by.get("Q1低", (0, 0.0))
    q4 = by.get("Q4高", (0, 0.0))
    if q4[0] < min_high_n or q1[0] < min_high_n:
        # 放宽
        pass
    spread = q4[1] - q1[1]
    # 附加：分数与 cont 的点二列相关近似
    if not scored:
        return -1.0
    mean_s = sum(s for s, _ in scored) / len(scored)
    mean_c = sum(c for _, c in scored) / len(scored)
    num = sum((s - mean_s) * (c - mean_c) for s, c in scored)
    den_s = sum((s - mean_s) ** 2 for s, _ in scored) ** 0.5
    den_c = sum((c - mean_c) ** 2 for _, c in scored) ** 0.5
    corr = num / (den_s * den_c + 1e-9)
    # 高分档绝对连板率
    return spread + 0.15 * corr + 0.1 * q4[1]


def coordinate_descent(rows, init_w, rounds=8, grid=None):
    if grid is None:
        grid = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    w = dict(init_w)
    best = objective(rows, w)
    history = [("init", dict(w), best)]
    keys = list(FEATURE_FUNCS.keys())
    for rd in range(rounds):
        improved = False
        for k in keys:
            local_best = best
            local_w = w[k]
            for g in grid:
                w[k] = g
                sc = objective(rows, w)
                if sc > local_best + 1e-6:
                    local_best = sc
                    local_w = g
                    improved = True
            w[k] = local_w
            best = local_best
        history.append((f"round{rd+1}", dict(w), best))
        if not improved:
            break
    return w, best, history


def random_search(rows, init_w, n_try=400, seed=42):
    rnd = random.Random(seed)
    grid = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
    best_w, best_sc = dict(init_w), objective(rows, init_w)
    keys = list(FEATURE_FUNCS.keys())
    for _ in range(n_try):
        w = {k: rnd.choice(grid) for k in keys}
        # 至少保留 seal_time 或 rank 有权重
        if w["seal_time"] + w["rank"] + w["is_anchor"] < 1.0:
            continue
        sc = objective(rows, w)
        if sc > best_sc:
            best_sc, best_w = sc, w
    return best_w, best_sc


def main():
    data = build_dataset()
    print(f"样本 n={len(data)} 基线连板={sum(r['cont'] for r in data)/len(data):.1%}")

    # 1) 初值
    w0 = dict(INIT_WEIGHTS)
    sc0 = objective(data, w0)
    bins0, _ = bin_rates(data, w0)
    print("初值 obj", round(sc0, 4), "bins", bins0)

    # 2) 随机搜索
    w_rs, sc_rs = random_search(data, w0, n_try=600)
    print("随机搜索 obj", round(sc_rs, 4), w_rs)

    # 3) 坐标下降（从更好的起点）
    start = w_rs if sc_rs >= sc0 else w0
    w_cd, sc_cd, hist = coordinate_descent(data, start, rounds=10)
    print("坐标下降 obj", round(sc_cd, 4), w_cd)

    # 取最优
    candidates = [(sc0, w0, "init"), (sc_rs, w_rs, "random"), (sc_cd, w_cd, "coord")]
    best_sc, best_w, best_name = max(candidates, key=lambda x: x[0])
    print("选用", best_name, best_sc)

    # 细分层
    scores = []
    for r in data:
        sc, det = score_one(r, best_w)
        row = dict(r)
        row["score"] = round(sc, 4)
        for k, v in det.items():
            row[f"pts_{k}"] = v
        scores.append(row)

    scores.sort(key=lambda x: -x["score"])
    # 固定分箱：按分数排序五等分
    n = len(scores)
    for i, r in enumerate(scores):
        r["score_rank"] = i + 1
        r["quintile"] = min(5, i * 5 // n + 1)  # 1=最高分

    # 五档连板
    cap = max_raw_score(best_w)
    lines = [
        "# 事前连板打分（满分 100）",
        "",
        f"样本：**{n}**（节点日纯往下；同梯队同 theme 取 T 日额最大）",
        f"基线连板率：**{sum(r['cont'] for r in scores)/n:.1%}**",
        f"权重来源：**{best_name}**（obj={best_sc:.4f}）",
        "",
        f"**计分**：各项特征 0～1 × 权重，再 × `100 / Σ权重` → **满分 100**。",
        f"当前 Σ权重 = **{cap:.1f}**。",
        "",
        "## 最终权重与满分贡献",
        "",
        "| 特征 | 含义 | 权重 | 满分贡献分 |",
        "|------|------|------|------------|",
    ]
    meaning = {
        "rank": "发酵排名(1最热)",
        "seal_time": "首封早晚",
        "seal_rank": "同板块首封第几",
        "is_anchor": "是否往下锚点本人",
        "yizi": "是否一字",
        "down_h": "往下锚判定高度",
        "anchor_type": "锚类型一字/重组/二板",
        "theme_compete": "同梯队同属性是否独苗",
        "amt_rank": "锚层内额排名",
    }
    for k, w in sorted(best_w.items(), key=lambda x: -x[1]):
        pts = 100.0 * float(w) / cap
        lines.append(
            f"| `{k}` | {meaning.get(k, k)} | **{w}** | **{pts:.1f}** |"
        )

    lines += [
        "",
        "## 五档（按分数从高到低等分）",
        "",
        "| 档 | 分数(100制) | n | 连板率 | vs基线 |",
        "|----|-------------|---|--------|--------|",
    ]
    base = sum(r["cont"] for r in scores) / n
    for q in range(1, 6):
        sub = [r for r in scores if r["quintile"] == q]
        if not sub:
            continue
        rate = sum(r["cont"] for r in sub) / len(sub)
        mn, mx = min(r["score"] for r in sub), max(r["score"] for r in sub)
        lab = {1: "Q1最高分", 2: "Q2", 3: "Q3", 4: "Q4", 5: "Q5最低分"}[q]
        lines.append(
            f"| {lab} | {mn:.1f}~{mx:.1f} | {len(sub)} | **{rate:.1%}** | {rate-base:+.1%} |"
        )

    # 绝对分阈值 100 制
    lines += ["", "## 绝对分阈值（满分100）", ""]
    for thr in [40, 50, 60, 70, 75, 80, 85, 90]:
        sub = [r for r in scores if r["score"] >= thr]
        if len(sub) < 8:
            continue
        rate = sum(r["cont"] for r in sub) / len(sub)
        lines.append(f"- score ≥ **{thr}**：n={len(sub)} 连板率 **{rate:.1%}**")

    lines += ["", "## Top15 高分", ""]
    lines.append("| score | T | 名 | theme | rank | 板块封序 | 锚 | 一字 | 连 |")
    lines.append("|-------|---|-----|-------|------|----------|----|------|----|")
    for r in scores[:15]:
        lines.append(
            f"| {r['score']:.1f} | {r['T']} | {r['name']} | {r['theme']} | "
            f"{r['rank']} | {r['seal_rank_theme']} | "
            f"{r['is_anchor']} | {r['yizi']} | {r['cont']} |"
        )

    lines += ["", "## 三坑货得分", ""]
    for r in scores:
        if r["name"] in ("澄星股份", "神州高铁", "华升股份") and r["T"] in (
            "2025-10-14",
            "2026-03-31",
            "2026-04-20",
        ):
            lines.append(
                f"- {r['T']} {r['name']}: score=**{r['score']:.1f}/100** "
                f"Q{r['quintile']} cont={r['cont']} "
                f"(rank={r['rank']} seal_rank={r['seal_rank_theme']} "
                f"anchor={r['is_anchor']} yizi={r['yizi']})"
            )

    lines += [
        "",
        "## 初值 vs 调后",
        "",
        f"- 初值 obj={sc0:.4f}",
        f"- 随机搜索 obj={sc_rs:.4f}",
        f"- 坐标下降 obj={sc_cd:.4f}",
        f"- **采用 {best_name}**",
        "",
        f"明细：`{OUT_CSV.relative_to(ROOT)}`",
        f"权重：`{OUT_W.relative_to(ROOT)}`",
        "",
        "说明：满分100只表事前连板相对强弱；不含次日开盘；T+1 仍要叠水下/回封。",
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # round score for csv
    for r in scores:
        r["score"] = round(float(r["score"]), 2)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(scores[0].keys()))
        w.writeheader()
        w.writerows(scores)
    OUT_W.write_text(
        json.dumps(
            {
                "source": best_name,
                "objective": best_sc,
                "scale": "100",
                "sum_weights": cap,
                "weights": best_w,
                "max_points_per_feature": {
                    k: round(100.0 * float(best_w.get(k, 0)) / cap, 2)
                    for k in FEATURE_FUNCS
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
