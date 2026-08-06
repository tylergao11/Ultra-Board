# -*- coding: utf-8 -*-
"""节点日换手、分歧与次日任务标签。

本模块不读取数值换手率，也不把不同含义压成一个总分。它只使用节点日及以前的
连续涨停量能链，加上节点日开盘、最低价、首封、终封与炸板事实，分别回答：

- 从首板到节点日的逐板量能与形态呈现什么结构；
- 分歧是否暴露、是否仍在延续、是否已经形成一致；
- 个股当前处于加速途中、换手整理中，还是整理完成；
- 次日仍欠什么任务，不预测它必须选择哪一种具体动作模型。

用法：

  python -m ultraboard.review.exchange_tags 2025-12-16 --fetch-missing
  python -m ultraboard.review.exchange_tags 2025-12-16 --code 001208
  python -m ultraboard.review.exchange_tags 2025-12-16 --format json
"""
from __future__ import annotations

import argparse
import json
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


POLICY_VERSION = "exchange_tags_v2_sequence_structure"

MORNING_START = 9 * 3600 + 30 * 60
MORNING_END = 11 * 3600 + 30 * 60
AFTERNOON_START = 13 * 3600
AFTERNOON_END = 15 * 3600
TAIL_START = 14 * 3600 + 30 * 60
QUICK_FINAL_SEAL_END = 9 * 3600 + 35 * 60
TOTAL_ACTIVE_SECONDS = (
    MORNING_END - MORNING_START + AFTERNOON_END - AFTERNOON_START
)


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


def unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


def consecutive_limit_sequence(
    day: str,
    code: str,
    height: int,
) -> tuple[list[dict[str, Any]], bool]:
    """回溯本轮连续涨停路径至首板，只读取 ``day`` 及以前。"""
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
            "open_pct": as_float(stock.get("open_pct")),
            "low_pct": price_pct(stock.get("low"), stock.get("prev_close")),
            "limit_pct": abs(as_float(stock.get("limit_pct")) or 0.0) or None,
            "shape_known": all(
                as_float(stock.get(field)) is not None
                for field in ("open", "high", "low")
            ),
            "one_price": is_one_price(stock),
        })
        expected -= 1
        if expected == 0:
            break
    rows = list(reversed(reverse_rows))
    return rows, expected == 0


def amount_path(
    current_amount: float | None,
    sequence: list[dict[str, Any]],
) -> dict[str, Any]:
    prior_amounts = [
        as_float(row.get("amount"))
        for row in sequence[:-1]
        if as_float(row.get("amount")) not in (None, 0.0)
    ]
    previous_row = sequence[-2] if len(sequence) >= 2 else None
    previous_amount = as_float((previous_row or {}).get("amount"))
    if current_amount is None or not prior_amounts:
        position = "逐板量能证据不足"
    elif current_amount > max(prior_amounts):
        position = "当前量高于前序所有板"
    elif current_amount < min(prior_amounts):
        position = "当前量低于前序所有板"
    else:
        position = "当前量位于前序量能区间"

    previous_relation: str | None = None
    if current_amount is not None and previous_amount is not None:
        if current_amount > previous_amount:
            previous_relation = "高于上一板"
        elif current_amount < previous_amount:
            previous_relation = "低于上一板"
        else:
            previous_relation = "与上一板相当"

    structure_tags = [position]
    if (previous_row or {}).get("one_price") is True:
        if previous_relation == "高于上一板":
            structure_tags.append("一字后补量")
        elif previous_relation == "低于上一板":
            structure_tags.append("一字后继续缩量")
    if (
        "一字后补量" in structure_tags
        and position == "当前量位于前序量能区间"
    ):
        structure_tags.append("补量但未超过前序高量板")

    return {
        "current_amount": current_amount,
        "position_in_sequence": position,
        "previous_relation": previous_relation,
        "structure_tags": unique(structure_tags),
        "comparison_contract": "只阅读完整逐板量能与形态，不建立单一有效基线或倍数",
        "sequence": sequence,
    }


def price_path(stock: dict[str, Any]) -> dict[str, Any]:
    limit_pct = abs(as_float(stock.get("limit_pct")) or 0.0)
    open_pct = as_float(stock.get("open_pct"))
    low_pct = price_pct(stock.get("low"), stock.get("prev_close"))
    if not limit_pct or open_pct is None or low_pct is None:
        return {
            "open_pct": open_pct,
            "low_pct": low_pct,
            "limit_pct": limit_pct or None,
            "downward_release_pct_points": None,
            "upward_eating_pct_points": None,
            "fact_tags": [],
        }

    downward_release = round(max(0.0, open_pct - low_pct), 2)
    upward_eating = round(max(0.0, limit_pct - open_pct), 2)
    tags: list[str] = []
    if downward_release > 0.0:
        tags.append("开盘后向下释放")
    if upward_eating > 0.0:
        tags.append("非涨停开盘后向上吃")
    if not tags:
        tags.append("价格路径封闭")
    return {
        "open_pct": round(open_pct, 2),
        "low_pct": round(low_pct, 2),
        "limit_pct": round(limit_pct, 2),
        "downward_release_pct_points": downward_release,
        "upward_eating_pct_points": upward_eating,
        "fact_tags": tags,
    }


