# -*- coding: utf-8 -*-
"""显式后验入口：计算 T+1 09:25 实际竞价分 A 与超预期差 Δ。

节点日预期 E 由 ``candidate_initial_score`` 生成且严格截止 T。本模块才允许
寻找下一交易日；收盘晋级结果只放在独立的 ``after_close_outcome`` 字段，绝不
参与 E、A 或 Δ 的计算。

历史数据只有最终竞价开盘价，没有竞价成交额和 09:20~09:25 队列轨迹，因此
自身竞价证据暂时只由开盘涨幅相对该股涨停幅度的位置构成；多票梯队再加入
冻结层内的实际 PK 形成 A。缺数据就明确缺失，不补默认分。全市场竞价一字
情况按当前约定不接入。

候选行动日日 K 若不在涨停池主源中，默认由腾讯接口补取、失败时走新浪兜底，
并写入统一未复权缓存；补取后仍不完整则整次任务失败，不输出删样本结果。

用法：

  python -m ultraboard.review.auction_score review 2025-12-22 --fetch-missing
  python -m ultraboard.review.auction_score backtest \
    --labels .blind-test-quarantine/labels/stage1_locked.json --fetch-missing
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean
from typing import Any

from ultraboard.kaipanla.ladder_evidence import (
    as_float,
    as_int,
    cached_ohlc,
    code_of,
    next_trade_day,
    ohlc_map,
    raw_pool,
)
from ultraboard.kaipanla.ohlc import (
    NoTradingBarError,
    fetch_kline_range,
    merge_cached_bars,
)
from ultraboard.limits import limit_ratio, limit_up_price
from ultraboard.review.candidate_initial_score import WEIGHTS, score_day
from ultraboard.review.ladder_selector import load_labels
from ultraboard.review.layer_pk import (
    PK_GAP_SCALE,
    PK_WEIGHT,
    PK_WEIGHT_CANDIDATES,
    compose_score,
    layer_pk_scores,
)


POLICY_VERSION = "stage2_auction_surprise_v2_layer_pk"

# 横轴是竞价涨幅 / 个股涨停幅度。平开为 50，涨停开为 100，跌停开为 0。
OPEN_SCORE_POINTS = (
    (-1.00, 0.0),
    (-0.70, 10.0),
    (-0.50, 20.0),
    (-0.30, 32.0),
    (-0.10, 44.0),
    (0.00, 50.0),
    (0.20, 60.0),
    (0.40, 70.0),
    (0.60, 80.0),
    (0.80, 90.0),
    (0.95, 97.0),
    (1.00, 100.0),
)

COMPONENT_NAMES = tuple(WEIGHTS)


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def interpolate(points: tuple[tuple[float, float], ...], value: float) -> float:
    if value <= points[0][0]:
        return points[0][1]
    if value >= points[-1][0]:
        return points[-1][1]
    for (left_x, left_y), (right_x, right_y) in zip(points, points[1:]):
        if left_x <= value <= right_x:
            ratio = (value - left_x) / (right_x - left_x)
            return left_y + (right_y - left_y) * ratio
    raise ValueError(f"插值点未覆盖 {value}")


def opening_strength_evidence(
    code: str,
    name: str,
    open_pct: float,
) -> dict[str, Any]:
    ratio = limit_ratio(code, name)
    if ratio is None:
        raise ValueError(f"{name}({code}) 不适用涨跌停竞价刻度")
    limit_pct = ratio * 100.0
    normalized_open = open_pct / limit_pct
    score = clamp(interpolate(OPEN_SCORE_POINTS, normalized_open))
    return {
        "score": round(score, 2),
        "open_pct": round(open_pct, 2),
        "limit_pct": round(limit_pct, 2),
        "normalized_open": round(normalized_open, 4),
        "scoring_inputs": {"normalized_open_price": 1.0},
        "unavailable_inputs": [
            "竞价成交额/成交量",
            "09:20至09:25委托队列轨迹",
            "全市场竞价一字结构",
        ],
    }


def surprise_label(delta: float) -> str:
    if delta >= 15:
        return "大幅超预期"
    if delta >= 7:
        return "超预期"
    if delta > -7:
        return "符合预期"
    if delta > -15:
        return "不及预期"
    return "大幅不及预期"


def absolute_label(score: float, normalized_open: float) -> str:
    if normalized_open >= 0.995:
        return "涨停价竞价"
    if score >= 90:
        return "近涨停强竞价"
    if score >= 80:
        return "强竞价"
    if score >= 65:
        return "偏强竞价"
    if score >= 45:
        return "普通竞价"
    if score >= 25:
        return "弱竞价"
    return "深水竞价"


def known_bar(code: str, day: str) -> tuple[dict[str, Any], str | None]:
    raw_bar = ohlc_map(day).get(code) or {}
    if raw_bar.get("open_pct") is not None:
        return raw_bar, "raw/action_day/ohlc.json"
    cached = cached_ohlc(code, day)
    if cached.get("open_pct") is not None:
        return cached, "ohlc_cache/unadjusted"
    if cached.get("trading_status") == "not_traded":
        return cached, "ohlc_cache/confirmed_no_bar"
    return {}, None


def fetch_bar(code: str, day: str) -> tuple[dict[str, Any], str | None]:
    try:
        bar = fetch_kline_range(code, day, day).get(day) or {}
    except NoTradingBarError:
        return {
            "trading_status": "not_traded",
            "evidence": "tencent_and_sina_empty",
        }, "tencent+sina/confirmed_no_bar"
    except Exception as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    return bar, None


def prepare_rows(days: list[str]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    prepared = []
    expectations = {}
    for day in days:
        expectation = score_day(day)
        expectations[day] = expectation
        action_day = next_trade_day(day)
        if not action_day:
            continue
        action_map = {
            code_of(row.get("code")): row
            for row in (raw_pool(action_day).get("stocks") or [])
        }
        for candidate in expectation.get("candidates") or []:
            prepared.append({
                "node_date": day,
                "action_date": action_day,
                "candidate": candidate,
                "action_stock": action_map.get(candidate["code"]) or {},
            })
    return prepared, expectations


def resolve_bars(
    prepared: list[dict[str, Any]],
    *,
    fetch_missing: bool,
    workers: int = 8,
) -> dict[tuple[str, str], tuple[dict[str, Any], str | None]]:
    resolved: dict[tuple[str, str], tuple[dict[str, Any], str | None]] = {}
    missing = []
    for item in prepared:
        code = item["candidate"]["code"]
        day = item["action_date"]
        key = (code, day)
        if key in resolved:
            continue
        bar, source = known_bar(code, day)
        if bar:
            resolved[key] = (bar, source)
        else:
            missing.append(key)

    if not fetch_missing or not missing:
        return resolved

    fetched_by_code: dict[str, dict[str, dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(fetch_bar, code, day): (code, day)
            for code, day in missing
        }
        for future in as_completed(futures):
            key = futures[future]
            bar, detail = future.result()
            if bar:
                resolved[key] = (
                    bar,
                    detail or "tencent_kline/sina_fallback",
                )
                fetched_by_code.setdefault(key[0], {})[key[1]] = bar
            else:
                resolved[key] = ({}, detail or "历史日K为空")

    # 网络补数必须落入统一未复权缓存；后续离线运行读取同一真相，不重复缺失。
    for code, bars in sorted(fetched_by_code.items()):
        merge_cached_bars(code, bars)

    unresolved = [key for key in missing if not resolved.get(key, ({}, None))[0]]
    if unresolved:
        details = ", ".join(
            f"{code}@{day}: {resolved.get((code, day), ({}, '未解析'))[1]}"
            for code, day in unresolved
        )
        raise RuntimeError(f"候选行动日日K补取后仍不完整：{details}")
    return resolved


def outcome_of(
    candidate: dict[str, Any],
    action: dict[str, Any],
    bar: dict[str, Any],
) -> dict[str, Any]:
    code = candidate["code"]
    name = candidate["name"]
    previous_close = as_float(bar.get("prev_close"))
    limit_price = (
        limit_up_price(previous_close, code, name)
        if previous_close is not None
        else None
    )
    open_price = as_float(bar.get("open"))
    high_price = as_float(bar.get("high"))
    close_price = as_float(bar.get("close") or action.get("price"))
    equal_limit = lambda value: bool(
        limit_price is not None
        and value is not None
        and abs(value - limit_price) < 0.005
    )
    return {
        "information_cutoff": "action_day_close",
        "opened_at_limit": equal_limit(open_price),
        "touched_limit": bool(
            limit_price is not None
            and high_price is not None
            and high_price >= limit_price - 0.005
        ),
        "closed_at_limit": equal_limit(close_price),
        "continued_limit": bool(
            as_int(action.get("boards")) == int(candidate["height"]) + 1
        ),
        "continued_source": "action_day_zt_pool_boards",
    }


def build_candidate_result(
    item: dict[str, Any],
    bar: dict[str, Any],
    source: str | None,
) -> dict[str, Any]:
    candidate = item["candidate"]
    expected = float(candidate["expected_auction_score"])
    open_pct = as_float(bar.get("open_pct"))
    opening = (
        opening_strength_evidence(candidate["code"], candidate["name"], open_pct)
        if open_pct is not None
        else None
    )
    opening_score = float(opening["score"]) if opening else None
    return {
        "node_rank": candidate["rank"],
        "code": candidate["code"],
        "name": candidate["name"],
        "height": candidate["height"],
        "scoring_theme": candidate["scoring_theme"],
        "expected_auction_score": round(expected, 2),
        "expected_score_evidence": candidate["same_ladder_pk"],
        "actual_auction": {
            **(opening or {
                "open_pct": None,
                "limit_pct": None,
                "normalized_open": None,
                "scoring_inputs": {},
                "unavailable_inputs": ["竞价开盘价"],
            }),
            "score": None,
            "opening_strength_evidence_score": opening_score,
            "same_ladder_pk": None,
            "information_cutoff": f"{item['action_date']} 09:25",
            "source": source,
            "trading_status": bar.get("trading_status") or "traded",
        },
        "surprise_delta": None,
        "surprise_label": "无法计算",
        "absolute_auction_label": "无法计算",
        "node_component_scores": candidate["component_scores"],
        "after_close_outcome": outcome_of(
            candidate,
            item["action_stock"],
            bar,
        ),
    }


def apply_actual_layer_pk(rows: list[dict[str, Any]]) -> None:
    """在同一节点整层竞价都准备好后，统一计算实际 PK、A 与 Δ。"""
    layer_size = len(rows)
    opening_scores = {
        row["code"]: float(row["actual_auction"]["opening_strength_evidence_score"])
        for row in rows
        if row["actual_auction"]["opening_strength_evidence_score"] is not None
    }
    layer_complete = len(opening_scores) == layer_size
    comparable = layer_size >= 2 and layer_complete
    actual_pk = (
        layer_pk_scores(opening_scores)
        if layer_complete
        else {row["code"]: None for row in rows}
    )

    for row in rows:
        auction = row["actual_auction"]
        opening_score = auction["opening_strength_evidence_score"]
        pk_score = actual_pk.get(row["code"])
        expected_pk_score = row["expected_score_evidence"]["expected_pk_score"]
        can_compose = opening_score is not None and (
            layer_size == 1 or comparable
        )
        if can_compose:
            final_score, effective_weight = compose_score(
                float(opening_score),
                pk_score,
            )
        else:
            final_score, effective_weight = None, 0.0

        auction["score"] = final_score
        auction["same_ladder_pk"] = {
            "available": comparable,
            "layer_candidate_count": layer_size,
            "covered_candidate_count": len(opening_scores),
            "peer_count": max(0, layer_size - 1),
            "actual_pk_score": pk_score if comparable else None,
            "pk_surprise_delta": (
                round(float(pk_score) - float(expected_pk_score), 2)
                if comparable and expected_pk_score is not None
                else None
            ),
            "configured_weight": PK_WEIGHT,
            "effective_weight": effective_weight,
            "gap_scale": PK_GAP_SCALE,
            "contract": (
                "比较冻结梯队内全部自然票的09:25开盘强度"
                if comparable
                else (
                    "梯队仅一只自然票，无对手，PK因子缺席"
                    if layer_size == 1
                    else "同梯队竞价数据未完整，最终A与Δ不降级计算"
                )
            ),
        }
        auction["scoring_inputs"] = {
            "opening_strength_evidence": round(1.0 - effective_weight, 2),
            "same_ladder_pk": round(effective_weight, 2),
        }
        if final_score is None:
            continue

        delta = round(final_score - float(row["expected_auction_score"]), 2)
        row["surprise_delta"] = delta
        row["surprise_label"] = surprise_label(delta)
        row["absolute_auction_label"] = absolute_label(
            final_score,
            float(auction["normalized_open"]),
        )


def review_days(
    days: list[str],
    *,
    fetch_missing: bool = True,
    workers: int = 8,
) -> list[dict[str, Any]]:
    prepared, expectations = prepare_rows(days)
    bars = resolve_bars(
        prepared,
        fetch_missing=fetch_missing,
        workers=workers,
    )
    grouped: dict[str, list[dict[str, Any]]] = {day: [] for day in days}
    for item in prepared:
        key = (item["candidate"]["code"], item["action_date"])
        bar, source = bars.get(key, ({}, None))
        grouped[item["node_date"]].append(
            build_candidate_result(item, bar, source)
        )

    packs = []
    for day in days:
        expectation = expectations[day]
        rows = sorted(grouped[day], key=lambda row: row["node_rank"])
        apply_actual_layer_pk(rows)
        action_day = next_trade_day(day)
        packs.append({
            "policy_version": POLICY_VERSION,
            "stage": "explicit_post_event_auction_review",
            "node_date": day,
            "node_information_cutoff": day,
            "action_date": action_day,
            "stage1": expectation["stage1"],
            "candidates": rows,
            "contracts": {
                "expected_E": "只由节点日T及以前的自身证据与预期层内PK冻结",
                "actual_A": "只使用T+1集合竞价开盘强度与实际层内PK；V2不含竞价量",
                "delta": "Δ=A-E；A与E在同一0至100刻度",
                "same_ladder_pk": (
                    "E与A都比较冻结梯队内全部自然票；单票时因子缺席。"
                    "多票竞价缺任一票时不降级计算最终A"
                ),
                "after_close": "仅供事后校准，绝不参与E、A或Δ",
                "auction_one_price_factor": "按当前约定不接入，权重为0",
            },
        })
    return packs


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    left_mean, right_mean = mean(xs), mean(ys)
    left = [value - left_mean for value in xs]
    right = [value - right_mean for value in ys]
    denominator = math.sqrt(
        sum(value * value for value in left)
        * sum(value * value for value in right)
    )
    if not denominator:
        return None
    return sum(a * b for a, b in zip(left, right)) / denominator


def mean_or_none(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


def scores_at_pk_weight(
    row: dict[str, Any],
    weight: float,
) -> tuple[float, float, float]:
    expected_evidence = row["expected_score_evidence"]
    actual_pk = row["actual_auction"]["same_ladder_pk"]
    expected, _ = compose_score(
        float(expected_evidence["candidate_evidence_score"]),
        expected_evidence["expected_pk_score"],
        weight=weight,
    )
    actual, _ = compose_score(
        float(row["actual_auction"]["opening_strength_evidence_score"]),
        actual_pk["actual_pk_score"],
        weight=weight,
    )
    return expected, actual, round(actual - expected, 2)


def pk_weight_comparison(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一批后验样本对照不同 PK 权重，不反写节点日输入。"""
    variants = []
    for weight in PK_WEIGHT_CANDIDATES:
        scored = [
            (row, *scores_at_pk_weight(row, weight))
            for row in rows
        ]
        expected = [item[1] for item in scored]
        actual = [item[2] for item in scored]
        deltas = [item[3] for item in scored]
        continued = [item for item in scored if item[0]["after_close_outcome"]["continued_limit"]]
        failed = [item for item in scored if not item[0]["after_close_outcome"]["continued_limit"]]
        strong_positive = [
            item for item in scored if item[2] >= 80 and item[3] >= 7
        ]
        strong_positive_continued = sum(
            item[0]["after_close_outcome"]["continued_limit"]
            for item in strong_positive
        )
        continued_actual = [item[2] for item in continued]
        failed_actual = [item[2] for item in failed]
        continued_delta = [item[3] for item in continued]
        failed_delta = [item[3] for item in failed]
        variants.append({
            "pk_weight": weight,
            "mean_expected_E": mean_or_none(expected),
            "mean_actual_A": mean_or_none(actual),
            "mae": mean_or_none([
                abs(left - right) for left, right in zip(expected, actual)
            ]),
            "pearson": (
                round(value, 4)
                if (value := pearson(expected, actual)) is not None
                else None
            ),
            "continued_vs_failed_actual_A_gap": (
                round(mean(continued_actual) - mean(failed_actual), 2)
                if continued_actual and failed_actual
                else None
            ),
            "continued_vs_failed_delta_gap": (
                round(mean(continued_delta) - mean(failed_delta), 2)
                if continued_delta and failed_delta
                else None
            ),
            "strong_and_positive": {
                "count": len(strong_positive),
                "continued_count": strong_positive_continued,
                "continued_rate": (
                    round(strong_positive_continued / len(strong_positive), 4)
                    if strong_positive
                    else None
                ),
            },
        })
    return variants


