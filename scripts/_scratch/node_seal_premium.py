# -*- coding: utf-8 -*-
"""节点日定锚 → 赚钱口径：
1) 次日(T+1) 打板封板率：锚集合内票 T+1 是否涨停封板（在涨停池且 boards=昨+1，或至少在涨停池）
2) 封板后次日溢价：T+1 封板成功的票，看 T+2 的 open_pct

比较：纯往下 / 纯今日最高 / dual 近死绝薄层 / dual always
锚集合不定票：对集合内每票等权；同时报「层内额Top1」作对照（仍非定票主结论）
"""
from __future__ import annotations

import importlib.util
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

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
    / "node_seal_premium.md"
)


def today_nat(stocks, day):
    h, highs = bt.natural_max(stocks, day)
    return h, list(highs)


def top_gate_near_thin(h, layer, dead_h):
    return bool(layer) and h >= max((dead_h or 0) - 1, 2) and len(layer) <= 2


def top_gate_always(h, layer, dead_h):
    return bool(layer)


def pick_sets(stocks, day, dead_h):
    th, tlayer = today_nat(stocks, day)
    lad = bt.pick_ladder(stocks, day)
    down = {s["code"]: s for s in stocks if s["code"] in (lad.get("members") or set())}
    # rebuild down from members
    down_stocks = [s for s in stocks if s["code"] in (lad.get("members") or set())]
    top_stocks = tlayer
    top_codes = {s["code"] for s in top_stocks}

    sets = {
        "down": down_stocks,
        "nat_max": top_stocks,
    }
    # dual near thin
    if top_gate_near_thin(th, tlayer, dead_h):
        codes = top_codes | {s["code"] for s in down_stocks}
        sets["dual_near_thin"] = [s for s in stocks if s["code"] in codes]
    else:
        sets["dual_near_thin"] = list(down_stocks)
    # dual always
    if top_stocks:
        codes = top_codes | {s["code"] for s in down_stocks}
        sets["dual_always"] = [s for s in stocks if s["code"] in codes]
    else:
        sets["dual_always"] = list(down_stocks)
    # fanpu sole no yizi only top else down
    if len(tlayer) == 1 and not bt.is_yizi(tlayer[0]):
        sets["fanpu_else_down"] = list(tlayer)
    else:
        sets["fanpu_else_down"] = list(down_stocks)
    return sets, th, lad


def sealed_next(s_t, pools_m, day_t1):
    """T+1 封板：在涨停池，且 boards == boards_T+1（连板晋级）或 boards>=1 且涨停。
    主口径：在 T+1 涨停池 且 boards == boards_T + 1
    辅：在 T+1 涨停池（含断板后再首板，偏松）
    """
    code = s_t["code"]
    b0 = int(s_t.get("boards") or 0)
    s1 = pools_m.get(day_t1, {}).get(code)
    if not s1:
        return False, False, None
    b1 = int(s1.get("boards") or 0)
    strict = b1 == b0 + 1
    loose = True  # in pool
    return strict, loose, s1