def board_path(ths: dict[str, Any] | None) -> dict[str, Any]:
    if not ths:
        return {
            "first_seal": None,
            "final_seal": None,
            "open_count": None,
            "first_to_final_seconds": None,
            "post_final_hold_seconds": None,
            "tail_final_seal": None,
            "quick_final_seal": None,
            "fact_tags": [],
        }

    first_seal = seal_time(ths.get("first_limit_ts"))
    final_seal = seal_time(ths.get("final_limit_ts"))
    open_count = as_int(ths.get("open_count"))
    first_active = active_clock(first_seal)
    final_active = active_clock(final_seal)
    first_to_final = (
        max(0, final_active - first_active)
        if first_active is not None and final_active is not None
        else None
    )
    hold_seconds = (
        max(0, TOTAL_ACTIVE_SECONDS - final_active)
        if final_active is not None
        else None
    )
    final_clock = clock_seconds(final_seal)
    tail_final = final_clock >= TAIL_START if final_clock is not None else None
    quick_final = (
        final_clock <= QUICK_FINAL_SEAL_END if final_clock is not None else None
    )

    tags: list[str] = []
    if clock_seconds(first_seal) is not None and clock_seconds(first_seal) < MORNING_START:
        tags.append("集合竞价封板")
    if open_count == 0:
        tags.append("未记录炸板")
    elif open_count == 1:
        tags.append("一次炸板")
    elif open_count is not None:
        tags.append("多次炸板")
    if first_seal and final_seal and first_seal == final_seal and open_count == 0:
        tags.append("首封即终封")
    elif first_seal and final_seal and first_seal != final_seal:
        tags.append("首封后重新回封")
    if tail_final:
        tags.append("尾盘终封")
    elif final_seal:
        tags.append("非尾盘终封")

    return {
        "first_seal": first_seal,
        "final_seal": final_seal,
        "open_count": open_count,
        "first_to_final_seconds": first_to_final,
        "post_final_hold_seconds": hold_seconds,
        "tail_final_seal": tail_final,
        "quick_final_seal": quick_final,
        "fact_tags": tags,
    }


def has_observable_interaction(
    *,
    one_price: bool,
    price: dict[str, Any],
    board: dict[str, Any],
) -> bool:
    if one_price:
        return False
    return any((
        (as_float(price.get("downward_release_pct_points")) or 0.0) > 0.0,
        (as_float(price.get("upward_eating_pct_points")) or 0.0) > 0.0,
        (as_int(board.get("open_count")) or 0) > 0,
        (as_int(board.get("first_to_final_seconds")) or 0) > 0,
    ))


def has_sustained_interaction(
    *,
    one_price: bool,
    observable_interaction: bool,
    price: dict[str, Any],
    board: dict[str, Any],
) -> bool:
    """区分真实展开的过程与高开后短促封板。

    非快速终封表示市场给出了持续交互时间；最低价触及零轴及以下则表示出现了
    明确的向下释放。普通的短阳实体或板上成交量不能单独宣布换手充分。
    """
    if one_price or not observable_interaction:
        return False
    low_pct = as_float(price.get("low_pct"))
    touched_zero_axis = low_pct is not None and low_pct <= 0.0
    return board.get("quick_final_seal") is False or touched_zero_axis


def classify_exchange(
    *,
    one_price: bool,
    amount: dict[str, Any],
    observable_interaction: bool,
    sustained_interaction: bool,
) -> dict[str, Any]:
    if one_price:
        return {
            "state": "严重欠换手",
            "shortfall_level": "严重",
            "has_shortfall": True,
            "reason": "一字封闭，没有可观察的筹码交互",
        }
    if amount.get("position_in_sequence") == "逐板量能证据不足":
        return {
            "state": "换手证据不足",
            "shortfall_level": "未知",
            "has_shortfall": None,
            "reason": "完整逐板量能证据不足，不建立虚假基线",
        }
    if not observable_interaction:
        return {
            "state": "量能存在但日内交互不足",
            "shortfall_level": "明显",
            "has_shortfall": True,
            "reason": "成交额不能替代价格释放、炸板或回封交互",
        }
    if not sustained_interaction:
        return {
            "state": "短促交互，仍欠换手",
            "shortfall_level": "明显",
            "has_shortfall": True,
            "reason": "高开后快速封板或交互时间过短，整日成交额不能替代过程",
        }
    structure_tags = set(amount.get("structure_tags") or [])
    if "补量但未超过前序高量板" in structure_tags:
        return {
            "state": "部分交换，仍欠换手",
            "shortfall_level": "部分",
            "has_shortfall": True,
            "reason": "一字后已有持续交换，但整段量能结构仍显示只完成部分补量",
        }
    if amount.get("position_in_sequence") == "当前量高于前序所有板":
        return {
            "state": "换手充分",
            "shortfall_level": "无明显缺口",
            "has_shortfall": False,
            "reason": "当前日持续交互，且量能在完整连板序列中处于前高",
        }
    return {
        "state": "已有持续交互，换手程度待确认",
        "shortfall_level": "未知",
        "has_shortfall": None,
        "reason": "完整量能结构与日内过程尚不足以宣布换手完成或仍明显欠缺",
    }


