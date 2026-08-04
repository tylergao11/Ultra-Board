# -*- coding: utf-8 -*-
"""第二步因子：发酵(首板同属性) × 次日开盘 过滤 → 摸板封板率。

目标：几乎不允许炸板（摸到涨停却没收住）。
  封板率 = 封住 / 摸到涨停（没摸板不算分母）

发酵：节点日 T 当日，该票 theme 的「首板+反包」家数 theme_fb。
  fb >= F → 发酵，否则未发酵。

开盘过滤（用户口径 → 可调阈值）：
  发酵：几乎不允许水下开；允许零轴上方小幅洗盘 → open >= Water_f 且 open <= Cap_f
  未发酵：不允许接近板开（易天地面）；允许水下 → open <= Near_u 且 (允许 open 很低)

网格搜 F / Water_f / Cap_f / Near_u，按：
  1) 封板率（摸板子集）
  2) 炸板率 = 1 - 封板率
  3) 样本量（摸板 n）
  4) 通过过滤后的票次（覆盖）

数据：纯往下锚层 × ohlc_cache 次日开盘。
"""
from __future__ import annotations

import csv
import importlib.util
import json
from collections import defaultdict
from itertools import product
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
OUT_MD = OUT_DIR / "ferment_open_seal_grid.md"
OUT_CSV = OUT_DIR / "ferment_open_seal_rows.csv"
OUT_GRID = OUT_DIR / "ferment_open_seal_grid.csv"

_bars: dict[str, dict] = {}


def load_bars(code: str) -> dict:
    code = str(code).zfill(6)
    if code in _bars:
        return _bars[code]
    p = CACHE / f"{code}.json"
    if not p.exists():
        _bars[code] = {}
        return {}
    try:
        _bars[code] = json.loads(p.read_text(encoding="utf-8-sig")).get("bars") or {}
    except Exception:
        _bars[code] = {}
    return _bars[code]


def lim_pct(code: str) -> float:
    if str(code).startswith(("300", "301", "688", "689")):
        return 20.0
    return 10.0


def theme_fb_counts(stocks: list) -> dict[str, int]:
    """首板 + 反包 按 theme 计数。"""
    c: dict[str, int] = defaultdict(int)
    for s in stocks:
        is_fb = bool(s.get("is_fanbao")) or int(s.get("boards") or 0) == 1
        if not is_fb:
            continue
        th = (s.get("theme") or "").strip() or "（无）"
        c[th] += 1
    return dict(c)


def open_pct_t1(code: str, t1: str, s1: dict | None) -> float | None:
    b = load_bars(code).get(t1)
    if b and b.get("open_pct") is not None:
        try:
            return float(b["open_pct"])
        except (TypeError, ValueError):
            pass
    if b and b.get("open") is not None and b.get("prev_close"):
        try:
            o, p = float(b["open"]), float(b["prev_close"])
            if p > 0:
                return round((o / p - 1) * 100, 4)
        except (TypeError, ValueError):
            pass
    if s1 and s1.get("open_pct") is not None:
        try:
            return float(s1["open_pct"])
        except (TypeError, ValueError):
            pass
    return None


def touch_seal_t1(code: str, t1: str, pools_m: dict, b0: int) -> tuple[bool | None, bool | None]:
    """(touched, sealed) on T+1; None if no data and not in zt."""
    s1 = pools_m.get(t1, {}).get(code)
    cont = bool(s1) and int(s1.get("boards") or 0) == b0 + 1
    bar = load_bars(code).get(t1)
    if cont:
        return True, True
    if s1 is not None:
        return True, True
    if not bar or bar.get("high") is None or not bar.get("prev_close"):
        return None, None
    try:
        high, close, prev = float(bar["high"]), float(bar["close"]), float(bar["prev_close"])
        if prev <= 0:
            return None, None
        limit_px = prev * (1 + lim_pct(code) / 100)
        tol = max(prev * 0.003, 0.02)
        touched = high + 1e-9 >= limit_px - tol
        sealed = close + 1e-9 >= limit_px - tol
        return touched, sealed
    except (TypeError, ValueError):
        return None, None


