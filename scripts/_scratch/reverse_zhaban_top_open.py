# -*- coding: utf-8 -*-
"""同梯队 + 同属性：只保留次日开盘最高的一只，再反推炸板/封板。

梯队 = 节点日 boards_T（同板高层）
属性 = theme
组内 key = (T, boards_T, theme) → 只留 open_pct_T1 最大者；其余丢掉不看。
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ferment_open_seal_grid import build_rows  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
OUT_MD = OUT_DIR / "reverse_zhaban_top_open.md"
OUT_CSV = OUT_DIR / "reverse_zhaban_top_open.csv"
OUT_KEEP = OUT_DIR / "node_tier_theme_top_open.csv"


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


def keep_top_open_per_group(rows: list[dict]) -> tuple[list[dict], int]:
    """(T, boards_T, theme) 组内 open 最高；并列取额大。"""
    groups: dict[tuple, list] = defaultdict(list)
    for r in rows:
        key = (r["T"], int(r["boards_T"]), r["theme"] or "（无）")
        groups[key].append(r)
    kept = []
    dropped = 0
    for key, items in groups.items():
        items = sorted(
            items,
            key=lambda x: (
                -(x["open_pct_T1"] if x["open_pct_T1"] is not None else -999),
                -(x["amount_yi"] or 0),
            ),
        )
        kept.append(items[0])
        dropped += len(items) - 1
        # tag
        kept[-1] = dict(kept[-1])
        kept[-1]["group_size"] = len(items)
        kept[-1]["group_key"] = f"{key[0]}|{key[1]}板|{key[2]}"
    return kept, dropped


def dist(zha, touch, key_fn, title):
    lines = [f"### {title}", ""]
    c_z = Counter(key_fn(r) for r in zha)
    c_t = Counter(key_fn(r) for r in touch)
    n_z, n_t = len(zha) or 1, len(touch) or 1
    keys = sorted(set(c_z) | set(c_t), key=lambda k: -c_z.get(k, 0))
    lines.append("| 分档 | 炸板n | 占炸板 | 摸板n | 占摸板 | lift | 该档炸板率 |")
    lines.append("|------|-------|--------|-------|--------|------|------------|")
    for k in keys:
        nz, nt = c_z.get(k, 0), c_t.get(k, 0)
        zrate = nz / nt if nt else 0
        lift = (nz / n_z) / (nt / n_t) if nt else 0
        lines.append(
            f"| {k} | {nz} | {nz/n_z:.1%} | {nt} | {nt/n_t:.1%} | {lift:.2f} | {zrate:.1%} |"
        )
    lines.append("")
    return lines


def main() -> int:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
    )
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)

    days, pools, pools_m = bt.load_days()
    raw = build_rows(days, pools, pools_m)
    kept, dropped = keep_top_open_per_group(raw)

    touch = [r for r in kept if r["touched"]]
    seal = [r for r in touch if r["sealed"]]
    zha = [r for r in touch if r["zhaban"]]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # all kept rows for step2
    if kept:
        with OUT_KEEP.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(kept[0].keys()))
            w.writeheader()
            w.writerows(kept)
    if zha:
        with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(zha[0].keys()))
            w.writeheader()
            w.writerows(zha)

    # before filter for comparison
    touch0 = [r for r in raw if r["touched"]]
    zha0 = [r for r in touch0 if r["zhaban"]]

    lines = [
        "# 同梯队同属性 · 只看开最高 → 炸板反推",
        "",
        "**规则**：同一节点日 T、同一 `boards` 梯队、同一 `theme`，"
        "只保留 **次日 open_pct 最高** 的一只（并列比额）；开得低的不看。",
        "",
        f"- 过滤前票·次：{len(raw)} → 保留 **{len(kept)}**（丢掉同组低开 {dropped}）",
        f"- 摸板：{len(touch0)} → **{len(touch)}**",
        f"- 炸板：{len(zha0)} → **{len(zha)}** "
        f"（炸板率 {pct(len(zha0), len(touch0)):.1%} → **{pct(len(zha), len(touch)):.1%}**）",
        f"- 封板率：{pct(sum(1 for r in touch0 if r['sealed']), len(touch0)):.1%} → "
        f"**{pct(len(seal), len(touch)):.1%}**",
        "",
        f"保留全表：`{OUT_KEEP.relative_to(ROOT)}`",
        f"炸板名单：`{OUT_CSV.relative_to(ROOT)}`",
        "",
        "## 炸板名单（组内开最高仍炸）",
        "",
        "| T | 名 | 板 | theme | fb | 开% | 组内n | 额 |",
        "|---|-----|-----|-------|-----|------|------|-----|",
    ]
    for r in sorted(zha, key=lambda x: (x["T"], -x["open_pct_T1"])):
        lines.append(
            f"| {r['T']} | {r['name']} | {r['boards_T']} | {r['theme']} | "
            f"{r['fb']} | {r['open_pct_T1']:.2f} | {r.get('group_size',1)} | "
            f"{r['amount_yi']} |"
        )
    lines.append("")

    lines.append("## 单因子（仅开最高子集）")
    lines.append("")
    lines += dist(zha, touch, lambda r: bucket_fb(r["fb"]), "发酵 fb")
    lines += dist(zha, touch, lambda r: bucket_open(r["open_pct_T1"]), "次日开盘%")
    lines += dist(
        zha, touch, lambda r: f"{r['boards_T']}板", "板高"
    )
    lines += dist(
        zha,
        touch,
        lambda r: "一字" if r["yizi"] else "换手",
        "板型",
    )
    lines += dist(
        zha,
        touch,
        lambda r: (
            "发酵水下"
            if r["fb"] >= 3 and r["open_pct_T1"] < 0
            else "发酵[0,2)"
            if r["fb"] >= 3 and 0 <= r["open_pct_T1"] < 2
            else "发酵≥2%"
            if r["fb"] >= 3
            else "未发酵深水<-3"
            if r["fb"] < 3 and r["open_pct_T1"] < -3
            else "未发酵近板≥9.5"
            if r["fb"] < 3 and r["open_pct_T1"] >= 9.5
            else "未发酵其它"
        ),
        "发酵×开盘",
    )

    # heat
    lines.append("## 交叉：fb × 开盘 → 炸板率（开最高子集·摸板）")
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
    lines.append("| fb\\\\开 | " + " | ".join(op_keys) + " |")
    lines.append("|---|" + "|".join(["---"] * len(op_keys)) + "|")
    risk = []
    for fk in fb_keys:
        cells = []
        for ok in op_keys:
            cell = [
                r
                for r in touch
                if bucket_fb(r["fb"]) == fk and bucket_open(r["open_pct_T1"]) == ok
            ]
            if len(cell) < 2:
                cells.append(f"n{len(cell)}")
            else:
                zr = sum(1 for r in cell if r["zhaban"]) / len(cell)
                cells.append(f"{zr:.0%}(n{len(cell)})")
                if len(cell) >= 3:
                    risk.append((zr, len(cell), fk, ok))
        lines.append(f"| {fk} | " + " | ".join(cells) + " |")
    lines.append("")

    if zha:
        ops = [r["open_pct_T1"] for r in zha]
        lines.append("## 炸板画像（开最高后仍炸）")
        lines.append("")
        lines.append(
            f"- n={len(zha)} 开盘均值 {mean(ops):.2f}% 中位 {median(ops):.2f}%"
        )
        lines.append(
            f"- 开盘<0：{pct(sum(1 for x in ops if x<0), len(ops)):.0%}；"
            f"≥9.5%：{pct(sum(1 for x in ops if x>=9.5), len(ops)):.0%}"
        )
        lines.append(
            f"- 组内曾竞争(group_size>1)："
            f"{sum(1 for r in zha if r.get('group_size',1)>1)}/"
            f"{len(zha)}"
        )
        lines.append("")

    lines.append("## 反推要点")
    lines.append("")
    lines.append(
        "1. 同梯队同属性只看开最高后，噪音票去掉，**封板/炸板率会变**（见文首）。"
    )
    lines.append("2. 仍炸的才是真问题名单。")
    if risk:
        risk.sort(reverse=True)
        lines.append("3. 高危格（n≥3）：")
        for zr, n, fk, ok in risk[:6]:
            lines.append(f"   - {fk} × {ok}：炸 {zr:.0%}（n={n}）")
        lines.append("4. 相对安全：")
        for zr, n, fk, ok in sorted(risk, key=lambda x: (x[0], -x[1]))[:5]:
            lines.append(f"   - {fk} × {ok}：炸 {zr:.0%}（n={n}）")

    text = "\n".join(lines)
    OUT_MD.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
