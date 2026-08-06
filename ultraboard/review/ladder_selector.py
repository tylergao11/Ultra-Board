# -*- coding: utf-8 -*-
"""节点批次选层器：节点日冻结一次，普通交易日只追踪最近节点批次。

节点日内部仍按进攻模型优先、防守模型次之、皆无则看自然二板。查询任意交易日
时，先回溯最近有效节点，再追踪当日冻结的原始成员；禁止用查询日的新梯队重选。
选择与追踪均不读取查询日之后、人工标签或隔离区。只有显式执行
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

from ultraboard.kaipanla.ladder_evidence import (
    available_trade_days,
    node_evidence,
    raw_stock_map,
)
from ultraboard.review.break_nodes import detect_break_node, latest_break_node


POLICY_VERSION = "stage1_node_batch_v10_active_tracking"
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


def _freeze_node_ladder(
    day: str,
    node_trigger: dict[str, Any],
) -> dict[str, Any]:
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
        "stage": "node_batch_frozen_selection",
        "date": day,
        "query_date": day,
        "node_date": day,
        "is_node_date": True,
        "information_cutoff": day,
        "selection_information_cutoff": day,
        "node_trigger": node_trigger,
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
            "node_trigger": (
                "上一交易日最高自然梯队全部断板才形成节点；"
                "只要仍有一只晋级就不产生新节点"
            ),
            "batch": (
                "目标梯队只在节点日冻结一次；后续交易日不得用当日新梯队重选或补入新票"
            ),
            "announcement": evidence["announcement_contract"],
            "theme": evidence["theme_contract"],
            "defense": (
                "同层至少一只真一字与至少一只自然票；可为同一只股票，"
                "不要求同题材，不使用高层题材压制；进攻模型命中时一律进攻优先"
            ),
            "candidate_boundary": "脚本只选梯队；第二阶段AI只能在已选梯队内选票或放弃",
        },
    }


def select_node_ladder(day: str) -> dict[str, Any]:
    """严格在真实节点日冻结目标梯队；非节点日拒绝重新选层。"""
    node_trigger = detect_break_node(day)
    if not node_trigger["is_break_node"]:
        raise ValueError(f"{day} 不是节点日：{node_trigger['reason']}")
    return _freeze_node_ladder(day, node_trigger)


def _track_batch_member(
    member: dict[str, Any],
    *,
    node_date: str,
    query_date: str,
    trade_days: list[str],
) -> dict[str, Any]:
    node_height = int(member["height"])
    last_height = node_height
    last_active_date = node_date
    exit_date: str | None = None
    observed_exit_height: int | None = None
    current_theme = (
        (raw_stock_map(node_date).get(member["code"]) or {}).get("theme") or ""
    )

    node_index = trade_days.index(node_date)
    query_index = trade_days.index(query_date)
    for route_day in trade_days[node_index + 1 : query_index + 1]:
        stock = raw_stock_map(route_day).get(member["code"])
        actual_height = int(stock.get("boards") or 0) if stock else None
        if actual_height == last_height + 1:
            last_height = actual_height
            last_active_date = route_day
            current_theme = stock.get("theme") or ""
            continue
        exit_date = route_day
        observed_exit_height = actual_height
        break

    active = exit_date is None
    return {
        **member,
        "node_height": node_height,
        "status": "active" if active else "exited",
        "status_label": "在队" if active else "断板离队",
        "current_height": last_height if active else None,
        "last_height": last_height,
        "last_active_date": last_active_date,
        "exit_date": exit_date,
        "observed_exit_height": observed_exit_height,
        "current_theme": current_theme if active else None,
    }


def _track_frozen_batch(
    frozen: dict[str, Any],
    query_date: str,
) -> list[dict[str, Any]]:
    trade_days = list(available_trade_days())
    if query_date not in trade_days:
        raise ValueError(f"不存在交易日数据: {query_date}")
    node_date = str(frozen["node_date"])
    if trade_days.index(query_date) < trade_days.index(node_date):
        raise ValueError(f"查询日 {query_date} 早于节点日 {node_date}")
    return [
        _track_batch_member(
            member,
            node_date=node_date,
            query_date=query_date,
            trade_days=trade_days,
        )
        for member in frozen["selected_layer"]
    ]


def _no_active_node(day: str) -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "stage": "active_node_batch_tracking",
        "date": day,
        "query_date": day,
        "node_date": None,
        "is_node_date": False,
        "information_cutoff": day,
        "selection_information_cutoff": None,
        "node_trigger": None,
        "target_height": None,
        "model": None,
        "selected_by": "no_active_break_node",
        "reason": f"截至{day}尚未检测到有效节点，无法建立节点批次",
        "tracking_reason": "没有可继承的节点批次",
        "natural_highest": None,
        "attack_check": {},
        "defense_checks": [],
        "selected_layer": [],
        "batch_members": [],
        "active_layer": [],
        "active_natural_candidates": [],
        "limit_reason_top_two": [],
        "contracts": {
            "future_data": f"只读取{day}及以前，不读取后续交易日",
            "node_trigger": (
                "上一交易日最高自然梯队全部断板才形成节点；"
                "只要仍有一只晋级就不产生新节点"
            ),
            "batch": "没有有效节点时不从普通交易日临时创建目标梯队",
        },
    }


def select_ladder(day: str) -> dict[str, Any]:
    """查询任意交易日所属的最近节点批次，并追踪冻结成员至当日。"""
    node_trigger = latest_break_node(day)
    if node_trigger is None:
        return _no_active_node(day)

    node_date = str(node_trigger["date"])
    frozen = _freeze_node_ladder(node_date, node_trigger)
    members = _track_frozen_batch(frozen, day)
    active_layer = [row for row in members if row["status"] == "active"]
    result = {
        **frozen,
        "stage": "active_node_batch_tracking",
        "date": day,
        "query_date": day,
        "is_node_date": day == node_date,
        "information_cutoff": day,
        "batch_members": members,
        "active_layer": active_layer,
        "active_natural_candidates": [
            row for row in active_layer if not row["announcement"]
        ],
        "tracking_reason": (
            f"{day}形成新节点并冻结本批次"
            if day == node_date
            else f"{day}未形成更新节点，沿用{node_date}冻结的节点批次"
        ),
    }
    result["contracts"] = {
        **frozen["contracts"],
        "future_data": (
            f"选层只读取{node_date}及以前；批次追踪只读取{day}及以前；"
            "不读取查询日后的交易数据"
        ),
    }
    return result


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
        prediction = select_node_ladder(str(label["date"]))
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
    node_date = result.get("node_date")
    if node_date is None:
        return "\n".join([
            f"## {result['date']}｜无有效节点批次",
            "",
            result["reason"],
            "",
            f"信息边界：只到{result['date']}，不含后续交易日。",
        ])

    if result["date"] == node_date:
        title = (
            f"## {result['date']}｜新节点批次{result['target_height'] or '无'}板｜"
            f"模型={result['model'] or '无目标'}"
        )
    else:
        title = (
            f"## {result['date']}｜沿用{node_date}节点批次｜"
            f"冻结{result['target_height'] or '无'}板｜模型={result['model'] or '无目标'}"
        )
    lines = [
        title,
        "",
        result["reason"],
        result.get("tracking_reason") or "",
        f"节点日最高自然梯队：{result['natural_highest'] or '无'}板",
        "",
        "冻结批次：",
    ]
    members = result.get("batch_members") or result["selected_layer"]
    for row in members:
        tags = [row["role"]]
        if row["one_price"]:
            tags.append("一字")
        if row["announcement_type"]:
            tags.append(row["announcement_type"])
        if row.get("status") == "active":
            tags.append(f"在队 {row['node_height']}→{row['current_height']}板")
        elif row.get("status") == "exited":
            tags.append(f"{row['exit_date']}断板离队")
        lines.append(f"- {row['name']}({row['code']})：{' / '.join(tags)}")
    if not members:
        lines.append("- 无")
    lines.extend([
        "",
        "节点日涨停原因发酵前二：" + "、".join(
            f"{row['rank']}.{row['theme']}({row['reported_count']}家/"
            f"{row['theme_amount'] / 1e8:.2f}亿)"
            for row in result["limit_reason_top_two"]
        ),
        "",
        (
            f"信息边界：选层截止{node_date}；批次追踪截止{result['date']}；"
            "不读取查询日后的交易数据。"
        ),
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

    select_parser = subparsers.add_parser(
        "select",
        help="查询任意交易日所属的最近节点批次",
    )
    select_parser.add_argument("dates", nargs="+", help="查询交易日 YYYY-MM-DD")
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