def build_rows(days, pools, pools_m) -> list[dict]:
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
        fb = theme_fb_counts(pools[cur])
        for s in pools[cur]:
            if s["code"] not in mem:
                continue
            # 公告板发酵另论：先跳过或 fb=0
            th = (s.get("theme") or "").strip() or "（无）"
            fb_n = int(fb.get(th, 0))
            if bt.is_gonggao(s, cur):
                # 公告不参与主属性发酵逻辑
                continue
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
                    "fb": fb_n,
                    "amount_yi": bt.amount_yi(s),
                    "yizi": bt.is_yizi(s),
                    "open_pct_T1": op,
                    "touched": touched,
                    "sealed": sealed,
                    "zhaban": bool(touched and not sealed),
                    "cont": bool(s1) and int(s1.get("boards") or 0) == b0 + 1,
                    "dead_h": dead_h,
                    "down_h": lad.get("height"),
                }
            )
    return rows


def pass_filter(r: dict, F: int, water_f: float, cap_f: float, near_u: float) -> bool:
    """发酵/未发酵开盘过滤。"""
    fermented = r["fb"] >= F
    op = r["open_pct_T1"]
    if fermented:
        # 几乎不允许水下；允许零上小洗到 cap_f
        if op < water_f:
            return False
        if op > cap_f:
            # 发酵接近板：也危险？用户说允许零上洗盘，没说接近板；发酵接近板可能仍猛
            # 先不卡上沿，或 loose cap_f=9.5 表示接近板也可
            return False
        return True
    else:
        # 不允许接近板开
        if op > near_u:
            return False
        # 允许水下：不卡下限
        return True


def eval_filter(rows: list[dict], F, water_f, cap_f, near_u) -> dict:
    sel = [r for r in rows if pass_filter(r, F, water_f, cap_f, near_u)]
    touch = [r for r in sel if r["touched"]]
    seal = [r for r in touch if r["sealed"]]
    zha = [r for r in touch if r["zhaban"]]
    n_touch = len(touch)
    seal_r = len(seal) / n_touch if n_touch else 0.0
    zha_r = len(zha) / n_touch if n_touch else 0.0
    return {
        "F": F,
        "water_f": water_f,
        "cap_f": cap_f,
        "near_u": near_u,
        "n_pass": len(sel),
        "n_touch": n_touch,
        "n_seal": len(seal),
        "n_zha": len(zha),
        "seal_r": seal_r,
        "zha_r": zha_r,
        "pass_rate": len(sel) / len(rows) if rows else 0,
        "cont_r": sum(1 for r in sel if r["cont"]) / len(sel) if sel else 0,
    }


def baseline_by_fb(rows: list[dict]) -> list[str]:
    lines = ["## 基线：仅按发酵分档（不过滤开盘）", ""]
    lines.append("| 档 | 定义 | 票次 | 摸板n | 封板率 | 炸板率 |")
    lines.append("|----|------|------|-------|--------|--------|")
    for lab, pred in [
        ("全部", lambda r: True),
        ("fb=0", lambda r: r["fb"] == 0),
        ("fb=1", lambda r: r["fb"] == 1),
        ("fb=2", lambda r: r["fb"] == 2),
        ("fb=3", lambda r: r["fb"] == 3),
        ("fb≥3", lambda r: r["fb"] >= 3),
        ("fb≥4", lambda r: r["fb"] >= 4),
        ("fb≥5", lambda r: r["fb"] >= 5),
    ]:
        sub = [r for r in rows if pred(r)]
        touch = [r for r in sub if r["touched"]]
        if not touch:
            lines.append(f"| {lab} | | {len(sub)} | 0 | - | - |")
            continue
        seal = sum(1 for r in touch if r["sealed"])
        zha = sum(1 for r in touch if r["zhaban"])
        lines.append(
            f"| {lab} | | {len(sub)} | {len(touch)} | "
            f"{seal}/{len(touch)}={seal/len(touch):.1%} | "
            f"{zha}/{len(touch)}={zha/len(touch):.1%} |"
        )
    lines.append("")
    return lines


