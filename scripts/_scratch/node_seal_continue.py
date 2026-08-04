# -*- coding: utf-8 -*-
"""节点日定锚 → 赚钱结构口径（不做溢价）：

① 封板率：T+1 摸到过涨停的票中，收盘仍封住的比例
   - 分母 = 摸板（high 触及涨停价，容差）
   - 分子 = 封板（收盘仍在涨停 / 在涨停池且 boards=T+1）
   - 没摸到涨停的 **不进分母**

② 连板率：锚集合内，T+1 严格连板晋级（boards = T日 boards+1 且在涨停池）
   - 分母 = 锚集合全部票（这是「这层有多少能连上」）
   - 另报：摸板条件下的连板 ≈ 与封板接近（连板晋级通常即封板）

数据：优先 ohlc_cache；缺则用 T+1 zt_pool 的 high/close/prev；
再缺则仅「在 T+1 涨停池」视为摸板且封板（无法识别炸板）。
"""
from __future__ import annotations

import json
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bt", Path(__file__).resolve().parent / "backtest_main_ladder.py"
)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "kaipanla" / "ohlc_cache"
OUT = ROOT / "data" / "kaipanla" / "ladder_daily" / "node_seal_continue.md"

_cache_mem: dict[str, dict] = {}


def load_bars(code: str) -> dict:
    if code in _cache_mem:
        return _cache_mem[code]
    p = CACHE / f"{code}.json"
    if not p.exists():
        _cache_mem[code] = {}
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8-sig"))
        bars = d.get("bars") or {}
        _cache_mem[code] = bars
        return bars
    except Exception:
        _cache_mem[code] = {}
        return {}


def bar_on(code: str, day: str) -> dict | None:
    bars = load_bars(code)
    b = bars.get(day)
    if b:
        return b
    return None


def limit_pct_for(code: str, name: str = "") -> float:
    """主板约 10%，ST 5%，创业/科创 20% 粗判。"""
    c = code
    if name and ("ST" in name or "st" in name or "S" == name[:1]):
        return 5.0
    if c.startswith(("300", "301", "688", "689")):
        return 20.0
    return 10.0


def touch_and_seal(code: str, name: str, day_t1: str, pools_m: dict, boards_t: int):
    """返回 (touched, sealed, source, continue_board)

    touched: 摸到涨停
    sealed: 收盘封住
    continue_board: boards_T+1 == boards_T+1 且在涨停池（连板）
    """
    s1 = pools_m.get(day_t1, {}).get(code)
    bar = bar_on(code, day_t1)

    # 连板晋级
    cont = False
    if s1 is not None:
        b1 = int(s1.get("boards") or 0)
        cont = b1 == boards_t + 1

    # 有 OHLC bar
    if bar and bar.get("high") is not None and bar.get("prev_close"):
        try:
            high = float(bar["high"])
            close = float(bar["close"])
            prev = float(bar["prev_close"])
            if prev <= 0:
                raise ValueError("prev")
            lp = limit_pct_for(code, name)
            # 涨停价近似：prev * (1+lp/100)，容差 0.5% 相对或 1 分钱
            limit_px = prev * (1.0 + lp / 100.0)
            # 有些收盘价四舍五入
            tol = max(prev * 0.003, 0.02)
            touched = high + 1e-9 >= limit_px - tol
            sealed = close + 1e-9 >= limit_px - tol
            # 若在涨停池且 cont，强制 sealed/touched
            if s1 is not None and cont:
                touched, sealed = True, True
            elif s1 is not None and int(s1.get("boards") or 0) >= 1:
                # 在涨停池 = 至少封住收盘
                touched, sealed = True, True
            return touched, sealed, "ohlc", cont
        except Exception:
            pass

    # zt_pool 当日有 high/close/prev
    if s1 is not None:
        try:
            high = s1.get("high")
            close = s1.get("price") or s1.get("close")
            prev = s1.get("prev_close")
            if high is not None and prev is not None:
                high, close, prev = float(high), float(close), float(prev)
                lp = float(s1.get("limit_pct") or limit_pct_for(code, name))
                # limit_pct 有时是已实现涨幅不是上限
                lim = limit_pct_for(code, name)
                limit_px = prev * (1.0 + lim / 100.0)
                tol = max(prev * 0.003, 0.02)
                touched = high + 1e-9 >= limit_px - tol
                sealed = True  # 在涨停池即收盘涨停
                return True, True, "zt_pool", cont
        except Exception:
            pass
        # 在涨停池无完整 OHLC：视为摸板且封板
        return True, True, "zt_only", cont

    # 不在涨停池、无 bar：无法判断摸板 → 排除（不算分母）
    if bar is None:
        return None, None, "no_data", cont

    return False, False, "ohlc_no_touch", cont


