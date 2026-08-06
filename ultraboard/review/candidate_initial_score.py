# -*- coding: utf-8 -*-
"""第二阶段节点日竞价预期分：只在第一阶段冻结梯队内给自然票排序。

它把节点日可见的身位、涨停原因榜位置、个股板块地位、首封主动性和首封后
的同题材传播压成自身证据，再加入冻结梯队内全部自然票的预期 PK，形成一个
可解释的次日竞价预期分。该入口严格截止节点日，绝不读取实际竞价；实际竞价
与超预期差由显式后验入口另算。

用法：

  python -m ultraboard.review.candidate_initial_score 2025-12-24
  python -m ultraboard.review.candidate_initial_score 2025-12-24 --format json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any

from ultraboard.kaipanla.ladder_evidence import (
    as_int,
    code_of,
    daily_stock_context,
    is_one_price,
    node_evidence,
    seal_time,
)
from ultraboard.review.ladder_selector import (
    MODEL_ATTACK,
    MODEL_DEFENSE,
    MODEL_NONE,
    select_ladder,
)
from ultraboard.review.layer_pk import (
    PK_GAP_SCALE,
    PK_WEIGHT,
    compose_score,
    layer_pk_scores,
)


POLICY_VERSION = "stage2_node_auction_expectation_v3_effective_theme"

# 唯一权重真相源。日内主动性 + 后续传播合计 40%。
WEIGHTS = {
    "layer_model_height": 0.20,
    "market_theme_position": 0.20,
    "candidate_theme_role": 0.20,
    "seal_initiative": 0.20,
    "post_seal_propagation": 0.20,
}

# 这些是首版人工先验，不是后验命中率。后续只能用隔离的 T+1 标签整体校准，
# 禁止为某只股票或某个日期加特判。
MODEL_STRENGTH = {
    MODEL_ATTACK: 92.0,
    MODEL_DEFENSE: 82.0,
    MODEL_NONE: 58.0,
    None: 0.0,
}
HEIGHT_STRENGTH = {
    2: 55.0,
    3: 68.0,
    4: 80.0,
    5: 88.0,
    # 节点日六板意味着次日冲击七板监控区，不能继续线性加分。
    6: 72.0,
    7: 62.0,
}

# 首封绝对时刻的分段锚点，区间内线性插值。
SEAL_TIME_POINTS = (
    (9 * 3600 + 25 * 60, 100.0),
    (9 * 3600 + 30 * 60 + 30, 98.0),
    (9 * 3600 + 31 * 60, 95.0),
    (9 * 3600 + 35 * 60, 90.0),
    (10 * 3600, 76.0),
    (10 * 3600 + 30 * 60, 64.0),
    (11 * 3600 + 30 * 60, 50.0),
    (13 * 3600, 44.0),
    (13 * 3600 + 30 * 60, 36.0),
    (14 * 3600, 28.0),
    (14 * 3600 + 30 * 60, 18.0),
    (14 * 3600 + 50 * 60, 9.0),
    (15 * 3600, 2.0),
)


def rounded(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def height_strength(height: int) -> float:
    if height in HEIGHT_STRENGTH:
        return HEIGHT_STRENGTH[height]
    if height > 7:
        return 55.0
    return 0.0


def rank_strength(rank: int | None) -> float:
    if rank is None:
        return 15.0
    if rank == 1:
        return 100.0
    if rank == 2:
        return 82.0
    return max(25.0, 72.0 - (rank - 3) * 10.0)


def breadth_strength(count: int) -> float:
    if count <= 0:
        return 0.0
    return min(100.0, 25.0 + 15.0 * math.sqrt(count))


def clock_seconds(value: str | None) -> int | None:
    if not value:
        return None
    try:
        hour, minute, second = (int(part) for part in value.split(":"))
    except (TypeError, ValueError):
        return None
    return hour * 3600 + minute * 60 + second


def absolute_seal_strength(value: str | None) -> float:
    seconds = clock_seconds(value)
    if seconds is None:
        return 0.0
    if seconds <= SEAL_TIME_POINTS[0][0]:
        return SEAL_TIME_POINTS[0][1]
    if seconds >= SEAL_TIME_POINTS[-1][0]:
        return SEAL_TIME_POINTS[-1][1]
    for (left_time, left_score), (right_time, right_score) in zip(
        SEAL_TIME_POINTS,
        SEAL_TIME_POINTS[1:],
    ):
        if left_time <= seconds <= right_time:
            ratio = (seconds - left_time) / (right_time - left_time)
            return left_score + (right_score - left_score) * ratio
    return 0.0


def member_brief(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code_of(row.get("code")),
        "name": row.get("name"),
        "height": as_int(row.get("boards")) or 0,
        "first_seal": seal_time(row.get("first_limit_ts")),
    }


def timeline_groups(
    natural_members: list[dict[str, Any]],
    candidate_code: str,
    candidate_ts: int | None,
) -> dict[str, Any]:
    peers = [
        row
        for row in natural_members
        if code_of(row.get("code")) != candidate_code
    ]
    before: list[dict[str, Any]] = []
    same: list[dict[str, Any]] = []
    after: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for row in peers:
        peer_ts = as_int(row.get("first_limit_ts"))
        if candidate_ts is None or peer_ts is None:
            missing.append(row)
        elif peer_ts < candidate_ts:
            before.append(row)
        elif peer_ts == candidate_ts:
            same.append(row)
        else:
            after.append(row)

    sorter = lambda row: (as_int(row.get("first_limit_ts")) or 10**20, code_of(row.get("code")))
    before.sort(key=sorter)
    same.sort(key=sorter)
    after.sort(key=sorter)
    missing.sort(key=lambda row: code_of(row.get("code")))
    return {
        "natural_peer_count": len(peers),
        "timed_peer_count": len(before) + len(same) + len(after),
        "before_count": len(before),
        "same_second_count": len(same),
        "after_count": len(after),
        "missing_time_count": len(missing),
        "before": [member_brief(row) for row in before],
        "same_second": [member_brief(row) for row in same],
        "after": [member_brief(row) for row in after],
        "missing_time": [member_brief(row) for row in missing],
    }


def relative_order_strength(timeline: dict[str, Any]) -> float:
    timed = int(timeline["timed_peer_count"])
    if timed == 0:
        return 50.0
    effective_before = (
        int(timeline["before_count"])
        + 0.5 * int(timeline["same_second_count"])
    )
    raw_score = 100.0 * (1.0 - effective_before / timed)
    # 一两个队友不足以把“最早”直接解释成满分，向中性 50 分收缩。
    evidence_weight = min(1.0, timed / 4.0)
    return 50.0 + (raw_score - 50.0) * evidence_weight


def propagation_strength(timeline: dict[str, Any]) -> tuple[float, dict[str, float]]:
    timed = int(timeline["timed_peer_count"])
    if timed == 0:
        return 0.0, {
            "effective_after_count": 0.0,
            "after_share_pct": 0.0,
            "after_count_strength": 0.0,
        }
    effective_after = (
        int(timeline["after_count"])
        + 0.5 * int(timeline["same_second_count"])
    )
    after_share = effective_after / timed * 100.0
    count_score = 100.0 * (1.0 - math.exp(-effective_after / 5.0))
    score = 0.45 * after_share + 0.55 * count_score
    return rounded(score), {
        "effective_after_count": round(effective_after, 2),
        "after_share_pct": round(after_share, 2),
        "after_count_strength": rounded(count_score),
    }


def candidate_role_strength(
    *,
    current_member: bool,
    candidate_height: int,
    natural_members: list[dict[str, Any]],
) -> tuple[float, str, int | None, int]:
    heights = [as_int(row.get("boards")) or 0 for row in natural_members]
    sector_max = max(heights, default=None)
    sector_max_count = (
        sum(height == sector_max for height in heights)
        if sector_max is not None
        else 0
    )
    if not current_member:
        return 35.0, "沿途题材关联，但节点日有效自然题材不在该板块", sector_max, sector_max_count
    if candidate_height == sector_max and sector_max_count == 1:
        return 100.0, "节点日有效自然题材成员，且为唯一最高身位", sector_max, sector_max_count
    if candidate_height == sector_max:
        return 84.0, "节点日有效自然题材成员，且并列最高身位", sector_max, sector_max_count
    gap = max(1, int(sector_max or candidate_height) - candidate_height)
    return (
        max(30.0, 70.0 - 15.0 * gap),
        f"节点日有效自然题材成员，但低于板块最高身位{gap}板",
        sector_max,
        sector_max_count,
    )


def theme_profile(
    *,
    candidate: dict[str, Any],
    raw_candidate: dict[str, Any],
    theme_evidence: dict[str, Any],
    context: dict[str, Any],
    reason_by_theme: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    theme = str(theme_evidence.get("theme") or "").strip()
    candidate_code = candidate["code"]
    candidate_height = int(candidate["height"])
    candidate_ts = as_int(raw_candidate.get("first_limit_ts"))
    identities = context["identities"]
    raw_current_members = [
        row
        for row in context["stocks"]
        if str(row.get("theme") or "").strip() == theme
    ]
    effective_members = [
        row
        for row in context["stocks"]
        if str(
            identities[code_of(row.get("code"))].get("effective_theme")
            or row.get("theme")
            or ""
        ).strip() == theme
    ]
    natural_members = [
        row
        for row in effective_members
        if not identities[code_of(row.get("code"))]["announcement"]
    ]
    announcement_members = [
        row
        for row in effective_members
        if identities[code_of(row.get("code"))]["announcement"]
    ]
    candidate_effective_theme = str(
        identities[candidate_code].get("effective_theme")
        or raw_candidate.get("theme")
        or ""
    ).strip()
    current_member = candidate_effective_theme == theme
    timeline = timeline_groups(
        natural_members,
        candidate_code,
        candidate_ts,
    )

    reason = reason_by_theme.get(theme) or {}
    reason_rank = as_int(reason.get("rank"))
    reported_count = as_int(reason.get("reported_count")) or 0
    market_count = reported_count if reason_rank is not None else len(raw_current_members)
    rank_score = rank_strength(reason_rank)
    breadth_score = breadth_strength(market_count)
    market_score = rounded(0.80 * rank_score + 0.20 * breadth_score)

    role_score, role, sector_max, sector_max_count = candidate_role_strength(
        current_member=current_member,
        candidate_height=candidate_height,
        natural_members=natural_members,
    )

    first_seal = seal_time(candidate_ts)
    absolute_score = absolute_seal_strength(first_seal)
    order_score = relative_order_strength(timeline)
    initiative_score = rounded(0.55 * absolute_score + 0.45 * order_score)
    propagation_score, propagation_parts = propagation_strength(timeline)

    return {
        "theme": theme,
        "current_theme_matched": current_member,
        "raw_current_theme_matched": (
            str(raw_candidate.get("theme") or "").strip() == theme
        ),
        "route_path_steps": theme_evidence.get("path_steps") or [],
        "limit_reason_rank": reason_rank,
        "limit_reason_reported_count": reported_count,
        "pool_current_theme_count": len(raw_current_members),
        "pool_effective_natural_theme_count": len(effective_members),
        "reported_count_matches_pool": (
            reported_count == len(raw_current_members)
            if reason_rank is not None
            else None
        ),
        "market_score_parts": {
            "rank_strength": rounded(rank_score),
            "breadth_strength": rounded(breadth_score),
            "ranking_contract": (
                "开盘啦市场动向榜名次占80%，题材家数占20%；"
                "同期客户端画面确认排序为家数、题材成交额"
            ),
        },
        "candidate_role": role,
        "candidate_role_parts": {
            "natural_effective_theme_members": len(natural_members),
            "announcement_effective_theme_members": len(announcement_members),
            "sector_natural_max_height": sector_max,
            "sector_natural_max_height_count": sector_max_count,
        },
        "timeline": timeline,
        "initiative_parts": {
            "candidate_first_seal": first_seal,
            "absolute_time_strength": rounded(absolute_score),
            "relative_order_strength": rounded(order_score),
            "absolute_time_weight": 0.55,
            "relative_order_weight": 0.45,
        },
        "propagation_parts": propagation_parts,
        "component_scores": {
            "market_theme_position": market_score,
            "candidate_theme_role": rounded(role_score),
            "seal_initiative": initiative_score,
            "post_seal_propagation": propagation_score,
        },
        "theme_thesis_score": rounded(
            (
                market_score
                + role_score
                + initiative_score
                + propagation_score
            )
            / 4.0
        ),
        "announcement_volume": [
            {
                **member_brief(row),
                "announcement_type": identities[code_of(row.get("code"))][
                    "announcement_type"
                ],
                "one_price": is_one_price(row),
            }
            for row in announcement_members
        ],
    }


def grade_of(score: float) -> str:
    if score >= 85:
        return "强"
    if score >= 75:
        return "偏强"
    if score >= 65:
        return "中上"
    if score >= 55:
        return "观察"
    return "弱"


def score_candidate(
    *,
    candidate: dict[str, Any],
    raw_candidate: dict[str, Any],
    context: dict[str, Any],
    selection: dict[str, Any],
    reason_by_theme: dict[str, dict[str, Any]],
    natural_layer_count: int,
) -> dict[str, Any]:
    theme_evidence_rows = list(candidate.get("route_theme_evidence") or [])
    if not theme_evidence_rows and (
        candidate.get("effective_theme") or candidate.get("theme")
    ):
        theme_evidence_rows = [{
            "theme": candidate.get("effective_theme") or candidate["theme"],
            "path_steps": [],
        }]
    profiles = [
        theme_profile(
            candidate=candidate,
            raw_candidate=raw_candidate,
            theme_evidence=row,
            context=context,
            reason_by_theme=reason_by_theme,
        )
        for row in theme_evidence_rows
    ]
    if not profiles:
        raise ValueError(f"{candidate['name']} 没有可评分的连续连板 theme")

    best = max(
        profiles,
        key=lambda row: (
            row["theme_thesis_score"],
            bool(row["current_theme_matched"]),
            -(row["limit_reason_rank"] or 10**6),
        ),
    )
    model_score = MODEL_STRENGTH.get(selection.get("model"), 0.0)
    height_score = height_strength(int(candidate["height"]))
    layer_score = rounded(0.60 * model_score + 0.40 * height_score)
    components = {
        "layer_model_height": layer_score,
        **best["component_scores"],
    }
    contributions = {
        name: round(components[name] * weight, 2)
        for name, weight in WEIGHTS.items()
    }
    candidate_evidence_score = rounded(sum(contributions.values()))

    warnings = []
    if not best["current_theme_matched"]:
        warnings.append("命中来自沿途题材，但不等于节点日有效自然题材，板块核心地位不直接记入")
    if best["limit_reason_rank"] is None:
        warnings.append("评分题材未进入节点日涨停原因榜，市场题材分受限")
    if best["timeline"]["missing_time_count"]:
        warnings.append("部分自然队友缺首封时间，时序分证据不完整")
    if best["reported_count_matches_pool"] is False:
        warnings.append("开盘啦榜单报告家数与本地主theme池数量不同；排名仍以开盘啦报告家数为准")
    if best["timeline"]["timed_peer_count"] == 0:
        warnings.append("没有可比较的自然队友首封，不能证明板块传播")

    first_seal = seal_time(raw_candidate.get("first_limit_ts"))
    return {
        "rank": None,
        "code": candidate["code"],
        "name": candidate["name"],
        "height": int(candidate["height"]),
        "expected_auction_score": None,
        "expectation_grade": None,
        "score_is_probability": False,
        "scoring_theme": best["theme"],
        "day_performance": {
            "current_theme": candidate.get("theme"),
            "effective_theme": candidate.get("effective_theme"),
            "open_pct": candidate.get("open_pct"),
            "first_seal": first_seal,
            "turnover_pct": candidate.get("turnover_pct"),
            "one_price": bool(candidate.get("one_price")),
            "one_price_direct_weight": 0.0,
        },
        "layer_context": {
            "model": selection.get("model"),
            "model_strength": rounded(model_score),
            "height_strength": rounded(height_score),
            "model_weight_inside_component": 0.60,
            "height_weight_inside_component": 0.40,
            "natural_candidate_count": natural_layer_count,
        },
        "component_scores": components,
        "candidate_evidence_contributions": contributions,
        "_candidate_evidence_score": candidate_evidence_score,
        "selected_theme_evidence": best,
        "alternative_theme_scores": [
            {
                "theme": row["theme"],
                "current_theme_matched": row["current_theme_matched"],
                "limit_reason_rank": row["limit_reason_rank"],
                "theme_thesis_score": row["theme_thesis_score"],
                "component_scores": row["component_scores"],
            }
            for row in sorted(
                profiles,
                key=lambda row: row["theme_thesis_score"],
                reverse=True,
            )
            if row is not best
        ],
        "warnings": warnings,
    }


def score_day(day: str) -> dict[str, Any]:
    selection = select_ladder(day)
    target_height = selection.get("target_height")
    if target_height is None:
        return {
            "policy_version": POLICY_VERSION,
            "stage": "node_close_auction_expectation",
            "date": day,
            "information_cutoff": day,
            "stage1": selection,
            "candidates": [],
            "status": "第一阶段没有目标梯队",
        }

    node = node_evidence(day, history_days=0)
    context = daily_stock_context(day)
    raw_by_code = {
        code_of(row.get("code")): row
        for row in context["stocks"]
    }
    reason_by_theme = {
        row["theme"]: row
        for row in node["market"]["limit_reason_ranking"]
    }
    layer = [
        row
        for row in node["candidates"]
        if int(row["height"]) == int(target_height)
    ]
    natural_layer = [row for row in layer if not row.get("announcement")]
    announcement_layer = [row for row in layer if row.get("announcement")]
    candidates = [
        score_candidate(
            candidate=row,
            raw_candidate=raw_by_code[row["code"]],
            context=context,
            selection=selection,
            reason_by_theme=reason_by_theme,
            natural_layer_count=len(natural_layer),
        )
        for row in natural_layer
    ]
    expected_pk = layer_pk_scores({
        row["code"]: float(row["_candidate_evidence_score"])
        for row in candidates
    })
    for row in candidates:
        candidate_evidence_score = float(row.pop("_candidate_evidence_score"))
        pk_score = expected_pk[row["code"]]
        expected_score, effective_weight = compose_score(
            candidate_evidence_score,
            pk_score,
        )
        row["expected_auction_score"] = expected_score
        row["expectation_grade"] = grade_of(expected_score)
        row["same_ladder_pk"] = {
            "available": pk_score is not None,
            "peer_count": max(0, len(candidates) - 1),
            "candidate_evidence_score": round(candidate_evidence_score, 2),
            "expected_pk_score": pk_score,
            "configured_weight": PK_WEIGHT,
            "effective_weight": effective_weight,
            "gap_scale": PK_GAP_SCALE,
            "contract": (
                "比较冻结梯队内全部自然票，不限题材；公告量能不参与。"
                if pk_score is not None
                else "梯队仅一只自然票，无对手，PK因子缺席且其余证据自动占满。"
            ),
        }
    candidates.sort(
        key=lambda row: (
            -row["expected_auction_score"],
            row["day_performance"]["first_seal"] or "99:99:99",
            row["code"],
        )
    )
    for index, row in enumerate(candidates, 1):
        row["rank"] = index

    return {
        "policy_version": POLICY_VERSION,
        "stage": "node_close_auction_expectation",
        "date": day,
        "information_cutoff": day,
        "stage1": {
            "target_height": target_height,
            "model": selection.get("model"),
            "reason": selection.get("reason"),
        },
        "score_semantics": (
            "节点日冻结的次日竞价预期分E；分越高，要求次日09:25给出越强的实际竞价"
        ),
        "weights": {
            "candidate_evidence_components": WEIGHTS,
            "same_ladder_pk": PK_WEIGHT,
        },
        "policy_parameters": {
            "model_strength": MODEL_STRENGTH,
            "height_strength": HEIGHT_STRENGTH,
            "layer_component": {"model": 0.60, "height": 0.40},
            "market_component": {"market_direction_rank": 0.80, "reported_count": 0.20},
            "initiative_component": {"absolute_first_seal": 0.55, "relative_order": 0.45},
            "propagation_component": {"after_share": 0.45, "after_count": 0.55},
            "same_ladder_pk": {
                "gap_scale": PK_GAP_SCALE,
                "configured_weight": PK_WEIGHT,
                "single_candidate_effective_weight": 0.0,
            },
        },
        "candidates": candidates,
        "excluded_announcement_structure": [
            {
                "code": row["code"],
                "name": row["name"],
                "height": row["height"],
                "announcement_type": row["announcement_type"],
                "role": "量能" if row["one_price"] else "公告结构",
                "one_price": row["one_price"],
            }
            for row in announcement_layer
        ],
        "contracts": {
            "future_data": "只读节点日T及以前；不调用next_trade_day，不读取T+1竞价或结果",
            "candidate_boundary": "只给第一阶段冻结梯队内的自然票排序；不得跨层",
            "same_ladder_pk": (
                "冻结梯队内全部自然票参与，不限题材；公告量能排除。"
                "单票梯队不造50分，PK权重归零"
            ),
            "theme": node["theme_contract"],
            "theme_selection": (
                "公告身份只按节点日最高板theme判定；节点日为自然票时，"
                "二板起沿途每个真实theme分别形成完整论点，禁止跨theme拼分"
            ),
            "announcement": node["announcement_contract"],
            "one_price": "一字形态本身直接权重为0；只能通过首封时刻、板块地位和此后传播体现",
        },
        "source_gaps": [
            "原始涨停池只有首封时间，没有末封时间、开板次数和候选首封瞬间仍在封板的队友数",
            "因此前/同秒/后只描述首次触板顺序，不宣称队友当时仍封住，也不宣称因果带动",
            "当前分值是竞价预期刻度，不是次日连板概率或百分比成功率",
        ],
    }


def markdown_score(result: dict[str, Any]) -> str:
    stage1 = result["stage1"]
    lines = [
        f"## {result['date']}｜{stage1.get('target_height') or '无'}板｜模型={stage1.get('model') or '无'}",
        "",
        result.get("score_semantics") or result.get("status") or "",
    ]
    candidates = result.get("candidates") or []
    if candidates:
        lines.extend([
            "",
            "|名次|候选|竞价预期E|自身证据|预期PK|评分题材|榜位|节点日theme|首封|自然队友 前/同秒/后|市场|板块地位|主动性|传播|",
            "|---:|---|---:|---:|---:|---|---:|:---:|---|---:|---:|---:|---:|---:|",
        ])
        for row in candidates:
            evidence = row["selected_theme_evidence"]
            timeline = evidence["timeline"]
            scores = row["component_scores"]
            lines.append(
                f"|{row['rank']}|{row['name']}({row['code']})|{row['expected_auction_score']:.2f} {row['expectation_grade']}|"
                f"{row['same_ladder_pk']['candidate_evidence_score']:.2f}|"
                f"{row['same_ladder_pk']['expected_pk_score'] if row['same_ladder_pk']['expected_pk_score'] is not None else '—'}|"
                f"{row['scoring_theme']}|{evidence['limit_reason_rank'] or '榜外'}|"
                f"{'是' if evidence['current_theme_matched'] else '否'}|"
                f"{row['day_performance']['first_seal'] or '缺失'}|"
                f"{timeline['before_count']}/{timeline['same_second_count']}/{timeline['after_count']}|"
                f"{scores['market_theme_position']:.2f}|{scores['candidate_theme_role']:.2f}|"
                f"{scores['seal_initiative']:.2f}|{scores['post_seal_propagation']:.2f}|"
            )
        for row in candidates:
            if row["warnings"]:
                lines.append("")
                lines.append(
                    f"- {row['name']}：" + "；".join(row["warnings"])
                )
    else:
        lines.extend(["", "- 无自然候选"])

    announcements = result.get("excluded_announcement_structure") or []
    if announcements:
        lines.extend(["", "公告结构（不评分）："])
        for row in announcements:
            lines.append(
                f"- {row['name']}({row['code']})：{row['announcement_type']} / {row['role']}"
            )
    if result.get("contracts"):
        lines.extend([
            "",
            "口径：一字本身直接权重为 0；日内主动性与首封后传播合计 40%。"
            "多票梯队在自身证据外加入同梯队PK；单票梯队自动取消PK。"
            "只读节点日，不含 T+1；当前分数是竞价预期E，不是连板成功率。",
        ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="+", help="节点日 YYYY-MM-DD")
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    args = parser.parse_args(argv)
    results = [score_day(day) for day in args.dates]
    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print("\n\n".join(markdown_score(result) for result in results))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