def open_buckets_by_ferment(rows: list[dict], F: int = 3) -> list[str]:
    lines = [f"## 开盘分桶 × 发酵(F={F}) 的封板率", ""]
    lines.append("| 发酵 | 开盘区间 | 摸板n | 封板率 | 炸板率 |")
    lines.append("|------|----------|-------|--------|--------|")
    bins = [
        ("<-3%", lambda x: x < -3),
        ("[-3,0)", lambda x: -3 <= x < 0),
        ("[0,2)", lambda x: 0 <= x < 2),
        ("[2,5)", lambda x: 2 <= x < 5),
        ("[5,8)", lambda x: 5 <= x < 8),
        ("[8,9.5)", lambda x: 8 <= x < 9.5),
        ("≥9.5%近板", lambda x: x >= 9.5),
    ]
    for fer_lab, fer_pred in [("发酵", lambda r: r["fb"] >= F), ("未发酵", lambda r: r["fb"] < F)]:
        for blab, bpred in bins:
            sub = [r for r in rows if fer_pred(r) and bpred(r["open_pct_T1"]) and r["touched"]]
            if len(sub) < 3:
                lines.append(f"| {fer_lab} | {blab} | {len(sub)} | (样本少) | |")
                continue
            seal = sum(1 for r in sub if r["sealed"])
            zha = sum(1 for r in sub if r["zhaban"])
            lines.append(
                f"| {fer_lab} | {blab} | {len(sub)} | {seal/len(sub):.1%} | {zha/len(sub):.1%} |"
            )
    lines.append("")
    return lines