def today_nat(stocks, day):
    h, highs = bt.natural_max(stocks, day)
    return h, list(highs)


def pick_sets(stocks, day, dead_h):
    th, tlayer = today_nat(stocks, day)
    lad = bt.pick_ladder(stocks, day)
    down_stocks = [s for s in stocks if s["code"] in (lad.get("members") or set())]
    top_stocks = tlayer
    top_codes = {s["code"] for s in top_stocks}

    def dual(gate):
        if gate and top_stocks:
            codes = top_codes | {s["code"] for s in down_stocks}
            return [s for s in stocks if s["code"] in codes]
        return list(down_stocks)

    near_thin = bool(tlayer) and th >= max((dead_h or 0) - 1, 2) and len(tlayer) <= 2
    sets = {
        "down": down_stocks,
        "nat_max": top_stocks,
        "dual_near_thin": dual(near_thin),
        "dual_always": dual(bool(tlayer)),
    }
    if len(tlayer) == 1 and not bt.is_yizi(tlayer[0]):
        sets["fanpu_else_down"] = list(tlayer)
    else:
        sets["fanpu_else_down"] = list(down_stocks)
    return sets


def main() -> int:
    days, pools, pools_m = bt.load_days()

    keys = ["down", "nat_max", "dual_near_thin", "dual_always", "fanpu_else_down"]
    zh = {
        "down": "纯往下锚",
        "nat_max": "纯今日自然最高",
        "dual_near_thin": "dual近死绝n≤2",
        "dual_always": "dual有顶就并",
        "fanpu_else_down": "独苗无一字用顶否则往下",
    }
    st = {
        k: {
            "nodes": 0,
            "n_all": 0,  # 锚内全部
            "n_touch": 0,  # 摸板
            "n_seal": 0,  # 摸板且封
            "n_cont": 0,  # 连板晋级
            "n_no_data": 0,
            "n_no_touch": 0,
            "node_touch": 0,
            "node_seal_given_touch_sum": 0.0,
            "node_cont_sum": 0.0,
            "node_any_cont": 0,
        }
        for k in keys
    }

    KNOWN = {
        "2025-12-24": "神剑股份",
        "2026-04-01": "津药药业",
        "2026-04-10": "华远控股",
        "2026-07-20": "立新能源",
    }
    known_rows = []

    for i in range(1, len(days) - 1):
        prev, cur = days[i - 1], days[i]
        t1 = days[i + 1]
        ok, dead_h, dead, _ = bt.is_high_tier_dead(
            pools[prev], set(pools_m[cur].keys()), prev
        )
        if not ok:
            continue

        sets = pick_sets(pools[cur], cur, dead_h)
        for name, members in sets.items():
            if not members:
                continue
            a = st[name]
            a["nodes"] += 1
            touch_n = seal_n = cont_n = 0
            touch_den = 0
            for s in members:
                a["n_all"] += 1
                b0 = int(s.get("boards") or 0)
                touched, sealed, src, cont = touch_and_seal(
                    s["code"], s.get("name") or "", t1, pools_m, b0
                )
                if cont:
                    a["n_cont"] += 1
                    cont_n += 1
                if touched is None:
                    a["n_no_data"] += 1
                    continue
                if not touched:
                    a["n_no_touch"] += 1
                    continue
                # 摸板
                a["n_touch"] += 1
                touch_den += 1
                touch_n += 1
                if sealed:
                    a["n_seal"] += 1
                    seal_n += 1

            a["node_cont_sum"] += cont_n / len(members)
            if cont_n > 0:
                a["node_any_cont"] += 1
            if touch_den > 0:
                a["node_touch"] += 1
                a["node_seal_given_touch_sum"] += seal_n / touch_den

        if cur in KNOWN:
            kn = KNOWN[cur]
            for s in pools[cur]:
                if s["name"] != kn:
                    continue
                b0 = int(s.get("boards") or 0)
                touched, sealed, src, cont = touch_and_seal(
                    s["code"], kn, t1, pools_m, b0
                )
                known_rows.append(
                    {
                        "T": cur,
                        "name": kn,
                        "b": b0,
                        "touched": touched,
                        "sealed": sealed,
                        "cont": cont,
                        "src": src,
                    }
                )
                break

    lines = [
        "# 节点日定锚：封板率（条件摸板）+ 连板率",
        "",
        "**口径**",
        "",
        "- **① 封板率** = `#封板 / #摸到涨停`（T+1）",
        "  - 摸板：日 K `high` 触及涨停价（容差）；或 T+1 在涨停池",
        "  - 封板：收盘仍在涨停（close 触及涨停价 / 在涨停池）",
        "  - **没摸到涨停的不进分母**；无 OHLC 且不在池 → 记 no_data，不进分母",
        "- **② 连板率** = `#T+1 boards=T+1 且在涨停池 / #锚集合全部票`",
        "  - 表示锚层里有多少能成功晋级连板",
        "",
        "不定票；集合内股票等权。不做溢价。",
        "",
        "## 总表",
        "",
        "| 策略 | 节点 | 票次 | 摸板n | ①封板率(封/摸) | 未摸板 | 无数据 | ②连板率(连/全) | 节点均连板率 | 节点≥1连 |",
        "|------|------|------|-------|----------------|--------|--------|----------------|--------------|----------|",
    ]

    for k in keys:
        a = st[k]
        touch = a["n_touch"] or 0
        seal_r = a["n_seal"] / touch if touch else 0
        cont_r = a["n_cont"] / a["n_all"] if a["n_all"] else 0
        nn = a["nodes"] or 1
        lines.append(
            f"| **{k}** {zh[k]} | {a['nodes']} | {a['n_all']} | {touch} | "
            f"{a['n_seal']}/{touch}={seal_r:.1%} | {a['n_no_touch']} | {a['n_no_data']} | "
            f"{a['n_cont']}/{a['n_all']}={cont_r:.1%} | "
            f"{a['node_cont_sum']/nn:.1%} | {a['node_any_cont']/nn:.1%} |"
        )

    lines += [
        "",
        "## 读法",
        "",
        "- **封板率高**：摸到板以后不容易炸，偏「打板质量」",
        "- **连板率高**：锚层里晋级多，偏「这层还能往上推」",
        "- 二者分母不同：封板只看摸板子集；连板看整层",
        "- 纯最高层通常票少、强度高 → 封板/连板可能都好看，但覆盖窄",
        "- 往下/ dual 票多 → 连板率会被弱票拉低（定锚阶段正常）",
        "",
        "## 四案本人（T+1）",
        "",
        "| T | 票 | T板 | 摸板 | 封板 | 连板 | 数据源 |",
        "|---|-----|-----|------|------|------|--------|",
    ]
    for r in known_rows:
        lines.append(
            f"| {r['T']} | {r['name']} | {r['b']} | {r['touched']} | {r['sealed']} | "
            f"{r['cont']} | {r['src']} |"
        )

    # ranking blurb
    lines.append("")
    lines.append("## 简比（按封板率 / 连板率）")
    lines.append("")
    rank_seal = sorted(
        keys,
        key=lambda k: (st[k]["n_seal"] / st[k]["n_touch"]) if st[k]["n_touch"] else 0,
        reverse=True,
    )
    rank_cont = sorted(
        keys,
        key=lambda k: (st[k]["n_cont"] / st[k]["n_all"]) if st[k]["n_all"] else 0,
        reverse=True,
    )
    lines.append(
        "- 封板率排序: "
        + " > ".join(
            f"{k}({st[k]['n_seal']/st[k]['n_touch']:.0%})"
            if st[k]["n_touch"]
            else k
            for k in rank_seal
        )
    )
    lines.append(
        "- 连板率排序: "
        + " > ".join(
            f"{k}({st[k]['n_cont']/st[k]['n_all']:.0%})"
            if st[k]["n_all"]
            else k
            for k in rank_cont
        )
    )

    text = "\n".join(lines)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
