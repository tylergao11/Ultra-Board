# -*- coding: utf-8 -*-
"""冻结梯队内的相对强弱 PK。

PK 不是新的选层规则，只在第一阶段已经冻结的自然票之间比较。节点日和次日
竞价使用同一套成对胜率刻度，分别得到预期 PK 与实际 PK；单票梯队没有对手，
该因子直接缺席，不伪造 50 分。
"""
from __future__ import annotations

import math


POLICY_VERSION = "same_ladder_pk_v1"

# 分差为 10 分时，成对强弱约为 73/27；20 分时约为 88/12。
PK_GAP_SCALE = 10.0

# 后验首轮显示层内相对强弱有信息，但高权重会恶化绝对刻度误差；先以 10%
# 小步接入。后验入口继续报告 0/10/20/30% 对照，禁止单日调参。
PK_WEIGHT = 0.10
PK_WEIGHT_CANDIDATES = (0.0, 0.10, 0.20, 0.30)


def clamp(value: float) -> float:
    return max(0.0, min(100.0, value))


def pairwise_strength(left: float, right: float) -> float:
    """把两票分差映射成 0~100 的相对强弱，分差相等时为 50。"""
    exponent = -(float(left) - float(right)) / PK_GAP_SCALE
    return 100.0 / (1.0 + math.exp(exponent))


def layer_pk_scores(scores: dict[str, float]) -> dict[str, float | None]:
    """返回每票对同梯队其余自然票的平均成对强弱。"""
    if len(scores) < 2:
        return {code: None for code in scores}

    result: dict[str, float | None] = {}
    for code, score in scores.items():
        comparisons = [
            pairwise_strength(score, peer_score)
            for peer_code, peer_score in scores.items()
            if peer_code != code
        ]
        result[code] = round(sum(comparisons) / len(comparisons), 2)
    return result


def compose_score(
    candidate_evidence_score: float,
    pk_score: float | None,
    *,
    weight: float = PK_WEIGHT,
) -> tuple[float, float]:
    """合成最终分，并返回实际生效的 PK 权重。"""
    if not 0.0 <= weight <= 1.0:
        raise ValueError(f"PK 权重必须在 0~1，收到 {weight}")
    effective_weight = weight if pk_score is not None else 0.0
    score = (
        float(candidate_evidence_score) * (1.0 - effective_weight)
        + float(pk_score or 0.0) * effective_weight
    )
    return round(clamp(score), 2), effective_weight
