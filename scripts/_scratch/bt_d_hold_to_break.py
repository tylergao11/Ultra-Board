# -*- coding: utf-8 -*-
"""D 策略买法回测：节点日选股 → T+1 开盘买（非全天一字）→ 持有到该票断板日收盘。

断板日 = 进场日及之后，首次不在涨停池的交易日（尾盘收盘价出场）。
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

from eval_zhusheng_strategies import STRATS
from eval_zhusheng_buyable import enrich_nodes

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT = ROOT / "data" / "kaipanla" / "ladder_daily" / "bt_d_hold_to_break.md"


def bar(code: str, day: str) -> dict | None:
    code = str(code).zfill(6)
    p = CACHE / f"{code}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        return (d.get("bars") or {}).get(day)
    except Exception:
        return None


def main() -> int:
    days, pools, pools_m = bt.load_days()
    day_i = {d: i for i, d in enumerate(days)}
    fn = next(f for sid, _, f in STRATS if sid.startswith("D_"))
    nodes = enrich_nodes()

    trades: list[dict] = []
    for n in nodes:
        T = n["T"]
        T1 = n.get("T1")
        if not T1:
            continue
        cands = n["cands"]
        if not cands:
            continue
        p = fn(cands, n)
        if not p:
            continue
        pc = next((c for c in cands if c["code"] == p["code"]), p)
        buyable = pc.get("buyable_t1")
        code = str(p["code"]).zfill(6)
        name = p["name"]
        b0 = int(p["boards"])
        gt = n.get("gt")
        hit = bool(gt and gt["code"] == p["code"])

        if buyable is False:
            trades.append(
                {
                    "T": T,
                    "T1": T1,
                    "name": name,
                    "code": code,
                    "status": "skip_yizi",
                    "hit": hit,
                    "b0": b0,
                }
            )
            continue
        if buyable is None:
            trades.append(
                {
                    "T": T,
                    "T1": T1,
                    "name": name,
                    "code": code,
                    "status": "skip_unknown",
                    "hit": hit,
                    "b0": b0,
                }
            )
            continue

        b1 = bar(code, T1)
        entry = None
        if b1 and b1.get("open") is not None:
            entry = float(b1["open"])
        else:
            s1 = pools_m.get(T1, {}).get(code)
            if s1 and s1.get("open") is not None:
                entry = float(s1["open"])
        if entry is None or entry <= 0:
            trades.append(
                {
                    "T": T,
                    "T1": T1,
                    "name": name,
                    "code": code,
                    "status": "skip_no_price",
                    "hit": hit,
                    "b0": b0,
                }
            )
            continue

        # 断板日：T1 起首次不在涨停池
        i1 = day_i[T1]
        exit_day = None
        exit_close = None
        max_b = b0
        cont_days = 0
        for j in range(i1, len(days)):
            d = days[j]
            s = pools_m.get(d, {}).get(code)
            bb = bar(code, d)
            if s is not None:
                max_b = max(max_b, int(s.get("boards") or 0))
                cont_days += 1
                continue
            exit_day = d
            if bb and bb.get("close") is not None:
                exit_close = float(bb["close"])
            break
        else:
            exit_day = days[-1]
            bb = bar(code, exit_day)
            if bb and bb.get("close") is not None:
                exit_close = float(bb["close"])

        if exit_close is None or exit_day is None:
            trades.append(
                {
                    "T": T,
                    "T1": T1,
                    "name": name,
                    "code": code,
                    "status": "skip_no_exit",
                    "hit": hit,
                    "b0": b0,
                    "entry": entry,
                    "exit_day": exit_day,
                }
            )
            continue

        ret = exit_close / entry - 1.0
        trades.append(
            {
                "T": T,
                "T1": T1,
                "name": name,
                "code": code,
                "status": "ok",
                "hit": hit,
                "b0": b0,
                "entry": round(entry, 3),
                "exit_day": exit_day,
                "exit": round(exit_close, 3),
                "ret": ret,
                "max_b": max_b,
                "cont_days": cont_days,
            }
        )

    ok = [t for t in trades if t["status"] == "ok"]
    sk = [t for t in trades if t["status"] != "ok"]

    lines = [
        "# D 策略 · T+1 开盘买 → 断板日尾盘卖",
        "",
        "底座：断板节点 + 纯往下锚层 + 自然票；D = 一字钉 + 大额换手取空间。",
        "",
        "**买入**：信号日 T 收盘后定票，**T+1 开盘价**（全天一字跳过，买不到）。",
        "**卖出**：进场日起该票**首次不在涨停池**的交易日，**收盘价**。",
        "",
        f"- 信号 **{len(trades)}** 次，成交 **{len(ok)}**，跳过 **{len(sk)}**",
        f"- 跳过：`{dict(Counter(t['status'] for t in sk))}`",
        "",
    ]

    if ok:
        rets = [t["ret"] for t in ok]
        mean_r = statistics.mean(rets)
        med_r = statistics.median(rets)
        win = sum(1 for r in rets if r > 0) / len(rets)
        sum_r = sum(rets)

        sorted_ok = sorted(ok, key=lambda x: (x["T1"], x["code"]))
        # 连乘忽略重叠
        eq1 = 1.0
        for t in sorted_ok:
            eq1 *= 1 + t["ret"]

        # 无重叠满仓：持仓期不接新单
        eq2 = 1.0
        free_after = ""
        taken = []
        skip_ov = 0
        for t in sorted_ok:
            if free_after and t["T1"] <= free_after:
                skip_ov += 1
                continue
            eq2 *= 1 + t["ret"]
            free_after = t["exit_day"]
            taken.append(t)

        hit_ok = [t for t in ok if t["hit"]]
        miss_ok = [t for t in ok if not t["hit"]]

        lines += [
            "## 汇总",
            "",
            f"| 指标 | 值 |",
            f"|------|-----|",
            f"| 成交笔数 | {len(ok)} |",
            f"| 单笔平均收益 | **{mean_r*100:.2f}%** |",
            f"| 单笔中位 | {med_r*100:.2f}% |",
            f"| 胜率(>0) | {win*100:.1f}% |",
            f"| 每笔 1 份本金 · 简单加总 | **{sum_r*100:.1f}%** |",
            f"| 每笔满仓连乘(忽略重叠) | {(eq1-1)*100:.1f}% → {eq1:.3f}x |",
            f"| **无重叠满仓接力** | **{(eq2-1)*100:.1f}% → {eq2:.3f}x**（{len(taken)} 笔，重叠跳过 {skip_ov}） |",
            "",
        ]
        if hit_ok:
            hr = sum(t["ret"] for t in hit_ok) / len(hit_ok)
            lines.append(
                f"- 点对子集 n={len(hit_ok)} 平均 **{hr*100:.2f}%** 加总 {sum(t['ret'] for t in hit_ok)*100:.1f}%"
            )
        if miss_ok:
            mr = sum(t["ret"] for t in miss_ok) / len(miss_ok)
            lines.append(
                f"- 点错子集 n={len(miss_ok)} 平均 **{mr*100:.2f}%** 加总 {sum(t['ret'] for t in miss_ok)*100:.1f}%"
            )

        lines += [
            "",
            "## 成交明细",
            "",
            "| T | 买入日 | 断板卖出日 | 名称 | 进价 | 出价 | 收益% | 持仓涨停天 | 点对 |",
            "|---|--------|------------|------|------|------|-------|------------|------|",
        ]
        for t in sorted(ok, key=lambda x: x["T"]):
            lines.append(
                f"| {t['T']} | {t['T1']} | {t['exit_day']} | {t['name']} | "
                f"{t['entry']} | {t['exit']} | **{t['ret']*100:.1f}%** | {t['cont_days']} | "
                f"{'✓' if t['hit'] else '×'} |"
            )

        lines += [
            "",
            "## 无重叠接力路径",
            "",
            "| # | 买入 | 卖出 | 名称 | 收益% | 净值 |",
            "|---|------|------|------|-------|------|",
        ]
        eq = 1.0
        for i, t in enumerate(taken, 1):
            eq *= 1 + t["ret"]
            lines.append(
                f"| {i} | {t['T1']} | {t['exit_day']} | {t['name']} | "
                f"{t['ret']*100:.1f}% | {eq:.3f} |"
            )

    text = "\n".join(lines)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