def rate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    continued = sum(
        row["after_close_outcome"]["continued_limit"] for row in rows
    )
    return {
        "count": len(rows),
        "continued_count": continued,
        "continued_rate": round(continued / len(rows), 4) if rows else None,
    }


def same_ladder_pk_diagnostics(
    packs: list[dict[str, Any]],
) -> dict[str, Any]:
    all_multi_packs = [
        pack for pack in packs if len(pack["candidates"]) >= 2
    ]
    multi_packs = [
        pack
        for pack in all_multi_packs
        if all(
            row["actual_auction"]["same_ladder_pk"]["actual_pk_score"]
            is not None
            for row in pack["candidates"]
        )
    ]
    rows = [row for pack in multi_packs for row in pack["candidates"]]
    continued = [
        row for row in rows if row["after_close_outcome"]["continued_limit"]
    ]
    failed = [
        row for row in rows if not row["after_close_outcome"]["continued_limit"]
    ]
    expected_leaders = []
    actual_leaders = []
    actual_non_leaders = []
    for pack in multi_packs:
        candidates = pack["candidates"]
        expected_leader = max(
            candidates,
            key=lambda row: row["expected_score_evidence"]["candidate_evidence_score"],
        )
        actual_leader = max(
            candidates,
            key=lambda row: row["actual_auction"]["opening_strength_evidence_score"],
        )
        expected_leaders.append(expected_leader)
        actual_leaders.append(actual_leader)
        actual_non_leaders.extend(
            row for row in candidates if row is not actual_leader
        )

    expected_pk = [
        float(row["expected_score_evidence"]["expected_pk_score"])
        for row in rows
    ]
    actual_pk = [
        float(row["actual_auction"]["same_ladder_pk"]["actual_pk_score"])
        for row in rows
    ]
    pk_delta = lambda row: (
        float(row["actual_auction"]["same_ladder_pk"]["actual_pk_score"])
        - float(row["expected_score_evidence"]["expected_pk_score"])
    )
    return {
        "multi_candidate_node_count": len(all_multi_packs),
        "auction_covered_node_count": len(multi_packs),
        "candidate_count": len(rows),
        "expected_vs_actual_pk_pearson": (
            round(value, 4)
            if (value := pearson(expected_pk, actual_pk)) is not None
            else None
        ),
        "mean_pk_surprise_continued": mean_or_none([
            pk_delta(row) for row in continued
        ]),
        "mean_pk_surprise_not_continued": mean_or_none([
            pk_delta(row) for row in failed
        ]),
        "node_expected_layer_leader": rate_summary(expected_leaders),
        "auction_actual_layer_leader": rate_summary(actual_leaders),
        "auction_actual_non_leader": rate_summary(actual_non_leaders),
    }


