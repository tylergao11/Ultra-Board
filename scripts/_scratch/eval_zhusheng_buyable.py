# -*- coding: utf-8 -*-
"""复盘认主升 · 叠加「次日买得到」硬约束。

用户口径：
  - 开盘板也没事
  - 只要不是 **全天一字** 就算买得到
  - 选对主升但次日全天一字 → 实盘仍失败

指标（有 GT 的节点上）：
  hit          选中 GT
  hit_buyable  选中 GT 且 T+1 非全天一字
  unbuyable    选了，但 T+1 是全天一字（含点对点错）
  wrong_buy    选错且可买（白买）
  abstain      弃权
  unknown      次日 OHLC 判不出一字
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from eval_zhusheng_strategies import STRATS, build_nodes as build_nodes_base

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT = ROOT / "data" / "kaipanla" / "ladder_daily" / "zhusheng_buyable_race.md"

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
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        _bars[code] = d.get("bars") or {}
    except Exception:
        _bars[code] = {}
    return _bars[code]


def is_all_day_yizi_ohlc(open_v, high_v, low_v, close_v, tol: float = 0.02) -> bool | None:
    """全天一字：开高低收几乎同一价（开盘板若盘中打开则 low 会下来 → 可买）。"""
    if None in (open_v, high_v, low_v, close_v):
        return None
    try:
        o, h, low, c = float(open_v), float(high_v), float(low_v), float(close_v)
    except (TypeError, ValueError):
        return None
    if min(o, h, low, c) <= 0:
        return None
    # 相对容差：价格越高 tol 用比例
    band = max(tol, abs(c) * 0.0015)
    return (
        abs(o - c) <= band
        and abs(h - c) <= band
        and abs(low - c) <= band
        and abs(h - low) <= band
    )


def t1_buyable(code: str, t1: str, pools_m: dict) -> tuple[bool | None, str]:
    """
    Returns (buyable, reason)
      True  = 非全天一字，买得到（含开盘板后打开、换手、未涨停等）
      False = 全天一字
      None  = 缺数据
    """
    code = str(code).zfill(6)
    b = load_bars(code).get(t1)
    open_v = high_v = low_v = close_v = None
    if b:
        open_v, high_v, low_v, close_v = (
            b.get("open"),
            b.get("high"),
            b.get("low"),
            b.get("close"),
        )
    s1 = pools_m.get(t1, {}).get(code)
    if s1 is not None:
        # 业务一字优先（开盘啦 9:25 + amp）
        if bt.is_yizi(s1):
            # 若 OHLC 显示盘中打开，以 OHLC 为准（T 字开板回封可买）
            y = is_all_day_yizi_ohlc(
                open_v if open_v is not None else s1.get("open"),
                high_v if high_v is not None else s1.get("high"),
                low_v if low_v is not None else s1.get("low"),
                close_v if close_v is not None else s1.get("price"),
            )
            if y is True:
                return False, "t1_all_day_yizi"
            if y is False:
                return True, "t1_opened_or_t_board"
            # OHLC 缺：信 is_yizi
            return False, "t1_yizi_flag_no_ohlc"
        open_v = open_v if open_v is not None else s1.get("open")
        high_v = high_v if high_v is not None else s1.get("high")
        low_v = low_v if low_v is not None else s1.get("low")
        close_v = close_v if close_v is not None else s1.get("price")

    y = is_all_day_yizi_ohlc(open_v, high_v, low_v, close_v)
    if y is True:
        return False, "t1_all_day_yizi_ohlc"
    if y is False:
        return True, "t1_has_range"
    # 不在涨停池且无 OHLC：保守当可买？未知更稳
    if s1 is None and b is None:
        return None, "missing_t1_data"
    if s1 is None:
        # 有 bar 但 y 为 None 极少；有 bar 已处理
        return True, "not_in_zt_assume_buyable"
    return None, "unknown"


def enrich_nodes():
    """在 strategies 节点上挂 T1、以及每票 buyable。"""
    days, pools, pools_m = bt.load_days()
    day_i = {d: i for i, d in enumerate(days)}
    nodes = build_nodes_base()
    for node in nodes:
        T = node["T"]
        i = day_i[T]
        t1 = days[i + 1] if i + 1 < len(days) else None
        node["T1"] = t1
        for c in node["cands"]:
            if not t1:
                c["buyable_t1"] = None
                c["buy_reason"] = "no_t1"
                continue
            ok, reason = t1_buyable(c["code"], t1, pools_m)
            c["buyable_t1"] = ok
            c["buy_reason"] = reason
        gt = node.get("gt")
        if gt and t1:
            ok, reason = t1_buyable(gt["code"], t1, pools_m)
            gt["buyable_t1"] = ok
            gt["buy_reason"] = reason
    return nodes


def main() -> int:
    nodes = enrich_nodes()
    n_gt = sum(1 for n in nodes if n["gt"])
    gt_buy = sum(1 for n in nodes if n["gt"] and n["gt"].get("buyable_t1") is True)
    gt_yizi = sum(1 for n in nodes if n["gt"] and n["gt"].get("buyable_t1") is False)
    gt_unk = sum(1 for n in nodes if n["gt"] and n["gt"].get("buyable_t1") is None)

    results = {}
    for sid, name, fn in STRATS:
        hit = hit_buy = wrong = unbuy = abstain = unk = 0
        for node in nodes:
            gt = node["gt"]
            if gt is None:
                continue
            pick = fn(node["cands"], node)
            if pick is None:
                abstain += 1
                continue
            # 对齐 buyable（pick 可能是 cands 引用）
            pc = next((c for c in node["cands"] if c["code"] == pick["code"]), pick)
            buy = pc.get("buyable_t1")
            if buy is None:
                unk += 1
            elif buy is False:
                unbuy += 1
            if pick["code"] == gt["code"]:
                hit += 1
                if buy is True:
                    hit_buy += 1
            else:
                wrong += 1
        L = hit + wrong + abstain  # labeled with decision; unk/unbuy overlap hit/wrong
        # note: unbuy counted within hit+wrong
        results[sid] = {
            "name": name,
            "hit": hit,
            "hit_buyable": hit_buy,
            "wrong": wrong,
            "unbuyable": unbuy,
            "unknown": unk,
            "abstain": abstain,
            "labeled": L,
            "hit_rate": hit / L if L else 0,
            "hit_buy_rate": hit_buy / L if L else 0,
            "unbuy_rate": unbuy / L if L else 0,
        }

    human = {
        "2025-10-30": "合富中国",
        "2025-11-10": "孚日股份",
        "2025-11-21": "梦天家居",
        "2025-12-04": "安记食品",
        "2026-03-19": "华电辽能",
    }

    lines = [
        "# 复盘认主升 · 次日买得到（非全天一字）",
        "",
        "口径：**开盘板可以买；全天一字买不到。**",
        "",
        f"节点 {len(nodes)}，有 GT **{n_gt}** 天。",
        f"GT 本身次日：可买 **{gt_buy}** / 全天一字 **{gt_yizi}** / 未知 **{gt_unk}**。",
        "",
        "| 策略 | hit | hit且可买 | wrong | 选中却全天一字 | abstain | 点对率 | **可买点对率** |",
        "|------|-----|-----------|-------|----------------|---------|--------|----------------|",
    ]
    ranked = sorted(
        results.items(),
        key=lambda x: (-x[1]["hit_buyable"], -x[1]["hit"], x[1]["unbuyable"]),
    )
    for sid, r in ranked:
        L = r["labeled"] or 1
        lines.append(
            f"| **{sid}** {r['name']} | {r['hit']} | **{r['hit_buyable']}** | {r['wrong']} | "
            f"{r['unbuyable']} | {r['abstain']} | {r['hit']/L:.1%} | **{r['hit_buyable']/L:.1%}** |"
        )

    lines += ["", "## 人工案例（名 / 次日可买?）", ""]
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
                continue
            pc = next((c for c in node["cands"] if c["code"] == p["code"]), p)
            mark = "✓" if p["name"] == uname else "×" + (p["name"] or "")[:4]
            b = pc.get("buyable_t1")
            if b is True:
                tag = "买"
            elif b is False:
                tag = "一字"
            else:
                tag = "?"
            cells.append(f"{mark}/{tag}")
        lines.append(f"| {T} | {uname} | " + " | ".join(cells) + " |")

    # D 策略：点对但买不到 明细
    d_fn = next(fn for sid, _, fn in STRATS if sid.startswith("D_"))
    lines += ["", "## D 策略：点对主升但次日全天一字（白点）", ""]
    n_white = 0
    for node in nodes:
        gt = node["gt"]
        if not gt:
            continue
        p = d_fn(node["cands"], node)
        if not p or p["code"] != gt["code"]:
            continue
        pc = next((c for c in node["cands"] if c["code"] == p["code"]), p)
        if pc.get("buyable_t1") is False:
            n_white += 1
            lines.append(
                f"- {node['T']}→{node.get('T1')} **{p['name']}** "
                f"{p['boards']}板 yizi_T={p.get('yizi')} ({pc.get('buy_reason')})"
            )
    if n_white == 0:
        lines.append("- （无）")

    lines += [
        "",
        "## 结论",
        "",
        "- 排序主键改为 **hit且可买**（次日非全天一字）。",
        "- 选中全天一字 = 实盘废票，即使名字点对。",
        "- GT 若本身次日一字：认主升对了也买不到 → 应改报层内可买空间票或弃权。",
        "",
        "脚本：`scripts/_scratch/eval_zhusheng_buyable.py`",
    ]

    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
