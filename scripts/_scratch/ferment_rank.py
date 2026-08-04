# -*- coding: utf-8 -*-
"""发酵 = 当日 theme 首板+反包 在全市场的排名（1=最热）。fb=0 排最后。"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts/_scratch")
from ferment_open_seal_grid import (
    theme_fb_counts,
    open_pct_t1,
    touch_seal_t1,
)
from reverse_zhaban_top_open import keep_top_open_per_group
import importlib.util

spec = importlib.util.spec_from_file_location(
    "bt", "scripts/_scratch/backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

days, pools, pools_m = bt.load_days()
OUT = Path("data/kaipanla/ladder_daily/node_ferment_rank.csv")
OUT_MD = Path("data/kaipanla/ladder_daily/node_ferment_rank.md")


def theme_rank_map(stocks):
    fb = theme_fb_counts(stocks)
    items = sorted(fb.items(), key=lambda x: (-x[1], x[0]))
    rank = {}
    prev_c, prev_r = None, 0
    for i, (th, c) in enumerate(items, 1):
        if c != prev_c:
            prev_r, prev_c = i, c
        rank[th] = prev_r
    return rank, fb, len(items)


def rank_of(theme, ranks, fb, n_th):
    """无首板的 theme：名次 = n_th+1（最冷一档）"""
    th = theme or "（无）"
    if th in ranks:
        return ranks[th], fb.get(th, 0), n_th
    return (n_th + 1 if n_th else 999), 0, n_th


def main():
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
        ranks1, fb1, n_th1 = theme_rank_map(pools[t1])
        for s in pools[cur]:
            if s["code"] not in mem:
                continue
            if bt.is_gonggao(s, cur):
                continue
            th = (s.get("theme") or "").strip() or "（无）"
            r0, c0, _ = rank_of(th, ranks, fb, n_th)
            r1, c1, _ = rank_of(th, ranks1, fb1, n_th1)
            code = str(s["code"]).zfill(6)
            b0 = int(s.get("boards") or 0)
            s1 = pools_m.get(t1, {}).get(code)
            op = open_pct_t1(code, t1, s1)
            if op is None:
                continue
            touched, sealed = touch_seal_t1(code, t1, pools_m, b0)
            if touched is None:
                continue
            rows.append(
                {
                    "T": cur,
                    "T1": t1,
                    "code": code,
                    "name": s.get("name") or "",
                    "boards_T": b0,
                    "theme": th,
                    "fb": c0,
                    "rank_T": r0,
                    "n_themes_T": n_th,
                    "fb_T1": c1,
                    "rank_T1": r1,
                    "open_pct_T1": op,
                    "yizi": bt.is_yizi(s),
                    "amount_yi": bt.amount_yi(s),
                    "touched": touched,
                    "sealed": sealed,
                    "zhaban": bool(touched and not sealed),
                    "dead_h": dead_h,
                    "down_h": lad.get("height"),
                }
            )

    kept, dropped = keep_top_open_per_group(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(kept[0].keys()))
        w.writeheader()
        w.writerows(kept)

    lines = []
    lines.append("# 发酵 = 当日主属性首板热度排名（1=最热）\n")
    lines.append(
        f"同梯队同属性只留开最高；样本 kept={len(kept)}（去同组低开 {dropped}）\n"
    )
    lines.append(
        "排名：按 theme 的首板+反包家数降序；**无首板的 theme 记为 n_themes+1（最冷）**。\n"
    )

    # three
    lines.append("## 三坑货\n")
    lines.append("| T | 名 | theme | fb | **rank_T** | rank_T1 | 开% | 结果 |\n")
    lines.append("|---|-----|-------|-----|------------|---------|-----|------|\n")
    for r in kept:
        if r["name"] in ("澄星股份", "神州高铁", "华升股份") and r["T"] in (
            "2025-10-14",
            "2026-03-31",
            "2026-04-20",
        ):
            res = "炸" if r["zhaban"] else ("封" if r["sealed"] else "未摸")
            lines.append(
                f"| {r['T']} | {r['name']} | {r['theme']} | {r['fb']} | "
                f"**#{r['rank_T']}**/{r['n_themes_T']} | #{r['rank_T1']} | "
                f"{r['open_pct_T1']:.1f}% | {res} |\n"
            )

    touch = [r for r in kept if r["touched"]]
    lines.append(f"\n摸板 n={len(touch)} 炸={sum(1 for r in touch if r['zhaban'])} "
                 f"炸板率={sum(1 for r in touch if r['zhaban'])/len(touch):.1%}\n")

    def bucket_rank(r):
        k = r["rank_T"]
        if k == 1:
            return "R1最热"
        if k <= 3:
            return "R2-3"
        if k <= 6:
            return "R4-6"
        if k <= 10:
            return "R7-10"
        return "R11+冷"

    lines.append("## 按排名档 炸板率\n")
    lines.append("| 排名档 | 摸板n | 炸 | 炸板率 |\n|--------|-------|-----|--------|\n")
    for lab in ["R1最热", "R2-3", "R4-6", "R7-10", "R11+冷"]:
        sub = [r for r in touch if bucket_rank(r) == lab]
        if not sub:
            continue
        z = sum(1 for r in sub if r["zhaban"])
        lines.append(f"| {lab} | {len(sub)} | {z} | {z/len(sub):.1%} |\n")

    lines.append("\n## 排名 × 开盘 炸板率（n≥3）\n")
    lines.append("| 排名 | 水下 | [0,5) | [5,9) | 近板≥9 |\n")
    lines.append("|------|------|-------|-------|--------|\n")
    for rlab, rp in [
        ("R1", lambda r: r["rank_T"] == 1),
        ("R2-3", lambda r: 2 <= r["rank_T"] <= 3),
        ("R4-6", lambda r: 4 <= r["rank_T"] <= 6),
        ("R7+", lambda r: r["rank_T"] >= 7),
    ]:
        cells = []
        for op in [
            lambda r: r["open_pct_T1"] < 0,
            lambda r: 0 <= r["open_pct_T1"] < 5,
            lambda r: 5 <= r["open_pct_T1"] < 9,
            lambda r: r["open_pct_T1"] >= 9,
        ]:
            sub = [r for r in touch if rp(r) and op(r)]
            if len(sub) < 3:
                cells.append(f"n{len(sub)}")
            else:
                z = sum(1 for r in sub if r["zhaban"])
                cells.append(f"{z/len(sub):.0%}(n{len(sub)})")
        lines.append(f"| {rlab} | " + " | ".join(cells) + " |\n")

    # expectation: T vs T1 rank
    lines.append("\n## 次日排名变化（超预期/不及）\n")
    both = [r for r in touch if r["rank_T1"] is not None]
    lines.append("| 变化 | 含义 | 摸 | 炸 | 炸板率 |\n|------|------|----|----|--------|\n")
    for lab, pred in [
        ("升热 rank变小", lambda r: r["rank_T1"] < r["rank_T"]),
        ("持平", lambda r: r["rank_T1"] == r["rank_T"]),
        ("变冷 rank变大", lambda r: r["rank_T1"] > r["rank_T"]),
    ]:
        sub = [r for r in both if pred(r)]
        z = sum(1 for r in sub if r["zhaban"])
        lines.append(f"| {lab} | | {len(sub)} | {z} | {z/len(sub) if sub else 0:.1%} |\n")

    # redefine 发酵水下 as R1-3 water
    lines.append("\n## 用「排名」重写水下第一坑\n")
    for name, pred in [
        ("R1-3 且水下", lambda r: r["rank_T"] <= 3 and r["open_pct_T1"] < 0),
        ("R1 且水下", lambda r: r["rank_T"] == 1 and r["open_pct_T1"] < 0),
        ("R1-3 且近板", lambda r: r["rank_T"] <= 3 and r["open_pct_T1"] >= 9),
        ("R4+ 且近板", lambda r: r["rank_T"] >= 4 and r["open_pct_T1"] >= 9),
        ("R11+冷 且近板", lambda r: r["rank_T"] >= 11 and r["open_pct_T1"] >= 9),
    ]:
        sub = [r for r in touch if pred(r)]
        if not sub:
            lines.append(f"- {name}: n=0\n")
            continue
        z = sum(1 for r in sub if r["zhaban"])
        lines.append(f"- **{name}**: 摸{len(sub)} 炸{z} **炸板率{z/len(sub):.1%}**\n")

    # kill R1-3 water
    left = [r for r in touch if not (r["rank_T"] <= 3 and r["open_pct_T1"] < 0)]
    z = sum(1 for r in left if r["zhaban"])
    lines.append(
        f"\n删「R1-3且水下」后: 摸{len(left)} 炸{z} 炸板率{z/len(left):.1%} "
        f"(基线 {sum(1 for r in touch if r['zhaban'])/len(touch):.1%})\n"
    )

    lines.append("\n## 口径建议\n")
    lines.append(
        "- **发酵强度 = rank_T（当日 theme 首板热度全市场第几）**，不看绝对家数\n"
        "- rank=1 最热；无首板 theme → 最冷档\n"
        "- **超预期/不及**：次日 rank 上升/下降（需 T+1 收盘才完整；盘中可看实时首板榜）\n"
        "- 热门水下（R1-3+开盘<0）仍应是第一刀\n"
        "- 冷门贴板（高 rank 数字 + 近板）对应澄星类弱结构\n"
    )

    OUT_MD.write_text("".join(lines), encoding="utf-8")
    print("".join(lines))
    print(f"wrote {OUT} {OUT_MD}")


if __name__ == "__main__":
    main()