def outcome_summary(rows: list[dict[str, Any]], continued: bool) -> dict[str, Any]:
    subset = [
        row
        for row in rows
        if row["after_close_outcome"]["continued_limit"] is continued
    ]
    return {
        "count": len(subset),
        "mean_expected_E": mean_or_none([
            float(row["expected_auction_score"]) for row in subset
        ]),
        "mean_actual_A": mean_or_none([
            float(row["actual_auction"]["score"])
            for row in subset
            if row["actual_auction"]["score"] is not None
        ]),
        "mean_delta": mean_or_none([
            float(row["surprise_delta"])
            for row in subset
            if row["surprise_delta"] is not None
        ]),
    }


def backtest(
    label_path: Path,
    *,
    include_review: bool = False,
    fetch_missing: bool = True,
    workers: int = 8,
) -> dict[str, Any]:
    labels = load_labels(label_path, include_review=include_review)
    packs = review_days(
        [str(row["date"]) for row in labels],
        fetch_missing=fetch_missing,
        workers=workers,
    )
    rows = [row for pack in packs for row in pack["candidates"]]
    covered = [
        row for row in rows if row["actual_auction"]["score"] is not None
    ]
    expected = [float(row["expected_auction_score"]) for row in covered]
    actual = [float(row["actual_auction"]["score"]) for row in covered]
    deltas = [float(row["surprise_delta"]) for row in covered]

    by_surprise = []
    for label in (
        "大幅超预期",
        "超预期",
        "符合预期",
        "不及预期",
        "大幅不及预期",
    ):
        subset = [row for row in covered if row["surprise_label"] == label]
        continued_count = sum(
            row["after_close_outcome"]["continued_limit"] for row in subset
        )
        by_surprise.append({
            "label": label,
            "count": len(subset),
            "continued_count": continued_count,
            "continued_rate": (
                round(continued_count / len(subset), 4) if subset else None
            ),
        })

    component_correlations = {}
    for component in COMPONENT_NAMES:
        values = [
            float(row["node_component_scores"][component]) for row in covered
        ]
        value = pearson(values, actual)
        component_correlations[component] = (
            round(value, 4) if value is not None else None
        )

    auction_matrix = []
    matrix_specs = (
        ("A强且超预期", lambda row: row["actual_auction"]["score"] >= 80 and row["surprise_delta"] >= 7),
        ("A强但未超预期", lambda row: row["actual_auction"]["score"] >= 80 and row["surprise_delta"] < 7),
        ("A弱但超预期", lambda row: row["actual_auction"]["score"] < 80 and row["surprise_delta"] >= 7),
        ("A弱且未超预期", lambda row: row["actual_auction"]["score"] < 80 and row["surprise_delta"] < 7),
    )
    for label, predicate in matrix_specs:
        subset = [row for row in covered if predicate(row)]
        continued_count = sum(
            row["after_close_outcome"]["continued_limit"] for row in subset
        )
        auction_matrix.append({
            "label": label,
            "count": len(subset),
            "continued_count": continued_count,
            "continued_rate": (
                round(continued_count / len(subset), 4) if subset else None
            ),
        })

    daily_top = []
    for pack in packs:
        candidates = pack["candidates"]
        if not candidates:
            continue
        top = min(candidates, key=lambda row: row["node_rank"])
        daily_top.append({
            "date": pack["node_date"],
            "name": top["name"],
            "expected_E": top["expected_auction_score"],
            "actual_A": top["actual_auction"]["score"],
            "delta": top["surprise_delta"],
            "continued": top["after_close_outcome"]["continued_limit"],
        })

    return {
        "policy_version": POLICY_VERSION,
        "evaluation": "显式后验校准；普通节点预期入口不读取本结果",
        "label_path": str(label_path),
        "node_count": len(packs),
        "candidate_count": len(rows),
        "auction_covered_count": len(covered),
        "expectation_vs_actual": {
            "mean_expected_E": mean_or_none(expected),
            "mean_actual_A": mean_or_none(actual),
            "mean_delta": mean_or_none(deltas),
            "mae": mean_or_none([
                abs(left - right) for left, right in zip(expected, actual)
            ]),
            "pearson": (
                round(value, 4)
                if (value := pearson(expected, actual)) is not None
                else None
            ),
        },
        "component_correlations_with_actual_A": component_correlations,
        "same_ladder_pk_coverage": {
            "node_count": sum(
                any(
                    row["actual_auction"]["same_ladder_pk"]["available"]
                    for row in pack["candidates"]
                )
                for pack in packs
            ),
            "candidate_count": sum(
                row["actual_auction"]["same_ladder_pk"]["available"]
                for row in covered
            ),
            "single_candidate_count": sum(
                row["actual_auction"]["same_ladder_pk"]["layer_candidate_count"] == 1
                for row in covered
            ),
        },
        "same_ladder_pk_diagnostics": same_ladder_pk_diagnostics(packs),
        "pk_weight_comparison": pk_weight_comparison(covered),
        "continued": outcome_summary(covered, True),
        "not_continued": outcome_summary(covered, False),
        "by_surprise": by_surprise,
        "absolute_and_surprise_matrix": {
            "strong_actual_threshold": 80,
            "positive_surprise_threshold": 7,
            "rows": auction_matrix,
        },
        "daily_top_expected": {
            "count": len(daily_top),
            "continued_count": sum(row["continued"] for row in daily_top),
            "continued_rate": (
                round(sum(row["continued"] for row in daily_top) / len(daily_top), 4)
                if daily_top
                else None
            ),
            "rows": daily_top,
        },
        "weight_policy": {
            "candidate_evidence_components": WEIGHTS,
            "same_ladder_pk": {
                "current": PK_WEIGHT,
                "gap_scale": PK_GAP_SCALE,
                "compared_weights": PK_WEIGHT_CANDIDATES,
            },
            "rule": "只按跨样本分组证据小步调整；禁止单日、股票名或结果特判",
        },
        "packs": packs,
    }


