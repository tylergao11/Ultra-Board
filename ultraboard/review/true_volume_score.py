# -*- coding: utf-8 -*-
"""节点日真实爆量证据分：量的放大必须经过日内交互验证。

该分数不读取换手率，也不预测次日涨停。它把当前连续涨停路径中的成交额放大、
开盘到最低价的价格释放、炸板/回封过程拆开呈现，避免把加速途中堆出的成交额
误判成“换手完成”。

用法：

  python -m ultraboard.review.true_volume_score 2025-12-16 --fetch-missing
  python -m ultraboard.review.true_volume_score 2025-12-16 --code 001208
  python -m ultraboard.review.true_volume_score 2025-12-16 --format json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any

from ultraboard.kaipanla.ladder_evidence import (
    as_float,
    as_int,
    available_trade_days,
    code_of,
    raw_pool,
    raw_stock_map,
    seal_time,
)
from ultraboard.kaipanla.price_shapes import is_one_price
from ultraboard.kaipanla.ths_limit_pool import stock_map as ths_stock_map


POLICY_VERSION = "true_volume_v2_dual_shortfall"

# 这些是全局解释锚点，不是股票或日期特判。成交额每翻一倍增加 25 分；
# 炸板与最终封死前的活跃时长使用平滑饱和函数，避免某一次动作支配全部结果。
AMOUNT_SCORE_PER_DOUBLING = 25.0
OPEN_COUNT_SATURATION = 3.0
FINAL_SEAL_DELAY_SATURATION_SECONDS = 30.0 * 60.0
STRONG_EVIDENCE = 70.0
LOW_INTERACTION = 40.0

MORNING_START = 9 * 3600 + 30 * 60
MORNING_END = 11 * 3600 + 30 * 60
AFTERNOON_START = 13 * 3600
AFTERNOON_END = 15 * 3600
TOTAL_ACTIVE_SECONDS = (
    MORNING_END - MORNING_START + AFTERNOON_END - AFTERNOON_START
)


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def rounded(value: float | None) -> float | None:
    return None if value is None else round(clamp(value), 2)


def harmonic_mean(left: float | None, right: float | None) -> float | None:
    if left is None or right is None:
        return None
    if left <= 0.0 or right <= 0.0:
        return 0.0
    return 2.0 * left * right / (left + right)


def clock_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hour, minute, second = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        return None
    return hour * 3600 + minute * 60 + second


def active_clock(value: str | None) -> int | None:
    seconds = clock_seconds(value)
    if seconds is None:
        return None
    if seconds <= MORNING_START:
        return 0
    if seconds <= MORNING_END:
        return seconds - MORNING_START
    morning = MORNING_END - MORNING_START
    if seconds <= AFTERNOON_START:
        return morning
    if seconds <= AFTERNOON_END:
        return morning + seconds - AFTERNOON_START
    return TOTAL_ACTIVE_SECONDS


def price_pct(price: Any, previous_close: Any) -> float | None:
    current = as_float(price)
    previous = as_float(previous_close)
    if current is None or not previous:
        return None
    return (current / previous - 1.0) * 100.0


def consecutive_limit_sequence(
    day: str,
    code: str,
    height: int,
) -> tuple[list[dict[str, Any]], bool]:
    """回溯当前连续涨停路径，包含首板；只读取 ``day`` 及以前。"""
    expected = int(height)
    reverse_rows: list[dict[str, Any]] = []
    for route_day in reversed([item for item in available_trade_days() if item <= day]):
        stock = raw_stock_map(route_day).get(code)
        if stock is None:
            break
        actual = as_int(stock.get("boards"))
        if actual != expected:
            break
        reverse_rows.append({
            "date": route_day,
            "height": actual,
            "amount": as_float(stock.get("amount")),
            "first_seal": seal_time(stock.get("first_limit_ts")),
        })
        expected -= 1
        if expected == 0:
            break
    rows = list(reversed(reverse_rows))
    return rows, expected == 0


def amount_expansion(
    current_amount: float | None,
    sequence: list[dict[str, Any]],
) -> dict[str, Any]:
    priors = [
        float(row["amount"])
        for row in sequence[:-1]
        if as_float(row.get("amount")) not in (None, 0.0)
    ]
    if current_amount is None or not priors:
        return {
            "score": None,
            "current_amount": current_amount,
            "prior_reference_amount": None,
            "amount_ratio": None,
            "reference_contract": "当前连续涨停路径此前各板成交额最大值",
        }
    reference = max(priors)
    ratio = current_amount / reference if reference > 0 else None
    score = (
        clamp(50.0 + AMOUNT_SCORE_PER_DOUBLING * math.log2(ratio))
        if ratio and ratio > 0
        else 0.0
    )
    return {
        "score": rounded(score),
        "current_amount": current_amount,
        "prior_reference_amount": reference,
        "amount_ratio": round(ratio, 3) if ratio is not None else None,
        "reference_contract": "当前连续涨停路径此前各板成交额最大值",
    }


def price_interaction(stock: dict[str, Any]) -> dict[str, Any]:
    limit_pct = abs(as_float(stock.get("limit_pct")) or 0.0)
    open_pct = as_float(stock.get("open_pct"))
    low_pct = price_pct(stock.get("low"), stock.get("prev_close"))
    if not limit_pct or open_pct is None or low_pct is None:
        return {
            "score": None,
            "open_pct": open_pct,
            "low_pct": low_pct,
            "limit_pct": limit_pct or None,
            "downward_release": None,
            "bullish_body": None,
        }
    downward_release = clamp((open_pct - low_pct) / limit_pct, 0.0, 1.0)
    bullish_body = clamp((limit_pct - open_pct) / limit_pct, 0.0, 1.0)
    # 向下释放与长阳实体任一成立，都说明价格层面给出了筹码交互空间。
    discovery = max(downward_release, bullish_body)
    return {
        "score": rounded(discovery * 100.0),
        "open_pct": round(open_pct, 2),
        "low_pct": round(low_pct, 2),
        "limit_pct": round(limit_pct, 2),
        "downward_release": round(downward_release, 4),
        "bullish_body": round(bullish_body, 4),
    }


def board_interaction(ths: dict[str, Any] | None) -> dict[str, Any]:
    if not ths:
        return {
            "score": None,
            "first_seal": None,
            "final_seal": None,
            "open_count": None,
            "first_to_final_seconds": None,
            "final_seal_delay_seconds": None,
        }
    first_seal = seal_time(ths.get("first_limit_ts"))
    final_seal = seal_time(ths.get("final_limit_ts"))
    open_count = as_int(ths.get("open_count"))
    first_clock = active_clock(first_seal)
    final_clock = active_clock(final_seal)
    first_to_final = (
        max(0, final_clock - first_clock)
        if first_clock is not None and final_clock is not None
        else None
    )
    final_seal_delay = final_clock
    open_strength = (
        100.0 * (1.0 - math.exp(-open_count / OPEN_COUNT_SATURATION))
        if open_count is not None
        else None
    )
    delay_strength = (
        100.0
        * (
            1.0
            - math.exp(
                -final_seal_delay / FINAL_SEAL_DELAY_SATURATION_SECONDS
            )
        )
        if final_seal_delay is not None
        else None
    )
    available = [value for value in (open_strength, delay_strength) if value is not None]
    return {
        "score": rounded(max(available)) if available else None,
        "first_seal": first_seal,
        "final_seal": final_seal,
        "open_count": open_count,
        "first_to_final_seconds": first_to_final,
        "final_seal_delay_seconds": final_seal_delay,
        "open_count_strength": rounded(open_strength),
        "final_seal_delay_strength": rounded(delay_strength),
    }


def combined_interaction(
    price_score: float | None,
    board_score: float | None,
    *,
    one_price: bool,
) -> float | None:
    if one_price:
        return 0.0
    if price_score is None or board_score is None:
        return None
    # 价格释放和持续交互是两个必要条件，不能让单次大振幅补掉过早封死。
    return rounded(harmonic_mean(price_score, board_score))


def post_final_hold_seconds(final_seal: str | None) -> int | None:
    final_clock = active_clock(final_seal)
    if final_clock is None:
        return None
    return max(0, TOTAL_ACTIVE_SECONDS - final_clock)


def interpretation(
    *,
    one_price: bool,
    activity: float | None,
    interaction: float | None,
    true_volume: float | None,
    hold_seconds: int | None,
) -> str:
    if one_price:
        return "一字封闭：没有可观察的筹码交互"
    if activity is None:
        return "连续板量能基线不足：暂不宣布爆量"
    if interaction is None:
        return "日内行为证据不足：只有量，不能判断真实爆量"
    if activity >= STRONG_EVIDENCE and interaction < LOW_INTERACTION:
        return "放量但交互不足：加速途中爆量，仍不能视为换手完成"
    if (true_volume or 0.0) >= STRONG_EVIDENCE:
        if hold_seconds is not None:
            return "真实爆量；终封后保持只列时长，不冒充板上无量"
        return "真实爆量；终封后保持时长缺失"
    if interaction >= STRONG_EVIDENCE and activity < STRONG_EVIDENCE:
        return "交互充分但量能放大有限：属于换手动作，不属于爆量"
    return "量与交互均未形成强证据"


def score_stock(
    day: str,
    stock: dict[str, Any],
    ths: dict[str, Any] | None,
) -> dict[str, Any]:
    code = code_of(stock.get("code"))
    height = as_int(stock.get("boards")) or 0
    sequence, complete = consecutive_limit_sequence(day, code, height)
    amount = amount_expansion(as_float(stock.get("amount")), sequence)
    price = price_interaction(stock)
    board = board_interaction(ths)
    one_price = is_one_price(stock)
    interaction_score = combined_interaction(
        as_float(price.get("score")),
        as_float(board.get("score")),
        one_price=one_price,
    )
    true_volume = rounded(
        harmonic_mean(as_float(amount.get("score")), interaction_score)
    )
    hold_seconds = post_final_hold_seconds(board.get("final_seal"))
    missing: list[str] = []
    if amount["score"] is None:
        missing.append("当前连续板此前成交额基线")
    if price["score"] is None:
        missing.append("开盘/最低价路径")
    if board["score"] is None:
        missing.append("同花顺终封与炸板次数")
    if hold_seconds is None:
        missing.append("终封后保持时长")
    warnings: list[str] = []
    if not complete:
        warnings.append("当前连续涨停路径未完整回溯到首板")
    kpl_first = as_int(stock.get("first_limit_ts"))
    ths_first = as_int((ths or {}).get("first_limit_ts"))
    if kpl_first and ths_first and abs(kpl_first - ths_first) > 60:
        warnings.append("开盘啦与同花顺首封时间相差超过60秒")
    return {
        "code": code,
        "name": stock.get("name"),
        "height": height,
        "theme": stock.get("theme"),
        "one_price": one_price,
        "true_volume_score": true_volume,
        "interpretation": interpretation(
            one_price=one_price,
            activity=as_float(amount.get("score")),
            interaction=interaction_score,
            true_volume=true_volume,
            hold_seconds=hold_seconds,
        ),
        "components": {
            "amount_expansion": amount,
            "price_interaction": price,
            "board_interaction": board,
            "intraday_interaction_score": interaction_score,
            "post_final_hold_seconds": hold_seconds,
        },
        "continuous_limit_sequence": sequence,
        "sequence_complete": complete,
        "missing_facts": missing,
        "warnings": warnings,
    }


def score_day(
    day: str,
    *,
    codes: set[str] | None = None,
    fetch_missing: bool = False,
) -> dict[str, Any]:
    pool = raw_pool(day)
    ths_rows = ths_stock_map(day, fetch_missing=fetch_missing)
    candidates = [
        row
        for row in (pool.get("stocks") or [])
        if (as_int(row.get("boards")) or 0) >= 2
        and (not codes or code_of(row.get("code")) in codes)
    ]
    if codes:
        found = {code_of(row.get("code")) for row in candidates}
        missing_codes = sorted(codes - found)
        if missing_codes:
            raise ValueError(f"{day} 涨停池不存在指定二板以上股票: {missing_codes}")
    rows = [
        score_stock(day, stock, ths_rows.get(code_of(stock.get("code"))))
        for stock in candidates
    ]
    rows.sort(key=lambda row: (
        -row["height"],
        -(row["true_volume_score"] if row["true_volume_score"] is not None else -1),
        row["code"],
    ))
    return {
        "policy_version": POLICY_VERSION,
        "stage": "node_close_true_volume_evidence",
        "date": day,
        "information_cutoff": day,
        "score_semantics": (
            "真实爆量分=成交额放大与日内筹码交互的调和平均；任一短板都不能被另一项掩盖"
        ),
        "contracts": {
            "forbidden_inputs": ["数值换手率"],
            "amount_reference": "只比较当前连续涨停路径，使用此前各板成交额最大值",
            "interaction": "价格释放与板上过程先取调和平均；任何一边不足都不能互相补分",
            "theme": "只展示开盘啦theme；同花顺请求不含reason_type",
            "prediction": "分数不等于次日连板概率，也不直接生成买卖结论",
        },
        "source_status": {
            "kaipanla": "available",
            "ths_limit_pool": "available" if ths_rows else "missing",
        },
        "candidates": rows,
        "source_gaps": [
            "当前没有逐笔或分钟成交分布，无法直接计算终封后板上实际成交量",
        ],
    }


def fmt(value: Any, digits: int = 2) -> str:
    number = as_float(value)
    return "—" if number is None else f"{number:.{digits}f}"


def markdown_score(result: dict[str, Any]) -> str:
    lines = [
        f"## {result['date']}｜真实爆量证据",
        "",
        result["score_semantics"],
        "",
        "|股票|板|量比*|量能分|价格交互|炸板|首封→终封|日内交互|真实爆量|封后保持(分)|结论|",
        "|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---|",
    ]
    for row in result["candidates"]:
        components = row["components"]
        amount = components["amount_expansion"]
        price = components["price_interaction"]
        board = components["board_interaction"]
        hold_seconds = components["post_final_hold_seconds"]
        lines.append(
            f"|{row['name']} `{row['code']}`|{row['height']}|"
            f"{fmt(amount['amount_ratio'], 3)}|{fmt(amount['score'])}|"
            f"{fmt(price['score'])}|{board['open_count'] if board['open_count'] is not None else '—'}|"
            f"{board['first_seal'] or '—'}→{board['final_seal'] or '—'}|"
            f"{fmt(components['intraday_interaction_score'])}|"
            f"{fmt(row['true_volume_score'])}|"
            f"{fmt(hold_seconds / 60.0 if hold_seconds is not None else None, 1)}|"
            f"{row['interpretation']}|"
        )
        notes = row["missing_facts"] + row["warnings"]
        if notes:
            lines.append(f"|↳证据缺口||||||||||{'；'.join(notes)}|")
    lines.extend([
        "",
        "*量比只使用当前连续涨停路径中“当日成交额 ÷ 此前各板最大成交额”，不读取换手率。",
        "终封后的板上实际成交分布尚无分钟/逐笔源，因此封后保持只表示未再炸板的时长，不冒充板上缩量。",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="+", help="节点日或研究日 YYYY-MM-DD")
    parser.add_argument("--code", action="append", help="只看指定股票，可重复")
    parser.add_argument(
        "--fetch-missing",
        action="store_true",
        help="缺少同花顺日文件时抓取并保存到同日 raw",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    args = parser.parse_args(argv)
    codes = {code_of(code) for code in (args.code or [])} or None
    results = [
        score_day(day, codes=codes, fetch_missing=args.fetch_missing)
        for day in args.dates
    ]
    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(markdown_score(result) for result in results))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
