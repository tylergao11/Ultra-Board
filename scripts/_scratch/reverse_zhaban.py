# -*- coding: utf-8 -*-
"""反推：先找齐「摸板却炸板」→ 再看发酵/开盘/板高/量能等长什么样。

样本：节点日纯往下锚层、非公告、有次日 OHLC 可判摸板。
炸板 = T+1 摸到涨停价 且 收盘未封住。
"""
from __future__ import annotations

import csv
import importlib.util
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

# reuse builders from ferment grid
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferment_open_seal_grid import (  # noqa: E402
    build_rows,
    theme_fb_counts,
)

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
OUT_MD = OUT_DIR / "reverse_zhaban.md"
OUT_CSV = OUT_DIR / "reverse_zhaban.csv"


def pct(n, d):
    return n / d if d else 0.0


def bucket_open(x: float) -> str:
    if x < -3:
        return "<-3%深水"
    if x < 0:
        return "[-3,0)贴水"
    if x < 2:
        return "[0,2)零上"
    if x < 5:
        return "[2,5)"
    if x < 8:
        return "[5,8)"
    if x < 9.5:
        return "[8,9.5)"
    return "≥9.5%近板"


def bucket_fb(n: int) -> str:
    if n <= 0:
        return "fb=0"
    if n == 1:
        return "fb=1"
    if n == 2:
        return "fb=2"
    if n == 3:
        return "fb=3"
    if n <= 5:
        return "fb=4-5"
    return "fb≥6"


def bucket_boards(b: int) -> str:
    if b <= 2:
        return "2板"
    if b == 3:
        return "3板"
    if b == 4:
        return "4板"
    return "≥5板"


def bucket_amt(a) -> str:
    if a is None:
        return "额未知"
    if a < 1:
        return "<1亿"
    if a < 3:
        return "1-3亿"
    if a < 8:
        return "3-8亿"
    if a < 15:
        return "8-15亿"
    return "≥15亿"


def dist_table(items: list[dict], key_fn, title: str, baseline_touch: list[dict]) -> list[str]:
    """炸板分布 vs 全体摸板分布，算 lift。"""
    lines = [f"### {title}", ""]
    c_z = Counter(key_fn(r) for r in items)
    c_t = Counter(key_fn(r) for r in baseline_touch)
    n_z, n_t = len(items) or 1, len(baseline_touch) or 1
    keys = sorted(set(c_z) | set(c_t), key=lambda k: -c_z.get(k, 0))
    lines.append("| 分档 | 炸板n | 占炸板 | 摸板总体n | 占摸板 | lift(炸/摸) | 该档炸板率 |")
    lines.append("|------|-------|--------|-----------|--------|------------|------------|")
    for k in keys:
        nz, nt = c_z.get(k, 0), c_t.get(k, 0)
        # 该档炸板率 = 炸板在该档 / 摸板在该档
        zrate = nz / nt if nt else 0
        lift = (nz / n_z) / (nt / n_t) if nt else 0
        lines.append(
            f"| {k} | {nz} | {nz/n_z:.1%} | {nt} | {nt/n_t:.1%} | {lift:.2f} | {zrate:.1%} |"
        )
    lines.append("")
    return lines