def markdown_review(pack: dict[str, Any]) -> str:
    lines = [
        f"## {pack['node_date']} → {pack['action_date']}｜"
        f"{pack['stage1']['target_height']}板｜模型={pack['stage1']['model']}",
        "",
        "|节点名次|候选|预期E|预期PK|实际A|开盘证据|实际PK|PKΔ|Δ|判断|竞价涨幅|次日晋级*|",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|:---:|",
    ]
    for row in pack["candidates"]:
        auction = row["actual_auction"]
        actual = auction["score"]
        delta = row["surprise_delta"]
        expected_pk = row["expected_score_evidence"]["expected_pk_score"]
        actual_pk = auction["same_ladder_pk"]["actual_pk_score"]
        pk_delta = auction["same_ladder_pk"]["pk_surprise_delta"]
        expected_pk_text = f"{expected_pk:.2f}" if expected_pk is not None else "—"
        actual_text = f"{actual:.2f}" if actual is not None else "缺失"
        opening_text = (
            f"{auction['opening_strength_evidence_score']:.2f}"
            if auction["opening_strength_evidence_score"] is not None
            else "缺失"
        )
        actual_pk_text = f"{actual_pk:.2f}" if actual_pk is not None else "—"
        pk_delta_text = f"{pk_delta:+.2f}" if pk_delta is not None else "—"
        delta_text = f"{delta:+.2f}" if delta is not None else "—"
        judgment = (
            f"{row['surprise_label']} / {row['absolute_auction_label']}"
            if actual is not None
            else "无法计算"
        )
        open_pct_text = (
            f"{auction['open_pct']:+.2f}%"
            if auction["open_pct"] is not None
            else "—"
        )
        lines.append(
            f"|{row['node_rank']}|{row['name']}({row['code']})|"
            f"{row['expected_auction_score']:.2f}|{expected_pk_text}|"
            f"{actual_text}|{opening_text}|{actual_pk_text}|{pk_delta_text}|"
            f"{delta_text}|"
            f"{judgment}|{open_pct_text}|"
            f"{'是' if row['after_close_outcome']['continued_limit'] else '否'}|"
        )
    lines.extend([
        "",
        "\\* 次日晋级是收盘后验，只用于校准，不参与 E、A 或 Δ。",
        "V2 的 A 由竞价开盘强度与同梯队实际PK组成；单票梯队不计算PK。"
        "竞价量与全市场竞价一字暂未接入。",
    ])
    return "\n".join(lines)


