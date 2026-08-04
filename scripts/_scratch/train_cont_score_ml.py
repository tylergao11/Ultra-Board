# -*- coding: utf-8 -*-
"""机器学习：事前特征 → 次日连板概率 → 满分100分。

流程：
1. 构造 T 日特征（无次日开盘）
2. 单因子筛选（训练集上 lift / AUC）
3. 时序切分 train / valid / test
4. 逻辑回归(L2) + 可选特征前向筛选
5. 概率 ×100 = 分数；输出分层连板率与系数

依赖：numpy, scikit-learn
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, log_loss, brier_score_loss
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferment_open_seal_grid import theme_fb_counts  # noqa: E402
import importlib.util

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
OUT_CSV = OUT_DIR / "ml_cont_scores.csv"
OUT_MD = OUT_DIR / "ml_cont_scores.md"
OUT_MODEL = OUT_DIR / "ml_cont_model.json"


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


def build_raw_rows():
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
                    "rank": ranks.get(th, n_th + 1),
                    "fb": fb.get(th, 0),
                    "n_themes": n_th,
                    "yizi": 1 if bt.is_yizi(s) else 0,
                    "amt": bt.amount_yi(s) or 0.0,
                    "amt_rank_layer": amt_rank.get(code) or 99,
                    "n_same_theme_tier": len(peers_tier),
                    "n_theme_ge2": len(peers_theme),
                    "first_seal_sec": my_sec if my_sec is not None else 99999,
                    "has_seal_time": 0 if my_sec is None else 1,
                    "seal_rank_theme": seal_rank or 99,
                    "anchor_type": lad.get("anchor_type") or "",
                    "down_h": lad.get("height") or 0,
                    "dead_h": dead_h or 0,
                    "is_anchor": 1
                    if code == (lad.get("anchor") or {}).get("code")
                    else 0,
                    "cont": cont,
                }
            )

    # 同梯队同 theme 额最大
    groups = defaultdict(list)
    for r in rows:
        groups[(r["T"], r["boards"], r["theme"])].append(r)
    out = []
    for items in groups.values():
        items = sorted(items, key=lambda x: (-x["amt"], x["code"]))
        out.append(items[0])
    out.sort(key=lambda r: r["T"])
    return out


def featurize(row: dict) -> dict[str, float]:
    """数值特征字典（全由 T 日可知）。"""
    sec = row["first_seal_sec"]
    # 早封分数：越小越好 → 映射
    if sec >= 99999:
        seal_early = 0.0
    else:
        # 09:25 = -300 → 1.0; 午后 → 0
        seal_early = float(np.clip(1.0 - (sec + 300) / 15000.0, 0.0, 1.0))

    at = row["anchor_type"]
    return {
        "rank": float(row["rank"]),
        "rank_inv": 1.0 / math.sqrt(float(row["rank"])),  # 越热越大
        "fb_log": math.log1p(float(row["fb"])),
        "yizi": float(row["yizi"]),
        "is_anchor": float(row["is_anchor"]),
        "amt_log": math.log1p(float(row["amt"])),
        "amt_rank": float(row["amt_rank_layer"]),
        "amt_rank_inv": 1.0 / float(row["amt_rank_layer"]),
        "n_same_theme_tier": float(row["n_same_theme_tier"]),
        "solo_theme_tier": 1.0 if row["n_same_theme_tier"] <= 1 else 0.0,
        "n_theme_ge2": float(row["n_theme_ge2"]),
        "seal_early": seal_early,
        "has_seal_time": float(row["has_seal_time"]),
        "seal_rank": float(row["seal_rank_theme"]),
        "seal_rank_inv": 1.0 / float(row["seal_rank_theme"]),
        "is_theme_first_seal": 1.0 if row["seal_rank_theme"] == 1 else 0.0,
        "down_h": float(row["down_h"]),
        "dead_h": float(row["dead_h"]),
        "boards": float(row["boards"]),
        "rel_dead": float(row["boards"] - (row["dead_h"] or 0)),
        "is_two_anchor": 1.0 if at == "anchor_two" else 0.0,
        "is_yizi_anchor_type": 1.0 if at == "anchor_nat_yizi" else 0.0,
        "is_reorg_anchor_type": 1.0 if at == "anchor_reorg" else 0.0,
        "rank_le_3": 1.0 if row["rank"] <= 3 else 0.0,
        "rank_eq_1": 1.0 if row["rank"] == 1 else 0.0,
        "early_and_hot": seal_early * (1.0 if row["rank"] <= 3 else 0.0),
        "anchor_and_yizi": float(row["is_anchor"] and row["yizi"]),
    }


def matrix(rows, feat_names):
    X = np.array([[featurize(r)[k] for k in feat_names] for r in rows], dtype=float)
    y = np.array([r["cont"] for r in rows], dtype=int)
    return X, y


def univariate_auc(X, y, names):
    """单因子 AUC（方向自动取反）。"""
    out = []
    for j, name in enumerate(names):
        x = X[:, j]
        if np.std(x) < 1e-12:
            out.append((name, 0.5, False))
            continue
        try:
            auc = roc_auc_score(y, x)
        except ValueError:
            auc = 0.5
        flip = False
        if auc < 0.5:
            auc = 1.0 - auc
            flip = True
        out.append((name, float(auc), flip))
    out.sort(key=lambda t: -t[1])
    return out


def time_split(rows, train_ratio=0.6, valid_ratio=0.2):
    n = len(rows)
    i1 = int(n * train_ratio)
    i2 = int(n * (train_ratio + valid_ratio))
    return rows[:i1], rows[i1:i2], rows[i2:]


def forward_select(Xtr, ytr, Xva, yva, names, max_feats=12):
    """前向筛选：在 valid 上最大化 AUC。"""
    remaining = list(range(len(names)))
    selected = []
    history = []
    best_auc = 0.5
    while remaining and len(selected) < max_feats:
        cand_best = None
        for j in remaining:
            cols = selected + [j]
            auc = fit_auc(Xtr[:, cols], ytr, Xva[:, cols], yva)
            if cand_best is None or auc > cand_best[0]:
                cand_best = (auc, j)
        if cand_best is None or cand_best[0] < best_auc + 0.002:
            # 增益不足则停（第一个特征例外）
            if selected:
                break
        best_auc, j = cand_best
        selected.append(j)
        remaining.remove(j)
        history.append((names[j], best_auc, len(selected)))
    return selected, history


def fit_auc(Xtr, ytr, Xva, yva):
    if len(np.unique(ytr)) < 2 or len(np.unique(yva)) < 2:
        return 0.5
    scaler = StandardScaler()
    Xtr_s = scaler.fit_transform(Xtr)
    Xva_s = scaler.transform(Xva)
    clf = LogisticRegression(max_iter=500, C=1.0, solver="lbfgs")
    clf.fit(Xtr_s, ytr)
    proba = clf.predict_proba(Xva_s)[:, 1]
    return float(roc_auc_score(yva, proba))


def train_lr(Xtr, ytr, Xte, yte, C=1.0):
    scaler = StandardScaler()
    Xtr_s = scaler.fit_transform(Xtr)
    Xte_s = scaler.transform(Xte)
    clf = LogisticRegression(max_iter=800, C=C, solver="lbfgs")
    clf.fit(Xtr_s, ytr)
    p_tr = clf.predict_proba(Xtr_s)[:, 1]
    p_te = clf.predict_proba(Xte_s)[:, 1]
    metrics = {
        "train_auc": float(roc_auc_score(ytr, p_tr)) if len(np.unique(ytr)) > 1 else None,
        "test_auc": float(roc_auc_score(yte, p_te)) if len(np.unique(yte)) > 1 else None,
        "train_logloss": float(log_loss(ytr, p_tr)),
        "test_logloss": float(log_loss(yte, p_te)),
        "train_brier": float(brier_score_loss(ytr, p_tr)),
        "test_brier": float(brier_score_loss(yte, p_te)),
        "train_rate": float(ytr.mean()),
        "test_rate": float(yte.mean()),
    }
    return clf, scaler, p_tr, p_te, metrics


def score_bins(rows, probs, n_bins=5):
    order = np.argsort(-probs)
    n = len(probs)
    out = []
    for b in range(n_bins):
        lo = b * n // n_bins
        hi = (b + 1) * n // n_bins
        idx = order[lo:hi]
        if len(idx) == 0:
            continue
        rate = float(np.mean([rows[i]["cont"] for i in idx]))
        sc = probs[idx]
        out.append(
            {
                "bin": b + 1,
                "label": f"Q{b+1}" + ("最高" if b == 0 else ("最低" if b == n_bins - 1 else "")),
                "n": len(idx),
                "cont_rate": rate,
                "score_min": float(sc.min() * 100),
                "score_max": float(sc.max() * 100),
                "score_mean": float(sc.mean() * 100),
            }
        )
    return out


def main():
    rows = build_raw_rows()
    print(f"样本 n={len(rows)} 连板率={np.mean([r['cont'] for r in rows]):.1%}")

    # 探测特征名
    feat0 = featurize(rows[0])
    all_names = list(feat0.keys())

    train, valid, test = time_split(rows, 0.6, 0.2)
    print(f"train {len(train)} {train[0]['T']}~{train[-1]['T']}")
    print(f"valid {len(valid)} {valid[0]['T']}~{valid[-1]['T']}")
    print(f"test  {len(test)} {test[0]['T']}~{test[-1]['T']}")

    Xtr_all, ytr = matrix(train, all_names)
    Xva_all, yva = matrix(valid, all_names)
    Xte_all, yte = matrix(test, all_names)

    # 1) 单因子筛选
    uni = univariate_auc(Xtr_all, ytr, all_names)
    print("\n单因子 train AUC top:")
    for name, auc, flip in uni[:12]:
        print(f"  {name}: {auc:.3f} flip={flip}")

    # 保留 train AUC >= 0.52
    kept_uni = [name for name, auc, _ in uni if auc >= 0.52]
    if len(kept_uni) < 5:
        kept_uni = [name for name, _, _ in uni[:10]]
    print(f"\n单因子入围 {len(kept_uni)}: {kept_uni}")

    # 2) 前向筛选
    idx_map = {n: i for i, n in enumerate(all_names)}
    cand_idx = [idx_map[n] for n in kept_uni]
    Xtr_c = Xtr_all[:, cand_idx]
    Xva_c = Xva_all[:, cand_idx]
    cand_names = kept_uni
    sel_local, hist = forward_select(Xtr_c, ytr, Xva_c, yva, cand_names, max_feats=10)
    sel_names = [cand_names[j] for j in sel_local]
    print("\n前向筛选顺序:")
    for name, auc, k in hist:
        print(f"  +{name} → valid AUC {auc:.3f} (k={k})")
    if not sel_names:
        sel_names = kept_uni[:8]
    print("最终特征:", sel_names)

    # 3) 在 train+valid 上重训，test 评估；C 网格
    train_val = train + valid
    Xtv, ytv = matrix(train_val, sel_names)
    Xte, yte = matrix(test, sel_names)
    Xtr, ytr = matrix(train, sel_names)
    Xva, yva = matrix(valid, sel_names)

    best_C, best_va = 1.0, -1.0
    for C in [0.1, 0.3, 1.0, 3.0, 10.0]:
        _, _, _, pva, _ = train_lr(Xtr, ytr, Xva, yva, C=C)
        # reuse fit on train eval valid - train_lr uses Xte as second
        auc = float(roc_auc_score(yva, pva)) if len(np.unique(yva)) > 1 else 0.5
        print(f"C={C} valid_auc={auc:.3f}")
        if auc > best_va:
            best_va, best_C = auc, C

    # 全 train+valid 训练，test 报告
    clf, scaler, p_tv, p_te, metrics = train_lr(Xtv, ytv, Xte, yte, C=best_C)
    print("\nTest metrics:", metrics)

    # 全样本分数（用 train+valid 模型）
    X_all, y_all = matrix(rows, sel_names)
    X_all_s = scaler.transform(X_all)
    proba_all = clf.predict_proba(X_all_s)[:, 1]
    scores = proba_all * 100.0

    # 系数（标准化空间）
    coef = clf.coef_.ravel()
    intercept = float(clf.intercept_[0])
    coef_table = sorted(
        [
            {
                "feature": sel_names[j],
                "coef_std": float(coef[j]),
                "abs": abs(float(coef[j])),
            }
            for j in range(len(sel_names))
        ],
        key=lambda x: -x["abs"],
    )

    # 分档
    bins_all = score_bins(rows, proba_all, 5)
    bins_te = score_bins(test, p_te, 5)

    # 输出行
    out_rows = []
    for i, r in enumerate(rows):
        out_rows.append(
            {
                **{k: r[k] for k in (
                    "T", "T1", "code", "name", "theme", "boards", "rank", "fb",
                    "yizi", "amt", "is_anchor", "down_h", "anchor_type",
                    "seal_rank_theme", "first_seal_sec", "cont",
                )},
                "score": round(float(scores[i]), 2),
                "prob": round(float(proba_all[i]), 4),
            }
        )
    out_rows.sort(key=lambda x: -x["score"])

    # 阈值
    thr_lines = []
    for thr in [40, 50, 55, 60, 65, 70, 75, 80]:
        sub = [r for r in out_rows if r["score"] >= thr]
        if len(sub) < 8:
            continue
        rate = sum(r["cont"] for r in sub) / len(sub)
        thr_lines.append((thr, len(sub), rate))

    # 三坑
    pit = [
        r
        for r in out_rows
        if r["name"] in ("澄星股份", "神州高铁", "华升股份")
        and r["T"] in ("2025-10-14", "2026-03-31", "2026-04-20")
    ]

    lines = [
        "# 机器学习：事前连板评分（满分100 = 预测概率×100）",
        "",
        "## 训练设定",
        "",
        f"- 样本 n=**{len(rows)}**，连板率 {np.mean(y_all):.1%}",
        f"- **时序切分** train {len(train)} / valid {len(valid)} / test {len(test)}",
        f"- 单因子筛 AUC≥0.52 → 前向筛选 → 逻辑回归 L2（C={best_C}）",
        f"- **不用次日开盘价**",
        "",
        "## 单因子筛选（train AUC）",
        "",
        "| 特征 | AUC |",
        "|------|-----|",
    ]
    for name, auc, flip in uni[:15]:
        mark = " ✓入围" if name in kept_uni else ""
        lines.append(f"| `{name}` | {auc:.3f}{mark} |")

    lines += [
        "",
        "## 前向筛选路径（valid AUC）",
        "",
    ]
    for name, auc, k in hist:
        lines.append(f"{k}. +`{name}` → valid AUC **{auc:.3f}**")

    lines += [
        "",
        f"## 最终模型特征（{len(sel_names)}）",
        "",
        "| 特征 | 标准化系数 | 方向 |",
        "|------|------------|------|",
    ]
    for c in coef_table:
        direction = "↑利多连板" if c["coef_std"] > 0 else "↓利空连板"
        lines.append(f"| `{c['feature']}` | {c['coef_std']:+.3f} | {direction} |")

    lines += [
        "",
        "## 测试集表现",
        "",
        f"- test AUC: **{metrics['test_auc']:.3f}**",
        f"- test logloss: {metrics['test_logloss']:.3f}",
        f"- test Brier: {metrics['test_brier']:.3f}",
        f"- train AUC: {metrics['train_auc']:.3f}",
        f"- test 基线连板率: {metrics['test_rate']:.1%}",
        "",
        "### 测试集五档（高→低）",
        "",
        "| 档 | n | 连板率 | 分数范围 |",
        "|----|---|--------|----------|",
    ]
    for b in bins_te:
        lines.append(
            f"| {b['label']} | {b['n']} | **{b['cont_rate']:.1%}** | "
            f"{b['score_min']:.1f}~{b['score_max']:.1f} |"
        )

    lines += [
        "",
        "### 全样本五档（模型打分，含训练段，仅供参考）",
        "",
        "| 档 | n | 连板率 | 分数范围 |",
        "|----|---|--------|----------|",
    ]
    for b in bins_all:
        lines.append(
            f"| {b['label']} | {b['n']} | **{b['cont_rate']:.1%}** | "
            f"{b['score_min']:.1f}~{b['score_max']:.1f} |"
        )

    lines += ["", "## 分数阈值（全样本）", ""]
    for thr, n, rate in thr_lines:
        lines.append(f"- score ≥ **{thr}**：n={n} 连板 **{rate:.1%}**")

    lines += ["", "## Top12", ""]
    lines.append("| score | T | 名 | theme | rank | 连 |")
    lines.append("|-------|---|-----|-------|------|----|")
    for r in out_rows[:12]:
        lines.append(
            f"| {r['score']:.1f} | {r['T']} | {r['name']} | {r['theme']} | "
            f"{r['rank']} | {r['cont']} |"
        )

    lines += ["", "## 三坑货", ""]
    for r in pit:
        lines.append(
            f"- {r['T']} {r['name']}: **{r['score']:.1f}/100** cont={r['cont']} "
            f"rank={r['rank']} yizi={r['yizi']} anchor={r['is_anchor']}"
        )

    lines += [
        "",
        "## 结论",
        "",
        "- 用 **时序验证 + 单因子筛选 + 前向筛选 + 逻辑回归**，比手调权重正规。",
        f"- 测试集 AUC≈**{metrics['test_auc']:.2f}**：有区分力，但远非完美。",
        "- 分数 = **P(次日连板)×100**，可直接当 0～100 分。",
        "- 仍建议 T+1 叠开盘/发酵水下/回封规则。",
        "",
        f"明细：`{OUT_CSV.relative_to(ROOT)}`",
        f"模型：`{OUT_MODEL.relative_to(ROOT)}`",
    ]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    model_blob = {
        "features": sel_names,
        "C": best_C,
        "intercept": intercept,
        "coef_std": {c["feature"]: c["coef_std"] for c in coef_table},
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "metrics": metrics,
        "forward_path": [{"feature": n, "valid_auc": a, "k": k} for n, a, k in hist],
        "univariate": [
            {"feature": n, "train_auc": a, "flip": flip} for n, a, flip in uni
        ],
    }
    OUT_MODEL.write_text(json.dumps(model_blob, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