def classify_divergence(
    *,
    exchange: dict[str, Any],
    observable_interaction: bool,
    board: dict[str, Any],
) -> dict[str, str]:
    tail_final = board.get("tail_final_seal")
    final_seal = board.get("final_seal")
    if final_seal is None or tail_final is None:
        return {
            "state": "分歧证据不足",
            "consensus": "未知",
            "reason": "终封事实缺失",
        }
    if tail_final and observable_interaction:
        return {
            "state": "分歧延续",
            "consensus": "筹码交换后仍未形成一致",
            "reason": "分歧延续到尾盘，快速回封不能单独证明整理完成",
        }
    if exchange.get("has_shortfall") is False and not tail_final:
        return {
            "state": "形成一致",
            "consensus": "已形成一致",
            "reason": "换手充分，并在非尾盘完成终封后保持",
        }
    if not observable_interaction:
        return {
            "state": "分歧未充分暴露",
            "consensus": "未经充分检验",
            "reason": "早封或封闭路径没有给出足够分歧交互",
        }
    return {
        "state": "分歧暴露有限",
        "consensus": "尚未确认一致",
        "reason": "已有交互，但换手缺口仍在，不能因封住就宣布一致",
    }


def classify_phase(
    exchange: dict[str, Any],
    divergence: dict[str, str],
    board: dict[str, Any],
) -> str:
    has_shortfall = exchange.get("has_shortfall") is True
    divergence_state = divergence.get("state")
    if divergence_state == "分歧延续":
        return "欠换手与分歧延续并存" if has_shortfall else "分歧延续中"
    if has_shortfall:
        return "加速途中" if board.get("quick_final_seal") else "补换手途中"
    if divergence_state == "形成一致":
        return "整理完成"
    return "状态待确认"


def next_day_intent(
    exchange: dict[str, Any],
    divergence: dict[str, str],
) -> dict[str, list[str]]:
    tasks: list[str] = []
    action_requirements: list[str] = []
    risks: list[str] = []
    has_shortfall = exchange.get("has_shortfall") is True
    if has_shortfall:
        tasks.append("补换手")
        action_requirements.append(
            "需要出现可观察筹码交换；可由下杀回封或不过度高开后的向上吃完成"
        )
        risks.append("再次大高开秒板属于继续加速，需警惕")
    if divergence.get("state") == "分歧延续":
        tasks.append("延续分歧后完成收敛")
        action_requirements.append("继续分歧后必须出现转强与稳定回封")
        risks.append("尾盘快速回封不能单独证明整理完成")
    if (
        exchange.get("has_shortfall") is False
        and divergence.get("state") == "形成一致"
    ):
        tasks.append("加速确认")
        action_requirements.append("个股形态的正常任务为大高开加速")
    if not tasks:
        tasks.append("状态待确认")
    return {
        "tasks": unique(tasks),
        "action_requirements": unique(action_requirements),
        "risks": unique(risks),
    }