def markdown_backtest(result: dict[str, Any]) -> str:
    summary = result["expectation_vs_actual"]
    continued = result["continued"]
    failed = result["not_continued"]
    daily_top = result["daily_top_expected"]
    pk = result["same_ladder_pk_diagnostics"]
    lines = [
        "# 竞价预期后验校准",
        "",
        f"节点 {result['node_count']}，候选 {result['candidate_count']}，"
        f"竞价覆盖 {result['auction_covered_count']}。",
        f"E/A 均值：{summary['mean_expected_E']} / {summary['mean_actual_A']}；"
        f"MAE={summary['mae']}，相关系数={summary['pearson']}。",
        f"晋级组 {continued['count']}：E/A/Δ 均值 "
        f"{continued['mean_expected_E']} / {continued['mean_actual_A']} / "
        f"{continued['mean_delta']:+.2f}。",
        f"未晋级组 {failed['count']}：E/A/Δ 均值 "
        f"{failed['mean_expected_E']} / {failed['mean_actual_A']} / "
        f"{failed['mean_delta']:+.2f}。",
        f"节点日预期第一名次日晋级：{daily_top['continued_count']}/"
        f"{daily_top['count']}（{daily_top['continued_rate']:.1%}）。",
        f"多票节点实际竞价层内第一："
        f"{pk['auction_actual_layer_leader']['continued_count']}/"
        f"{pk['auction_actual_layer_leader']['count']}"
        f"（{pk['auction_actual_layer_leader']['continued_rate']:.1%}）；"
        f"其余票 {pk['auction_actual_non_leader']['continued_count']}/"
        f"{pk['auction_actual_non_leader']['count']}"
        f"（{pk['auction_actual_non_leader']['continued_rate']:.1%}）。",
        "",
        "|超预期分组|样本|晋级|晋级率|",
        "|---|---:|---:|---:|",
    ]
    for row in result["by_surprise"]:
        rate = (
            f"{row['continued_rate']:.1%}"
            if row["continued_rate"] is not None
            else "—"
        )
        lines.append(
            f"|{row['label']}|{row['count']}|{row['continued_count']}|{rate}|"
        )
    lines.extend([
        "",
        "|实际A与Δ交叉|样本|晋级|晋级率|",
        "|---|---:|---:|---:|",
    ])
    for row in result["absolute_and_surprise_matrix"]["rows"]:
        rate = (
            f"{row['continued_rate']:.1%}"
            if row["continued_rate"] is not None
            else "—"
        )
        lines.append(
            f"|{row['label']}|{row['count']}|{row['continued_count']}|{rate}|"
        )
    lines.extend([
        "",
        "|PK权重|E/A相关|MAE|晋级-失败 A差|晋级-失败 Δ差|A强且超预期 命中|",
        "|---:|---:|---:|---:|---:|---:|",
    ])
    for row in result["pk_weight_comparison"]:
        selected = row["strong_and_positive"]
        selected_rate = (
            f"{selected['continued_count']}/{selected['count']} "
            f"({selected['continued_rate']:.1%})"
            if selected["continued_rate"] is not None
            else "—"
        )
        lines.append(
            f"|{row['pk_weight']:.0%}|{row['pearson']}|{row['mae']}|"
            f"{row['continued_vs_failed_actual_A_gap']}|"
            f"{row['continued_vs_failed_delta_gap']}|{selected_rate}|"
        )
    lines.extend([
        "",
        f"当前 PK 权重 {PK_WEIGHT:.0%}；单票梯队实际生效权重为 0。",
        "当前不自动改权重；先看跨样本分组，再小步修改唯一权重源。",
    ])
    return "\n".join(lines)