def main() -> int:
    days, pools, pools_m = bt.load_days()
    rows = build_rows(days, pools, pools_m)

    # write row csv
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if rows:
        with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    # grid
    F_list = [1, 2, 3, 4, 5]
    water_list = [-0.5, 0.0, 0.5, 1.0]  # 发酵最低开
    cap_list = [5.0, 7.0, 9.0, 9.8, 99.0]  # 发酵最高开；99=不限制上沿
    near_list = [3.0, 5.0, 6.0, 7.0, 8.0]  # 未发酵：开盘不得超过

    grid = []
    for F, wf, cf, nu in product(F_list, water_list, cap_list, near_list):
        if wf >= cf and cf < 50:
            continue
        grid.append(eval_filter(rows, F, wf, cf, nu))

    # rank: high seal_r, low zha_r, require n_touch >= 20
    viable = [g for g in grid if g["n_touch"] >= 20]
    viable.sort(key=lambda g: (-g["seal_r"], -g["n_touch"], g["zha_r"]))

    # also rank strict n_touch>=40
    viable40 = [g for g in grid if g["n_touch"] >= 40]
    viable40.sort(key=lambda g: (-g["seal_r"], -g["n_touch"]))

    with OUT_GRID.open("w", encoding="utf-8-sig", newline="") as f:
        if grid:
            w = csv.DictWriter(f, fieldnames=list(grid[0].keys()))
            w.writeheader()
            w.writerows(sorted(grid, key=lambda g: (-g["seal_r"], -g["n_touch"])))

    # baseline no filter
    base = eval_filter(rows, F=99, water_f=-999, cap_f=999, near_u=999)
    # F=99 means all unfermented path with near_u=999 → all pass
    all_touch = [r for r in rows if r["touched"]]
    base_seal = (
        sum(1 for r in all_touch if r["sealed"]) / len(all_touch) if all_touch else 0
    )

    lines = [
        "# 发酵 × 开盘因子网格 → 摸板封板率",
        "",
        f"样本：节点日纯往下锚层、非公告、有次日开盘+可判摸板 **{len(rows)}** 票·次",
        f"全样本摸板封板率（无过滤）：**"
        f"{sum(1 for r in all_touch if r['sealed'])}/{len(all_touch)}="
        f"{base_seal:.1%}**；炸板率 **{1-base_seal:.1%}**",
        "",
        "**发酵** = 节点日 T 该票 theme 的首板+反包家数 `fb ≥ F`",
        "",
        "**开盘规则**",
        "- 发酵：`water_f ≤ open_pct ≤ cap_f`（水下砍掉；上沿 cap 防过热/近板可调，99=不限）",
        "- 未发酵：`open_pct ≤ near_u`（砍接近板开；水下不限）",
        "",
        "**主指标**：摸板封板率；炸板率 = 1 − 封板率。要求摸板 n≥20（稳健 n≥40）。",
        "",
    ]
    lines += baseline_by_fb(rows)
    lines += open_buckets_by_ferment(rows, F=3)
    lines += open_buckets_by_ferment(rows, F=2)

    lines.append("## 网格最优（摸板 n≥20，按封板率）")
    lines.append("")
    lines.append(
        "| 名次 | F | 发酵水下线 | 发酵上沿 | 未发酵近板上限 | 通过n | 摸板n | 封板率 | 炸板率 | 连板率 |"
    )
    lines.append(
        "|------|---|------------|----------|----------------|-------|-------|--------|--------|--------|"
    )
    for i, g in enumerate(viable[:15], 1):
        lines.append(
            f"| {i} | {g['F']} | {g['water_f']}% | {g['cap_f']}% | {g['near_u']}% | "
            f"{g['n_pass']} | {g['n_touch']} | {g['seal_r']:.1%} | {g['zha_r']:.1%} | "
            f"{g['cont_r']:.1%} |"
        )
    lines.append("")
    lines.append("## 网格最优（摸板 n≥40）")
    lines.append("")
    lines.append(
        "| 名次 | F | water_f | cap_f | near_u | 通过n | 摸板n | 封板率 | 炸板率 |"
    )
    lines.append("|------|---|---------|-------|--------|-------|-------|--------|--------|")
    for i, g in enumerate(viable40[:12], 1):
        lines.append(
            f"| {i} | {g['F']} | {g['water_f']} | {g['cap_f']} | {g['near_u']} | "
            f"{g['n_pass']} | {g['n_touch']} | {g['seal_r']:.1%} | {g['zha_r']:.1%} |"
        )

    # recommend
    rec = viable40[0] if viable40 else (viable[0] if viable else None)
    lines.append("")
    lines.append("## 建议默认参数（以封板率为主、样本够）")
    lines.append("")
    if rec:
        lines.append(
            f"- **F={rec['F']}**（fb≥{rec['F']} 算发酵）\n"
            f"- 发酵：开盘 **≥ {rec['water_f']}%** 且 **≤ {rec['cap_f']}%**\n"
            f"- 未发酵：开盘 **≤ {rec['near_u']}%**（禁接近板）\n"
            f"- 效果：摸板封板率 **{rec['seal_r']:.1%}**（炸板 **{rec['zha_r']:.1%}**），"
            f"摸板 n={rec['n_touch']}，通过 {rec['n_pass']} 票·次\n"
            f"- 对比无过滤封板率 **{base_seal:.1%}**\n"
        )
        # vs user intuition
        lines.append("### 与口径对照")
        lines.append("")
        lines.append(
            "- 发酵禁水下：对应 `water_f≈0` 是否进最优前列\n"
            "- 未发酵禁近板：对应 `near_u` 在 5～7 是否抬封板率\n"
            "- 发酵零上小洗：`water_f=0~1` 且 `cap_f` 不必太紧\n"
        )

    # fixed user-like presets
    lines.append("## 固定口径试算（你的描述）")
    lines.append("")
    presets = [
        ("严：F3 发酵≥0 未发酵≤5", 3, 0.0, 99.0, 5.0),
        ("中：F3 发酵≥0 未发酵≤6", 3, 0.0, 99.0, 6.0),
        ("中：F2 发酵≥0 未发酵≤6", 2, 0.0, 99.0, 6.0),
        ("松：F3 发酵≥-0.5 未发酵≤7", 3, -0.5, 99.0, 7.0),
        ("发酵也限近板：F3 ≥0 ≤7 未≤5", 3, 0.0, 7.0, 5.0),
        ("仅禁未发酵近板≤5 其余不过滤发酵", 3, -999, 99.0, 5.0),
    ]
    lines.append("| 预设 | 通过n | 摸板n | 封板率 | 炸板率 |")
    lines.append("|------|-------|-------|--------|--------|")
    for name, F, wf, cf, nu in presets:
        g = eval_filter(rows, F, wf, cf, nu)
        lines.append(
            f"| {name} | {g['n_pass']} | {g['n_touch']} | {g['seal_r']:.1%} | {g['zha_r']:.1%} |"
        )

    lines.append("")
    lines.append(f"明细行：`{OUT_CSV.relative_to(ROOT)}`")
    lines.append(f"全网格：`{OUT_GRID.relative_to(ROOT)}`")

    text = "\n".join(lines)
    OUT_MD.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