def main() -> int:
    days, pools, pools_m = bt.load_days()
    rows = build_rows(days, pools, pools_m)
    touch = [r for r in rows if r["touched"]]
    seal = [r for r in touch if r["sealed"]]
    zha = [r for r in touch if r["zhaban"]]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if zha:
        with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(zha[0].keys()))
            w.writeheader()
            w.writerows(zha)

    lines = [
        "# 反推：全部炸板样本",
        "",
        f"- 可分析票·次（有开盘+可判摸板）：**{len(rows)}**",
        f"- 摸板：**{len(touch)}**",
        f"- 封住：**{len(seal)}** → 封板率 {pct(len(seal), len(touch)):.1%}",
        f"- **炸板：{len(zha)}** → 炸板率 {pct(len(zha), len(touch)):.1%}",
        "",
        "炸板定义：T+1 `high` 触及涨停价，且收盘未封（且不在涨停池）。",
        f"名单：`{OUT_CSV.relative_to(ROOT)}`",
        "",
        "## 1. 炸板名单（全）",
        "",
        "| T | 名 | 板 | theme | fb首板同属性 | 次日开% | 额亿 | 一字 |",
        "|---|-----|-----|-------|--------------|---------|------|------|",
    ]
    for r in sorted(zha, key=lambda x: (x["T"], -x["open_pct_T1"])):
        lines.append(
            f"| {r['T']} | {r['name']} | {r['boards_T']} | {r['theme']} | "
            f"{r['fb']} | {r['open_pct_T1']:.2f} | {r['amount_yi']} | "
            f"{'Y' if r['yizi'] else ''} |"
        )
    lines.append("")

    lines.append("## 2. 单因子反推（炸板 vs 全体摸板）")
    lines.append("")
    lines.append(
        "lift>1 表示该档在炸板里更「超配」；**该档炸板率** 是最直接的风险。"
    )
    lines.append("")

    lines += dist_table(zha, lambda r: bucket_fb(r["fb"]), "首板同属性发酵 fb", touch)
    lines += dist_table(zha, lambda r: bucket_open(r["open_pct_T1"]), "次日开盘%", touch)
    lines += dist_table(zha, lambda r: bucket_boards(r["boards_T"]), "节点日板高", touch)
    lines += dist_table(zha, lambda r: bucket_amt(r["amount_yi"]), "成交额", touch)
    lines += dist_table(
        zha, lambda r: "一字" if r["yizi"] else "换手", "板型", touch
    )
    lines += dist_table(
        zha,
        lambda r: (
            "发酵水下"
            if r["fb"] >= 3 and r["open_pct_T1"] < 0
            else "发酵零上"
            if r["fb"] >= 3 and r["open_pct_T1"] >= 0
            else "未发酵近板≥8"
            if r["fb"] < 3 and r["open_pct_T1"] >= 8
            else "未发酵弱开<5"
            if r["fb"] < 3 and r["open_pct_T1"] < 5
            else "未发酵中开"
        ),
        "发酵×开盘组合（口感标签）",
        touch,
    )

    # cross heat: fb bucket x open bucket zhaban rate
    lines.append("## 3. 交叉热力：fb × 开盘 → 该格炸板率（摸板样本）")
    lines.append("")
    fb_keys = ["fb=0", "fb=1", "fb=2", "fb=3", "fb=4-5", "fb≥6"]
    op_keys = [
        "<-3%深水",
        "[-3,0)贴水",
        "[0,2)零上",
        "[2,5)",
        "[5,8)",
        "[8,9.5)",
        "≥9.5%近板",
    ]
    # header
    lines.append("| fb\\\\开盘 | " + " | ".join(op_keys) + " |")
    lines.append("|---|" + "|".join(["---"] * len(op_keys)) + "|")
    for fk in fb_keys:
        cells = []
        for ok in op_keys:
            cell = [
                r
                for r in touch
                if bucket_fb(r["fb"]) == fk and bucket_open(r["open_pct_T1"]) == ok
            ]
            if len(cell) < 2:
                cells.append(f"n={len(cell)}")
            else:
                zr = sum(1 for r in cell if r["zhaban"]) / len(cell)
                cells.append(f"{zr:.0%}(n{len(cell)})")
        lines.append(f"| {fk} | " + " | ".join(cells) + " |")
    lines.append("")

    # quantitative summary of zha
    ops = [r["open_pct_T1"] for r in zha]
    fbs = [r["fb"] for r in zha]
    lines.append("## 4. 炸板样本数值画像")
    lines.append("")
    lines.append(f"- 开盘%：均值 {mean(ops):.2f}% 中位 {median(ops):.2f}% "
                 f"p25 {sorted(ops)[len(ops)//4]:.2f}% p75 {sorted(ops)[3*len(ops)//4]:.2f}%")
    lines.append(f"- fb：均值 {mean(fbs):.2f} 中位 {median(fbs):.1f}")
    lines.append(
        f"- 开盘<0：{sum(1 for x in ops if x<0)}/{len(ops)}={pct(sum(1 for x in ops if x<0), len(ops)):.0%}"
    )
    lines.append(
        f"- 开盘≥9.5%：{sum(1 for x in ops if x>=9.5)}/{len(ops)}="
        f"{pct(sum(1 for x in ops if x>=9.5), len(ops)):.0%}"
    )
    lines.append(
        f"- fb≥3 且开盘<0：{sum(1 for r in zha if r['fb']>=3 and r['open_pct_T1']<0)}"
    )
    lines.append(
        f"- fb<3 且开盘≥9.5%：{sum(1 for r in zha if r['fb']<3 and r['open_pct_T1']>=9.5)}"
    )
    lines.append("")

    # compare seal group same stats
    lines.append("## 5. 对照：封住样本（同口径）")
    lines.append("")
    if seal:
        sop = [r["open_pct_T1"] for r in seal]
        sfb = [r["fb"] for r in seal]
        lines.append(
            f"- 开盘%：均值 {mean(sop):.2f}% 中位 {median(sop):.2f}%"
        )
        lines.append(f"- fb：均值 {mean(sfb):.2f} 中位 {median(sfb):.1f}")
        lines.append(
            f"- 开盘<0：{pct(sum(1 for x in sop if x<0), len(sop)):.0%}；"
            f"≥9.5%：{pct(sum(1 for x in sop if x>=9.5), len(sop)):.0%}"
        )
    lines.append("")

    lines.append("## 6. 反推结论（先写死的）")
    lines.append("")
    # compute top risk cells
    risk = []
    for fk in fb_keys:
        for ok in op_keys:
            cell = [
                r
                for r in touch
                if bucket_fb(r["fb"]) == fk and bucket_open(r["open_pct_T1"]) == ok
            ]
            if len(cell) < 3:
                continue
            zr = sum(1 for r in cell if r["zhaban"]) / len(cell)
            risk.append((zr, len(cell), fk, ok))
    risk.sort(reverse=True)
    lines.append("摸板 n≥3 时，炸板率最高的格子：")
    for zr, n, fk, ok in risk[:8]:
        lines.append(f"- **{fk} × {ok}**：炸板率 {zr:.0%}（n={n}）")
    lines.append("")
    lines.append("相对安全（炸板率最低）的格子：")
    for zr, n, fk, ok in sorted(risk, key=lambda x: (x[0], -x[1]))[:8]:
        lines.append(f"- {fk} × {ok}：炸板率 {zr:.0%}（n={n}）")
    lines.append("")
    lines.append(
        "后续规则应优先 **杀掉高炸板格子**，而不是先优化均值开盘。"
    )

    text = "\n".join(lines)
    OUT_MD.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT_MD}\n→ {OUT_CSV} zha={len(zha)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