def emit(payload: Any, output_format: str, renderer) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    items = payload if isinstance(payload, list) else [payload]
    print("\n\n".join(renderer(item) for item in items))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    review_parser = subparsers.add_parser(
        "review",
        help="显式读取T+1竞价和收盘结果",
    )
    review_parser.add_argument("dates", nargs="+", help="节点日 YYYY-MM-DD")
    review_parser.add_argument(
        "--fetch-missing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="自动补取并缓存候选行动日日K；用 --no-fetch-missing 进入显式离线模式",
    )
    review_parser.add_argument("--workers", type=int, default=8)
    review_parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )

    backtest_parser = subparsers.add_parser(
        "backtest",
        help="用隔离标签显式做跨节点后验校准",
    )
    backtest_parser.add_argument("--labels", type=Path, required=True)
    backtest_parser.add_argument("--include-review", action="store_true")
    backtest_parser.add_argument(
        "--fetch-missing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="自动补取并缓存候选行动日日K；用 --no-fetch-missing 进入显式离线模式",
    )
    backtest_parser.add_argument("--workers", type=int, default=8)
    backtest_parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )

    args = parser.parse_args(argv)
    if args.command == "review":
        packs = review_days(
            args.dates,
            fetch_missing=args.fetch_missing,
            workers=args.workers,
        )
        emit(packs, args.format, markdown_review)
    else:
        result = backtest(
            args.labels,
            include_review=args.include_review,
            fetch_missing=args.fetch_missing,
            workers=args.workers,
        )
        emit(result, args.format, markdown_backtest)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