def analyze_stock(
    day: str,
    stock: dict[str, Any],
    ths: dict[str, Any] | None,
) -> dict[str, Any]:
    code = code_of(stock.get("code"))
    height = as_int(stock.get("boards")) or 0
    sequence, complete = consecutive_limit_sequence(day, code, height)
    amount = amount_path(as_float(stock.get("amount")), sequence)
    price = price_path(stock)
    board = board_path(ths)
    one_price = is_one_price(stock)
    observable_interaction = has_observable_interaction(
        one_price=one_price,
        price=price,
        board=board,
    )
    sustained_interaction = has_sustained_interaction(
        one_price=one_price,
        observable_interaction=observable_interaction,
        price=price,
        board=board,
    )
    exchange = classify_exchange(
        one_price=one_price,
        amount=amount,
        observable_interaction=observable_interaction,
        sustained_interaction=sustained_interaction,
    )
    divergence = classify_divergence(
        exchange=exchange,
        observable_interaction=observable_interaction,
        board=board,
    )
    phase = classify_phase(exchange, divergence, board)
    intent = next_day_intent(exchange, divergence)

    fact_tags = (
        list(amount.get("structure_tags") or [])
        + list(price.get("fact_tags") or [])
        + list(board.get("fact_tags") or [])
    )
    if one_price:
        fact_tags.insert(0, "一字封闭")
    missing: list[str] = []
    if amount.get("position_in_sequence") == "逐板量能证据不足":
        missing.append("完整逐板量能")
    if price.get("downward_release_pct_points") is None:
        missing.append("开盘/最低价路径")
    if board.get("final_seal") is None or board.get("open_count") is None:
        missing.append("同花顺终封与炸板次数")
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
        "facts": {
            "volume_path": amount,
            "price_path": price,
            "board_path": board,
            "observable_interaction": observable_interaction,
            "sustained_interaction": sustained_interaction,
            "tags": unique(fact_tags),
        },
        "labels": {
            "exchange": exchange,
            "divergence": divergence,
            "phase": phase,
        },
        "next_day_intent": intent,
        "missing_facts": missing,
        "warnings": warnings,
    }


def analyze_day(
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
        analyze_stock(day, stock, ths_rows.get(code_of(stock.get("code"))))
        for stock in candidates
    ]
    rows.sort(key=lambda row: (-row["height"], row["code"]))
    return {
        "policy_version": POLICY_VERSION,
        "stage": "node_close_exchange_and_divergence_tags",
        "date": day,
        "information_cutoff": day,
        "semantics": (
            "原始数值负责证据，多轴标签负责表达换手、分歧、阶段与次日任务；"
            "不生成混合含义的总分"
        ),
        "contracts": {
            "forbidden_inputs": ["数值换手率", "T+1及以后事实"],
            "amount_path": (
                "只展示完整逐板量能与形态关系；禁止建立单一有效基线或派生倍数"
            ),
            "exchange_and_divergence": (
                "换手充分度与分歧状态相互独立，允许欠换手与分歧延续同时存在"
            ),
            "position": "不读取板块地位与发酵，地位侧预期由独立入口处理",
            "prediction": "次日任务不是具体动作预测，也不是买卖结论",
            "selection": "本入口只产出证据与标签，不负责节点选层",
        },
        "source_status": {
            "kaipanla": "available",
            "ths_limit_pool": "available" if ths_rows else "missing",
        },
        "candidates": rows,
        "source_gaps": [
            "当前没有逐笔或分钟成交分布，无法精确拆出尾盘开板区间实际成交额",
        ],
    }


def fmt_amount(value: Any) -> str:
    number = as_float(value)
    return "—" if number is None else f"{number / 100_000_000:.2f}亿"


def amount_chain(sequence: list[dict[str, Any]]) -> str:
    return "→".join(fmt_amount(row.get("amount")) for row in sequence) or "—"


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        f"## {result['date']}｜换手、分歧与次日任务标签",
        "",
        result["semantics"],
        "",
        "|股票|板|量能链|量能结构|首封→终封/炸板|换手标签|分歧标签|阶段|次日任务|",
        "|---|---:|---|---|---|---|---|---|---|",
    ]
    for row in result["candidates"]:
        facts = row["facts"]
        volume = facts["volume_path"]
        board = facts["board_path"]
        labels = row["labels"]
        open_count = board["open_count"] if board["open_count"] is not None else "—"
        tasks = "＋".join(row["next_day_intent"]["tasks"])
        lines.append(
            f"|{row['name']} `{row['code']}`|{row['height']}|"
            f"{amount_chain(volume['sequence'])}|"
            f"{'＋'.join(volume['structure_tags'])}|"
            f"{board['first_seal'] or '—'}→{board['final_seal'] or '—'}/{open_count}|"
            f"{labels['exchange']['state']}|{labels['divergence']['state']}|"
            f"{labels['phase']}|{tasks}|"
        )
        details = row["next_day_intent"]["action_requirements"]
        risks = row["next_day_intent"]["risks"]
        notes = row["missing_facts"] + row["warnings"]
        explanations = unique(details + risks + notes)
        if explanations:
            lines.append(f"|↳||||||||{'；'.join(explanations)}|")
    lines.extend([
        "",
        "- 量能链仅包含本轮连续涨停；保留逐板原值与形态关系，不建立单一有效基线，也不输出派生倍数。",
        "- 尾盘终封只描述路径；交换多少仍需结合整段量能链，换手充分也不等于已经形成一致。",
        "- 当前缺少分钟／逐笔成交分布，因此尾盘开板区间的精确交换量只作证据缺口，不伪造结论。",
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
        analyze_day(day, codes=codes, fetch_missing=args.fetch_missing)
        for day in args.dates
    ]
    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(markdown_report(result) for result in results))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
