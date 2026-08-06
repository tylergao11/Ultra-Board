# -*- coding: utf-8 -*-
"""第一阶段统一选层器：进攻模型优先，其次逐层检查防守模型，皆无则看自然二板。

选择器只调用节点日证据包，不读取 T+1、人工标签或隔离区。只有显式执行
``backtest --labels ...`` 时，才把外部人工标签用于结果对照；标签永不进入选层。

用法：

  python -m ultraboard.review.ladder_selector select 2026-06-01
  python -m ultraboard.review.ladder_selector backtest --labels PATH
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ultraboard.kaipanla.ladder_evidence import node_evidence


POLICY_VERSION = "stage1_attack_first_v9_route_theme_semantics"
MODEL_ATTACK = "进攻模型"
MODEL_DEFENSE = "防守模型"
MODEL_NONE = "无"

# 节点日市场动向榜按家数、题材成交额排序后，取严格前二。
ATTACK_LIMIT_REASON_TOP_N = 2


def _by_height(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["height"]), []).append(row)
    return grouped


def _attack_triggers(row: dict[str, Any]) -> list[dict[str, Any]]:
    if row.get("announcement"):
        return []
    triggers = []
    for theme in row.get("route_theme_evidence") or []:
        reason_rank = theme.get("limit_reason_rank")
        if reason_rank is not None and theme.get("limit_reason_top_two_matched"):
            triggers.append({
                "theme": theme["theme"],
                "limit_reason_rank": int(reason_rank),
                "reported_count": int(
                    theme.get("limit_reason_reported_count") or 0
                ),
            })
    return sorted(
        triggers,
        key=lambda item: (
            item["limit_reason_rank"],
            item["theme"],
        ),
    )


def _stock_brief(row: dict[str, Any]) -> dict[str, Any]:
    if row.get("announcement"):
        role = "量能" if row.get("one_price") else "公告结构"
    else:
        role = "自然候选"
    return {
        "code": row["code"],
        "name": row["name"],
        "height": int(row["height"]),
        "role": role,
        "announcement": bool(row.get("announcement")),
        "announcement_type": row.get("announcement_type"),
        "announcement_origin_date": row.get("announcement_origin_date"),
        "one_price": bool(row.get("one_price")),
        "route_themes": row.get("route_themes") or [],
        "attack_themes": _attack_triggers(row),
    }


def select_ladder(day: str) -> dict[str, Any]:
    evidence = node_evidence(day, history_days=0)
    rows = evidence["candidates"]
    grouped = _by_height(rows)
    natural_rows = [row for row in rows if not row.get("announcement")]
    natural_highest = max(
        (int(row["height"]) for row in natural_rows),
        default=None,
    )

    highest_rows = (
        [row for row in natural_rows if int(row["height"]) == natural_highest]
        if natural_highest is not None
        else []
    )
    attack_triggers = [
        {
            "code": row["code"],
            "name": row["name"],
            "themes": _attack_triggers(row),
        }
        for row in highest_rows
        if _attack_triggers(row)
    ]

    defense_checks = []
    for height in sorted(
        {int(row["height"]) for row in natural_rows},
        reverse=True,
    ):
        layer = grouped.get(height) or []
        natural_layer = [row for row in layer if not row.get("announcement")]
        anchors = [row for row in layer if row.get("one_price")]
        anchor_rows = [
            {
                "code": row["code"],
                "name": row["name"],
                "announcement": bool(row.get("announcement")),
                "role": "量能" if row.get("announcement") else "自然一字",
            }
            for row in anchors
        ]
        defense_checks.append({
            "height": height,
            "valid": bool(natural_layer and anchor_rows),
            "natural_candidates": [
                {"code": row["code"], "name": row["name"]}
                for row in natural_layer
            ],
            "one_price_anchors": anchor_rows,
            "natural_one_price_anchors": [
                row for row in anchor_rows if not row["announcement"]
            ],
            "announcement_one_price_anchors": [
                row for row in anchor_rows if row["announcement"]
            ],
        })

    selected_height: int | None
    model: str | None
    selected_by: str
    reason: str
    if natural_highest is not None and attack_triggers:
        selected_height = natural_highest
        model = MODEL_ATTACK
        selected_by = "highest_natural_market_direction_top2_attack"
        trigger_text = "、".join(
            f"{item['name']}:{'/'.join(theme['theme'] for theme in item['themes'])}"
            for item in attack_triggers
        )
        reason = (
            f"最高自然梯队为{selected_height}板，沿途theme命中市场动向榜前二："
            f"{trigger_text}；模型=进攻模型"
        )
    else:
        # defense_checks 已按高度降序；取首个有效结构，不能越过三板直接落到二板。
        valid_defense = next(
            (item for item in defense_checks if item["valid"]),
            None,
        )
        if valid_defense:
            selected_height = int(valid_defense["height"])
            model = MODEL_DEFENSE
            selected_by = "highest_valid_defense_structure"
            anchor_text = "、".join(
                f"{item['name']}({item['role']})"
                for item in valid_defense["one_price_anchors"]
            )
            reason = (
                "最高自然梯队未形成进攻模型；防守模型按高度从高到低检查，"
                "选择首个含合格真一字锚与自然候选的梯队。"
                f"本次为{selected_height}板：{anchor_text}；模型=防守模型"
            )
        elif any(int(row["height"]) == 2 for row in natural_rows):
            selected_height = 2
            model = MODEL_NONE
            selected_by = "natural_two_board_floor_fallback"
            reason = "进攻模型与防守模型均不成立；存在自然二板，梯队下沉到二板"
        else:
            selected_height = None
            model = None
            selected_by = "no_natural_two_board_candidate"
            reason = "进攻模型与防守模型均不成立，且不存在自然二板候选；本日不选层"

    selected_rows = grouped.get(selected_height, []) if selected_height else []
    return {
        "policy_version": POLICY_VERSION,
        "stage": "node_close_ladder_selection",
        "date": day,
        "information_cutoff": day,
        "target_height": selected_height,
        "model": model,
        "selected_by": selected_by,
        "reason": reason,
        "natural_highest": natural_highest,
        "attack_check": {
            "only_height": natural_highest,
            "limit_reason_top_n": ATTACK_LIMIT_REASON_TOP_N,
            "ranking_contract": evidence["market"]["limit_reason_ranking_contract"],
            "matched": bool(attack_triggers),
            "triggers": attack_triggers,
        },
        "defense_checks": defense_checks,
        "selected_layer": [_stock_brief(row) for row in selected_rows],
        "limit_reason_top_two": evidence["market"]["limit_reason_top_two"],
        "contracts": {
            "future_data": "禁止读取T+1；本结果只使用information_cutoff当日及以前",
            "announcement": evidence["announcement_contract"],
            "theme": evidence["theme_contract"],
            "defense": (
                "同层至少一只真一字与至少一只自然票；可为同一只股票，"
                "不要求同题材，不使用高层题材压制；进攻模型命中时一律进攻优先"
            ),
            "candidate_boundary": "脚本只选梯队；第二阶段AI只能在已选梯队内选票或放弃",
        },
    }


def load_labels(path: Path, *, include_review: bool) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    labels = payload.get("labels") or []
    accepted_statuses = {"locked"}
    if include_review:
        accepted_statuses.add("policy_changed_review")
    return [row for row in labels if row.get("status", "locked") in accepted_statuses]


def backtest(path: Path, *, include_review: bool = False) -> dict[str, Any]:
    labels = load_labels(path, include_review=include_review)
    rows = []
    for label in labels:
        prediction = select_ladder(str(label["date"]))
        expected_height = label.get("target_height")
        expected_model = label.get("model")
        height_hit = prediction["target_height"] == expected_height
        model_hit = (
            prediction["model"] == expected_model
            if expected_model is not None
            else None
        )
        rows.append({
            "date": label["date"],
            "status": label.get("status", "locked"),
            "expected_height": expected_height,
            "predicted_height": prediction["target_height"],
            "height_hit": height_hit,
            "expected_model": expected_model,
            "predicted_model": prediction["model"],
            "model_hit": model_hit,
            "joint_hit": height_hit and (model_hit is not False),
            "selected_by": prediction["selected_by"],
            "reason": prediction["reason"],
            "note": label.get("note"),
        })

    model_rows = [row for row in rows if row["model_hit"] is not None]
    return {
        "policy_version": POLICY_VERSION,
        "evaluation": "人工冻结标签一致率，不是次日交易成功率",
        "label_path": str(path),
        "sample_count": len(rows),
        "height": {
            "hits": sum(row["height_hit"] for row in rows),
            "total": len(rows),
        },
        "model": {
            "hits": sum(bool(row["model_hit"]) for row in model_rows),
            "total": len(model_rows),
        },
        "joint": {
            "hits": sum(row["joint_hit"] for row in rows),
            "total": len(rows),
        },
        "mismatches": [row for row in rows if not row["joint_hit"]],
        "rows": rows,
    }


def markdown_selection(result: dict[str, Any]) -> str:
    lines = [
        f"## {result['date']}｜{result['target_height'] or '无'}板｜模型={result['model'] or '无目标'}",
        "",
        result["reason"],
        f"最高自然梯队：{result['natural_highest'] or '无'}板",
        "",
        "目标层角色：",
    ]
    for row in result["selected_layer"]:
        tags = [row["role"]]
        if row["one_price"]:
            tags.append("一字")
        if row["announcement_type"]:
            tags.append(row["announcement_type"])
        lines.append(f"- {row['name']}({row['code']})：{' / '.join(tags)}")
    if not result["selected_layer"]:
        lines.append("- 无")
    lines.extend([
        "",
        "涨停原因发酵前二：" + "、".join(
            f"{row['rank']}.{row['theme']}({row['reported_count']}家/"
            f"{row['turnover_amount'] / 1e8:.2f}亿)"
            for row in result["limit_reason_top_two"]
        ),
        "",
        "信息边界：只到节点日收盘，不含 T+1。",
    ])
    return "\n".join(lines)


def markdown_backtest(result: dict[str, Any]) -> str:
    height = result["height"]
    model = result["model"]
    joint = result["joint"]
    lines = [
        "# 第一阶段回测",
        "",
        f"样本：{result['sample_count']}（人工冻结标签一致率，不是次日成功率）",
        f"梯队：{height['hits']}/{height['total']}",
        f"模型：{model['hits']}/{model['total']}",
        f"联合：{joint['hits']}/{joint['total']}",
        "",
        "|日期|人工|算法|模型|结果|原因|",
        "|---|---:|---:|---|:---:|---|",
    ]
    for row in result["rows"]:
        expected_model = row["expected_model"] or "未标"
        verdict = "✓" if row["joint_hit"] else "✗"
        lines.append(
            f"|{row['date']}|{row['expected_height']}板/{expected_model}|"
            f"{row['predicted_height']}板/{row['predicted_model']}|"
            f"{row['selected_by']}|{verdict}|{row['reason']}|"
        )
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

    select_parser = subparsers.add_parser("select", help="只使用节点日证据统一选层")
    select_parser.add_argument("dates", nargs="+", help="节点日 YYYY-MM-DD")
    select_parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )

    backtest_parser = subparsers.add_parser(
        "backtest", help="显式读取外部人工标签做一致率对照"
    )
    backtest_parser.add_argument("--labels", type=Path, required=True)
    backtest_parser.add_argument("--include-review", action="store_true")
    backtest_parser.add_argument(
        "--format", choices=("markdown", "json"), default="markdown"
    )

    args = parser.parse_args(argv)
    if args.command == "select":
        emit(
            [select_ladder(day) for day in args.dates],
            args.format,
            markdown_selection,
        )
    else:
        result = backtest(args.labels, include_review=args.include_review)
        emit(result, args.format, markdown_backtest)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