def open_pct_of(s):
    v = s.get("open_pct")
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def main():
    days, pools, pools_m = bt.load_days()
    day_i = {d: i for i, d in enumerate(days)}

    # per strategy accumulators
    # equal-weight each stock-day in anchor set
    st = {
        k: {
            "n_stock": 0,
            "seal_strict": 0,
            "seal_loose": 0,
            "prem_list": [],  # T+2 open_pct after T+1 strict seal
            "prem_missing": 0,
            "nodes": 0,
            "node_any_seal": 0,  # 节点层内至少一只严格封板
            "node_seal_rate_sum": 0.0,  # 节点内等权封板率再平均
            "node_prem_means": [],
            # top1 by amount on T
            "top1_n": 0,
            "top1_seal": 0,
            "top1_prem": [],
        }
        for k in (
            "down",
            "nat_max",
            "dual_near_thin",
            "dual_always",
            "fanpu_else_down",
        )
    }

    # known cases detail
    KNOWN = {
        "2025-12-24": "神剑股份",
        "2026-04-01": "津药药业",
        "2026-04-10": "华远控股",
        "2026-07-20": "立新能源",
    }
    known_rows = []

    for i in range(1, len(days) - 2):  # need T+1 and T+2
        prev, cur = days[i - 1], days[i]
        t1, t2 = days[i + 1], days[i + 2]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue

        sets, th, lad = pick_sets(pools[cur], cur, dead_h)

        for name, members in sets.items():
            if not members:
                continue
            acc = st[name]
            acc["nodes"] += 1
            seals = 0
            prems_node = []
            for s in members:
                acc["n_stock"] += 1
                strict, loose, s1 = sealed_next(s, pools_m, t1)
                if loose:
                    acc["seal_loose"] += 1
                if strict:
                    acc["seal_strict"] += 1
                    seals += 1
                    # T+2 open_pct：封板后次日溢价
                    s2 = pools_m.get(t2, {}).get(s["code"])
                    # 溢价用 T+2 开盘相对 T+1 收盘；若 T+2 不在涨停池，ohlc 可能仍在别的地方？
                    # zt_pool 仅涨停票有 open_pct。未涨停则无 T+2 池里没有。
                    # 尝试：若 s2 在池，用 s2.open_pct；否则无法从 zt_pool 取（非涨停无 open_pct）
                    if s2 is not None:
                        op = open_pct_of(s2)
                        if op is not None:
                            acc["prem_list"].append(op)
                            prems_node.append(op)
                        else:
                            acc["prem_missing"] += 1
                    else:
                        # 未连上 T+2 涨停：用不到池内 open_pct。
                        # 若 T+1 收盘价与 T+2 有数据——zt 没有非涨停。记 missing。
                        # 但「封板后次日溢价」即使低开不涨停也有溢价；需要 OHLC。
                        # 回退：读 raw T+2 若无该股，尝试用 T+1 的 price 与… 无 T+2 bar。
                        acc["prem_missing"] += 1

            rate = seals / len(members)
            acc["node_seal_rate_sum"] += rate
            if seals > 0:
                acc["node_any_seal"] += 1
            if prems_node:
                acc["node_prem_means"].append(mean(prems_node))

            # top1 amount
            top1 = max(members, key=lambda x: (bt.amount_yi(x) or 0))
            acc["top1_n"] += 1
            strict, _, s1 = sealed_next(top1, pools_m, t1)
            if strict:
                acc["top1_seal"] += 1
                s2 = pools_m.get(t2, {}).get(top1["code"])
                if s2 is not None:
                    op = open_pct_of(s2)
                    if op is not None:
                        acc["top1_prem"].append(op)

        # known
        if cur in KNOWN:
            kn = KNOWN[cur]
            for s in pools[cur]:
                if s["name"] == kn:
                    strict, _, s1 = sealed_next(s, pools_m, t1)
                    s2 = pools_m.get(t2, {}).get(s["code"])
                    op = open_pct_of(s2) if s2 else None
                    known_rows.append(
                        {
                            "T": cur,
                            "name": kn,
                            "b": s["boards"],
                            "seal": strict,
                            "t2_open_pct": op,
                            "in_down": s["code"]
                            in (lad.get("members") or set()),
                            "in_top": any(
                                x["name"] == kn for x in today_nat(pools[cur], cur)[1]
                            ),
                        }
                    )
                    break

    # Also try fill premium from any day file - if stock not limit up T+2, check if we have ohlc elsewhere
    # Improve: for sealed T+1, get T+2 open_pct from stock if present on ANY - actually need non-zt ohlc
    # Check ohlc cache
    ohlc_root = Path("data/kaipanla")
    # search for ohlc json patterns
    ohlc_files = list(ohlc_root.rglob("*ohlc*"))[:5]

    lines = []
    lines.append("# 节点日定锚：次日封板率 + 封板后次日溢价\n")
    lines.append("**口径（赚钱，不是最高板）**\n")
    lines.append("- 节点日 T 定锚集合（等权看集合内每只，**不定票**）\n")
    lines.append(
        "- **① 次日封板率**：T+1 仍在涨停池且 `boards = T日boards+1`（连板晋级封死）\n"
    )
    lines.append(
        "- **② 封板后次日溢价**：T+1 严格封板成功的票，取 **T+2 的 open_pct**"
        "（开盘溢价%；目前仅当 T+2 仍能在涨停池取到 OHLC 时有值，"
        "低开未涨停者 open_pct 可能缺失，见下）\n"
    )
    lines.append(f"- 节点样本：需存在 T+1、T+2 交易日\n")
    lines.append(f"- ohlc 相关文件样例：{[str(p) for p in ohlc_files]}\n")

    names_zh = {
        "down": "纯往下锚",
        "nat_max": "纯今日自然最高",
        "dual_near_thin": "dual 近死绝且n≤2",
        "dual_always": "dual 有顶就并",
        "fanpu_else_down": "独苗无一字用顶否则往下",
    }

    lines.append("## 总表（股票·次 等权）\n")
    lines.append(
        "| 策略 | 节点 | 票次 | ①严格封板率 | 松封板(在池) | ②溢价样本n | 溢价均值 | 溢价中位 | 节点层内封板率均值 | 节点至少1只封 |"
    )
    lines.append("|------|------|------|-------------|--------------|------------|----------|----------|-------------------|---------------|")

    for k, zh in names_zh.items():
        a = st[k]
        ns = a["n_stock"] or 1
        nn = a["nodes"] or 1
        seal_r = a["seal_strict"] / ns
        loose_r = a["seal_loose"] / ns
        pl = a["prem_list"]
        prem_m = mean(pl) if pl else None
        prem_med = median(pl) if pl else None
        node_seal_avg = a["node_seal_rate_sum"] / nn
        any_r = a["node_any_seal"] / nn
        lines.append(
            f"| **{k}** {zh} | {a['nodes']} | {a['n_stock']} | "
            f"{a['seal_strict']}/{a['n_stock']}={seal_r:.1%} | {loose_r:.1%} | "
            f"{len(pl)} (缺{a['prem_missing']}) | "
            f"{'' if prem_m is None else f'{prem_m:.2f}%'} | "
            f"{'' if prem_med is None else f'{prem_med:.2f}%'} | "
            f"{node_seal_avg:.1%} | {any_r:.1%} |"
        )

    lines.append("\n## 对照：锚层内成交额 Top1（仍非定票结论）\n")
    lines.append("| 策略 | Top1封板率 | Top1溢价n | 溢价均值 | 溢价中位 |")
    lines.append("|------|-----------|-----------|----------|----------|")
    for k, zh in names_zh.items():
        a = st[k]
        n = a["top1_n"] or 1
        pl = a["top1_prem"]
        lines.append(
            f"| {k} | {a['top1_seal']}/{a['top1_n']}={a['top1_seal']/n:.1%} | "
            f"{len(pl)} | "
            f"{'' if not pl else f'{mean(pl):.2f}%'} | "
            f"{'' if not pl else f'{median(pl):.2f}%'} |"
        )

    lines.append("\n## 四案：真主升本人的封板与溢价\n")
    lines.append("| T | 票 | T板 | T+1严格封板 | T+2 open_pct | 在往下 | 在最高 |")
    lines.append("|---|-----|-----|-------------|--------------|--------|--------|")
    for r in known_rows:
        lines.append(
            f"| {r['T']} | {r['name']} | {r['b']} | {'Y' if r['seal'] else 'N'} | "
            f"{r['t2_open_pct'] if r['t2_open_pct'] is not None else 'NA'} | "
            f"{'Y' if r['in_down'] else 'N'} | {'Y' if r['in_top'] else 'N'} |"
        )

    # Distribution of premiums for down vs nat_max
    lines.append("\n## 溢价分布粗看（严格封板且有 T+2 open_pct）\n")
    for k in ("down", "nat_max", "dual_near_thin"):
        pl = sorted(st[k]["prem_list"])
        if not pl:
            continue
        def pct(p):
            if not pl:
                return None
            i = int(round((len(pl) - 1) * p))
            return pl[i]
        ge5 = sum(1 for x in pl if x >= 5) / len(pl)
        ge9 = sum(1 for x in pl if x >= 9) / len(pl)
        lt0 = sum(1 for x in pl if x < 0) / len(pl)
        lines.append(
            f"- **{k}** n={len(pl)}: p25={pct(0.25):.1f}% p50={pct(0.5):.1f}% "
            f"p75={pct(0.75):.1f}% | ≥5%占{ge5:.0%} ≥9%占{ge9:.0%} 低开<0占{lt0:.0%}"
        )

    lines.append("\n## 读法（先定锚）\n")
    lines.append(
        "1. **① 封板率**高 = 锚层里次日更能连上，偏「能打板做接力」\n"
        "2. **② 溢价**高 = 连上之后次日开盘更给分，偏「封板后收益空间」\n"
        "3. 两套策略可能一个封板高、一个溢价高——对应不同赚钱段，不必合成一个命中率\n"
        "4. 溢价缺失：T+2 未涨停时 zt_pool 无 open_pct，会低估「烂板/低开」样本；"
        "若要完整溢价需非涨停 OHLC（东财日线已有能力可补）\n"
    )

    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
