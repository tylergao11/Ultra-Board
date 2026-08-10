# -*- coding: utf-8 -*-
"""校验、筛选并导出结构化历史案例。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "cases" / "manifest.json"
CASE_ID_RE = re.compile(r"^CASE-(\d{4}-\d{2}-\d{2})$")
REQUIRED_FIELDS = {
    "schema_version",
    "case_id",
    "record_id",
    "revision",
    "case_status",
    "retrieval_status",
    "setup_trade_date",
    "decision_cutoff",
    "replay_trade_date",
    "outcome_cutoff",
    "decision_record_mode",
    "decision_recorded_at",
    "case_compiled_at",
    "historical_replay_scope",
    "title",
    "case_question",
    "source",
    "retrieval_tags",
    "condition_axes",
    "market_structure",
    "decision",
    "outcome",
    "similarity",
    "legacy_fields",
    "supersedes",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def _manifest() -> dict[str, Any]:
    payload = _read_json(MANIFEST_PATH)
    if payload.get("schema_version") != 1:
        raise ValueError("案例 manifest 版本不受支持")
    return payload


def _record_paths(manifest: dict[str, Any]) -> list[Path]:
    pattern = manifest["record_glob"]
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("record_glob 必须是非空字符串")
    return sorted(ROOT.glob(str(Path(pattern).relative_to("."))))


def _records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in _record_paths(manifest):
        row = _read_json(path)
        row["_path"] = path
        result.append(row)
    return result


def _nonempty_string(value: Any, field: str, record_id: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{record_id} {field} 必须是非空字符串")
    return value


def _string_list(value: Any, field: str, record_id: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{record_id} {field} 必须是字符串数组")
    if len(value) != len(set(value)):
        raise ValueError(f"{record_id} {field} 不能包含重复值")
    return value


def _object(value: Any, field: str, record_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{record_id} {field} 必须是对象")
    return value


def _iso_date(value: Any, field: str, record_id: str) -> date:
    raw = _nonempty_string(value, field, record_id)
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{record_id} {field} 不是 ISO 日期") from exc


def _iso_datetime(
    value: Any,
    field: str,
    record_id: str,
    *,
    allow_none: bool = False,
) -> datetime | None:
    if value is None and allow_none:
        return None
    raw = _nonempty_string(value, field, record_id)
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{record_id} {field} 不是 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{record_id} {field} 必须包含时区")
    return parsed


def _positive_int_or_none(value: Any, field: str, record_id: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{record_id} {field} 必须是正整数或 null")
    return value


def _enum(
    value: Any,
    allowed: Iterable[str],
    field: str,
    record_id: str,
) -> str:
    raw = _nonempty_string(value, field, record_id)
    if raw not in set(allowed):
        raise ValueError(f"{record_id} {field} 非法: {raw}")
    return raw


def _validate_record(row: dict[str, Any], manifest: dict[str, Any]) -> None:
    path = row.pop("_path")
    missing = REQUIRED_FIELDS.difference(row)
    unknown = set(row).difference(REQUIRED_FIELDS)
    if missing:
        raise ValueError(f"{path} 缺少字段: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{path} 存在未知字段: {', '.join(sorted(unknown))}")
    if row["schema_version"] != manifest["schema_version"]:
        raise ValueError(f"{path} schema_version 与 manifest 不一致")

    record_id = _nonempty_string(row["record_id"], "record_id", str(path))
    case_id = _nonempty_string(row["case_id"], "case_id", record_id)
    match = CASE_ID_RE.fullmatch(case_id)
    if not match:
        raise ValueError(f"{record_id} case_id 格式非法")
    revision = row["revision"]
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise ValueError(f"{record_id} revision 必须是正整数")
    if record_id != f"{case_id}@{revision}":
        raise ValueError(f"{record_id} 必须等于 <case_id>@<revision>")
    if path.stem != record_id:
        raise ValueError(f"{record_id} 文件名必须与 record_id 一致")

    case_status = _enum(
        row["case_status"], manifest["allowed_case_statuses"], "case_status", record_id
    )
    retrieval_status = _enum(
        row["retrieval_status"],
        manifest["allowed_retrieval_statuses"],
        "retrieval_status",
        record_id,
    )
    if retrieval_status == "accepted" and case_status != "closed":
        raise ValueError(f"{record_id} accepted 案例必须已经 closed")

    setup_day = _iso_date(row["setup_trade_date"], "setup_trade_date", record_id)
    if setup_day.isoformat() != match.group(1):
        raise ValueError(f"{record_id} setup_trade_date 必须与 case_id 日期一致")
    replay_day = _iso_date(row["replay_trade_date"], "replay_trade_date", record_id)
    if replay_day <= setup_day:
        raise ValueError(f"{record_id} replay_trade_date 必须晚于 setup_trade_date")
    decision_cutoff = _iso_datetime(
        row["decision_cutoff"], "decision_cutoff", record_id
    )
    outcome_cutoff = _iso_datetime(row["outcome_cutoff"], "outcome_cutoff", record_id)
    compiled_at = _iso_datetime(row["case_compiled_at"], "case_compiled_at", record_id)
    if decision_cutoff.date() != setup_day:
        raise ValueError(f"{record_id} decision_cutoff 日期必须等于 setup_trade_date")
    if outcome_cutoff.date() < replay_day:
        raise ValueError(f"{record_id} outcome_cutoff 不能早于 replay_trade_date")
    if outcome_cutoff <= decision_cutoff:
        raise ValueError(f"{record_id} outcome_cutoff 必须晚于 decision_cutoff")

    mode = _enum(
        row["decision_record_mode"],
        manifest["allowed_decision_record_modes"],
        "decision_record_mode",
        record_id,
    )
    recorded_at = _iso_datetime(
        row["decision_recorded_at"],
        "decision_recorded_at",
        record_id,
        allow_none=True,
    )
    _enum(
        row["historical_replay_scope"],
        manifest["allowed_historical_replay_scopes"],
        "historical_replay_scope",
        record_id,
    )
    if mode == "contemporaneous" and recorded_at is None:
        raise ValueError(f"{record_id} contemporaneous 必须记录 decision_recorded_at")
    if mode == "contemporaneous" and recorded_at >= outcome_cutoff:
        raise ValueError(f"{record_id} contemporaneous 记录时间必须早于结果截点")
    if recorded_at is not None and compiled_at < recorded_at:
        raise ValueError(f"{record_id} case_compiled_at 不能早于 decision_recorded_at")

    _nonempty_string(row["title"], "title", record_id)
    _nonempty_string(row["case_question"], "case_question", record_id)

    source = _object(row["source"], "source", record_id)
    _enum(
        source.get("kind"), manifest["allowed_source_kinds"], "source.kind", record_id
    )
    _string_list(source.get("source_reports"), "source.source_reports", record_id)
    _string_list(source.get("source_issues"), "source.source_issues", record_id)

    retrieval_tags = _string_list(
        row["retrieval_tags"], "retrieval_tags", record_id
    )
    result_only = set(manifest["result_only_tags"])
    leaked = sorted(set(retrieval_tags).intersection(result_only))
    if leaked:
        raise ValueError(f"{record_id} 条件标签混入结果标签: {', '.join(leaked)}")

    axes = _object(row["condition_axes"], "condition_axes", record_id)
    expected_axes = set(manifest["condition_axes"])
    if set(axes) != expected_axes:
        raise ValueError(f"{record_id} condition_axes 必须恰好包含四个固定轴")
    for axis_name in manifest["condition_axes"]:
        axis = _object(axes[axis_name], f"condition_axes.{axis_name}", record_id)
        _nonempty_string(axis.get("summary"), f"{axis_name}.summary", record_id)
    height = axes["height_environment"]
    market_max = _positive_int_or_none(
        height.get("market_max_boards"), "market_max_boards", record_id
    )
    core_height = _positive_int_or_none(
        height.get("meaningful_core_boards"), "meaningful_core_boards", record_id
    )
    if not isinstance(height.get("regulatory_height_present"), bool):
        raise ValueError(f"{record_id} regulatory_height_present 必须是布尔值")
    if market_max is not None and height["regulatory_height_present"] != (market_max >= 7):
        raise ValueError(f"{record_id} 监管高度标记必须与市场最高板一致")
    if market_max is not None and core_height is not None and core_height > market_max:
        raise ValueError(f"{record_id} 有意义核心高度不能高于市场最高板")

    market = _object(row["market_structure"], "market_structure", record_id)
    if not isinstance(market.get("is_node_day"), bool):
        raise ValueError(f"{record_id} market_structure.is_node_day 必须是布尔值")
    _nonempty_string(
        market.get("broken_core_summary"), "broken_core_summary", record_id
    )
    _nonempty_string(
        market.get("closing_structure_summary"), "closing_structure_summary", record_id
    )

    decision = _object(row["decision"], "decision", record_id)
    _enum(decision.get("model"), manifest["allowed_models"], "decision.model", record_id)
    _positive_int_or_none(
        decision.get("defense_level_boards"), "defense_level_boards", record_id
    )
    selection_mode = _enum(
        decision.get("selection_mode"),
        manifest["allowed_selection_modes"],
        "decision.selection_mode",
        record_id,
    )
    primary_target = decision.get("primary_target")
    if primary_target is not None:
        _nonempty_string(primary_target, "decision.primary_target", record_id)
    conditional_targets = decision.get("conditional_targets")
    if not isinstance(conditional_targets, list):
        raise ValueError(f"{record_id} conditional_targets 必须是数组")
    frozen_targets = {primary_target} if primary_target is not None else set()
    for index, item in enumerate(conditional_targets):
        item = _object(item, f"conditional_targets[{index}]", record_id)
        target = _nonempty_string(
            item.get("target"), f"conditional_targets[{index}].target", record_id
        )
        if target in frozen_targets:
            raise ValueError(f"{record_id} 冻结目标不能重复: {target}")
        frozen_targets.add(target)
        _nonempty_string(item.get("trigger"), f"conditional_targets[{index}].trigger", record_id)
    if selection_mode == "unique" and primary_target is None:
        raise ValueError(f"{record_id} unique 决策必须有 primary_target")
    if selection_mode == "none" and (primary_target is not None or conditional_targets):
        raise ValueError(f"{record_id} none 决策不能包含目标")
    if selection_mode == "conditional" and primary_target is None and not conditional_targets:
        raise ValueError(f"{record_id} conditional 决策必须至少包含一条冻结路径")
    _nonempty_string(decision.get("frozen_plan"), "decision.frozen_plan", record_id)
    _string_list(
        decision.get("invalidation_conditions"),
        "decision.invalidation_conditions",
        record_id,
    )

    outcome = _object(row["outcome"], "outcome", record_id)
    trade_result = _enum(
        outcome.get("trade_result"),
        manifest["allowed_trade_results"],
        "outcome.trade_result",
        record_id,
    )
    executed_target = outcome.get("executed_target")
    if executed_target is not None:
        _nonempty_string(executed_target, "outcome.executed_target", record_id)
    if trade_result in {"sealed_limit", "failed_to_hold_limit"} and executed_target is None:
        raise ValueError(f"{record_id} 已发生交易时必须记录 executed_target")
    if trade_result == "no_trade" and executed_target is not None:
        raise ValueError(f"{record_id} no_trade 不能记录 executed_target")
    if executed_target is not None and executed_target not in frozen_targets:
        raise ValueError(f"{record_id} executed_target 必须来自节点日冻结路径")
    _nonempty_string(outcome.get("replay_summary"), "outcome.replay_summary", record_id)
    if not isinstance(outcome.get("follow_up_summary"), str):
        raise ValueError(f"{record_id} follow_up_summary 必须是字符串")
    _string_list(outcome.get("result_tags"), "outcome.result_tags", record_id)

    similarity = _object(row["similarity"], "similarity", record_id)
    _nonempty_string(
        similarity.get("environment_summary"), "similarity.environment_summary", record_id
    )
    _string_list(
        similarity.get("difference_boundaries"),
        "similarity.difference_boundaries",
        record_id,
    )
    if not isinstance(row["legacy_fields"], dict):
        raise ValueError(f"{record_id} legacy_fields 必须是对象")
    _string_list(row["supersedes"], "supersedes", record_id)


def validate(records: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    for row in records:
        _validate_record(row, manifest)
    by_record_id: dict[str, dict[str, Any]] = {}
    case_revisions: dict[str, set[int]] = {}
    for row in records:
        record_id = row["record_id"]
        if record_id in by_record_id:
            raise ValueError(f"record_id 重复: {record_id}")
        by_record_id[record_id] = row
        revisions = case_revisions.setdefault(row["case_id"], set())
        if row["revision"] in revisions:
            raise ValueError(f"{row['case_id']} revision 重复: {row['revision']}")
        revisions.add(row["revision"])

    superseded_ids: set[str] = set()
    for row in records:
        for old_id in row["supersedes"]:
            if old_id not in by_record_id:
                raise ValueError(f"{row['record_id']} supersedes 指向不存在记录: {old_id}")
            old = by_record_id[old_id]
            if old["case_id"] != row["case_id"]:
                raise ValueError(f"{row['record_id']} 不能替代其他 case_id 的记录")
            if old["revision"] >= row["revision"]:
                raise ValueError(f"{row['record_id']} 替代版本必须具有更高 revision")
            superseded_ids.add(old_id)
    for old_id in superseded_ids:
        if by_record_id[old_id]["retrieval_status"] != "superseded":
            raise ValueError(f"{old_id} 已被替代，retrieval_status 必须为 superseded")
    for case_id, rows in _group_by_case(records).items():
        active = [row for row in rows if row["retrieval_status"] != "superseded"]
        if len(active) > 1:
            raise ValueError(f"{case_id} 同时存在多个未替代版本")

    return {
        "source": str(ROOT / "data" / "cases" / "records"),
        "record_count": len(records),
        "case_count": len(case_revisions),
        "status_counts": {
            status: sum(row["retrieval_status"] == status for row in records)
            for status in manifest["allowed_retrieval_statuses"]
        },
        "valid": True,
    }


def _group_by_case(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        grouped.setdefault(row["case_id"], []).append(row)
    return grouped


def _parse_research_cutoff(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    parsed = _iso_datetime(raw, "research_cutoff", "query")
    assert parsed is not None
    return parsed


def _selected(
    records: list[dict[str, Any]],
    manifest: dict[str, Any],
    statuses: list[str],
    models: list[str],
    tags: list[str],
    research_cutoff: datetime | None,
) -> list[dict[str, Any]]:
    requested_statuses = set(statuses or manifest["default_retrieval_status"])
    requested_models = set(models)
    requested_tags = {tag.strip() for tag in tags if tag.strip()}
    selected: list[dict[str, Any]] = []
    for row in records:
        if row["retrieval_status"] not in requested_statuses:
            continue
        if row["case_status"] != "closed" and row["retrieval_status"] == "accepted":
            continue
        if requested_models and row["decision"]["model"] not in requested_models:
            continue
        if requested_tags and not requested_tags.intersection(row["retrieval_tags"]):
            continue
        outcome_cutoff = _iso_datetime(
            row["outcome_cutoff"], "outcome_cutoff", row["record_id"]
        )
        if research_cutoff is not None and not outcome_cutoff < research_cutoff:
            continue
        selected.append(row)
    return sorted(selected, key=lambda row: (row["setup_trade_date"], row["record_id"]))


def _short(text: str, limit: int) -> str:
    rendered = " ".join(text.split())
    if len(rendered) <= limit:
        return rendered
    for punctuation in ("。", "；", "，"):
        position = rendered.rfind(punctuation, 0, limit)
        if position >= max(20, limit // 2):
            return rendered[: position + 1]
    return rendered[:limit]


def _retrieval_text(row: dict[str, Any], manifest: dict[str, Any]) -> str:
    axes = row["condition_axes"]
    height = axes["height_environment"]
    market = row["market_structure"]
    decision = row["decision"]
    market_max = height["market_max_boards"]
    core_height = height["meaningful_core_boards"]
    defense_level = decision["defense_level_boards"]
    parts = [
        "条件标签：" + "、".join(row["retrieval_tags"]),
        (
            f"节点日：{'是' if market['is_node_day'] else '否'}；"
            f"攻守：{decision['model']}；市场最高：{market_max}；"
            f"核心高度：{core_height}；防守层：{defense_level}"
        ),
        "冻结路径：" + _short(decision["frozen_plan"], 88),
        "发酵：" + _short(axes["fermentation"]["summary"], 58),
        "加速：" + _short(axes["acceleration"]["summary"], 58),
        "板型：" + _short(axes["board_shape"]["summary"], 58),
        "高度：" + _short(axes["height_environment"]["summary"], 58),
    ]
    text = "\n".join(parts)
    return _short(text, manifest["retrieval_text_max_chars"])


def _full_text(row: dict[str, Any]) -> str:
    axes = row["condition_axes"]
    outcome = row["outcome"]
    sections = [
        row["title"],
        f"案例问题：{row['case_question']}",
        f"条件标签：{'、'.join(row['retrieval_tags'])}",
        f"发酵情况：{axes['fermentation']['summary']}",
        f"加速情况：{axes['acceleration']['summary']}",
        f"板型情况：{axes['board_shape']['summary']}",
        f"高度环境：{axes['height_environment']['summary']}",
        f"核心与节点：{row['market_structure']['broken_core_summary']}",
        f"收盘结构：{row['market_structure']['closing_structure_summary']}",
        f"冻结计划：{row['decision']['frozen_plan']}",
        f"验证日结果：{outcome['replay_summary']}",
        f"交易判卷：{outcome['trade_result']}",
    ]
    if outcome["follow_up_summary"]:
        sections.append(f"后续反馈：{outcome['follow_up_summary']}")
    if row["similarity"]["difference_boundaries"]:
        sections.append(
            "差异边界：" + "；".join(row["similarity"]["difference_boundaries"])
        )
    return "\n".join(sections)


def _chunk(row: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    height = row["condition_axes"]["height_environment"]
    return {
        "id": row["record_id"],
        "retrieval_text": _retrieval_text(row, manifest),
        "text": _full_text(row),
        "metadata": {
            "case_id": row["case_id"],
            "revision": row["revision"],
            "case_status": row["case_status"],
            "retrieval_status": row["retrieval_status"],
            "setup_trade_date": row["setup_trade_date"],
            "decision_cutoff": row["decision_cutoff"],
            "replay_trade_date": row["replay_trade_date"],
            "outcome_cutoff": row["outcome_cutoff"],
            "decision_record_mode": row["decision_record_mode"],
            "historical_replay_scope": row["historical_replay_scope"],
            "model": row["decision"]["model"],
            "market_max_boards": height["market_max_boards"],
            "meaningful_core_boards": height["meaningful_core_boards"],
            "regulatory_height_present": height["regulatory_height_present"],
            "retrieval_tags": row["retrieval_tags"],
            "result_tags": row["outcome"]["result_tags"],
            "trade_result": row["outcome"]["trade_result"],
            "source": row["source"],
            "supersedes": row["supersedes"],
        },
    }


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    rendered = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(rendered) + ("\n" if rendered else ""),
        encoding="utf-8",
        newline="\n",
    )
    return len(rendered)


def _add_filters(parser: argparse.ArgumentParser, manifest: dict[str, Any]) -> None:
    parser.add_argument(
        "--status",
        action="append",
        choices=manifest["allowed_retrieval_statuses"],
        default=[],
    )
    parser.add_argument(
        "--model",
        action="append",
        choices=manifest["allowed_models"],
        default=[],
    )
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument(
        "--research-cutoff",
        help="仅返回 outcome_cutoff 严格早于该 ISO 时间的案例",
    )


def _parser(manifest: dict[str, Any]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")

    listing = subparsers.add_parser("list")
    _add_filters(listing, manifest)

    export = subparsers.add_parser("export-chunks")
    _add_filters(export, manifest)
    export.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    manifest = _manifest()
    args = _parser(manifest).parse_args(argv)
    records = _records(manifest)
    validation = validate(records, manifest)
    if args.command == "validate":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 0

    selected = _selected(
        records,
        manifest,
        args.status,
        args.model,
        args.tag,
        _parse_research_cutoff(args.research_cutoff),
    )
    chunks = [_chunk(row, manifest) for row in selected]
    if args.command == "list":
        print(
            json.dumps(
                {
                    "record_count": len(chunks),
                    "records": [
                        {
                            "record_id": chunk["id"],
                            "title": row["title"],
                            "model": row["decision"]["model"],
                            "setup_trade_date": row["setup_trade_date"],
                            "outcome_cutoff": row["outcome_cutoff"],
                            "retrieval_tags": row["retrieval_tags"],
                        }
                        for row, chunk in zip(selected, chunks)
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    count = _write_jsonl(output, chunks)
    print(
        json.dumps(
            {
                "record_count": count,
                "output": str(output),
                "retrieval_text_max_chars": manifest["retrieval_text_max_chars"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
