# -*- coding: utf-8 -*-
"""验证并导出盲测决策与后验纠错记录。"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "training" / "manifest.json"
REQUIRED_FIELDS = {
    "schema_version",
    "record_id",
    "sequence",
    "record_type",
    "recorded_at",
    "case_date",
    "information_cutoff",
    "hindsight_boundary",
    "source",
    "user_signal",
    "public_reasoning_summary",
    "decision",
    "outcome",
    "correction",
    "accepted_learning",
    "supersedes",
    "tags",
}
RECORD_TYPES = {
    "principle",
    "pre_outcome_selection",
    "outcome_reveal",
    "correction",
    "workflow_hypothesis",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def _manifest() -> dict[str, Any]:
    payload = _read_json(MANIFEST_PATH)
    if payload.get("schema_version") != 1:
        raise ValueError("训练记录 manifest 版本不受支持")
    return payload


def _journal_path(scope: str, allow_post_outcome: bool) -> Path:
    manifest = _manifest()
    if scope == "blind":
        relative = manifest["blind_safe_journal"]
    elif scope == "post-outcome":
        if not allow_post_outcome:
            raise PermissionError(
                "读取后验训练记录必须显式提供 --allow-post-outcome；盲测分析禁止调用。"
            )
        relative = manifest["post_outcome_journal"]
    else:
        raise ValueError(f"未知 scope: {scope}")
    return ROOT / relative


def _records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    result = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 解析失败: {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"JSONL 行必须是对象: {path}:{line_number}")
        record["_line_number"] = line_number
        result.append(record)
    return result


def _optional_day(value: Any, field: str, record_id: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{record_id} {field} 必须是日期字符串或 null")
    return date.fromisoformat(value).isoformat()


def validate_records(
    records: list[dict[str, Any]],
    scope: str,
) -> dict[str, Any]:
    seen_ids: set[str] = set()
    seen_sequences: set[int] = set()
    previous_sequence = -1
    for record in records:
        line_number = record.pop("_line_number")
        missing = REQUIRED_FIELDS.difference(record)
        if missing:
            raise ValueError(
                f"第 {line_number} 行缺少字段: {', '.join(sorted(missing))}"
            )
        if record["schema_version"] != 1:
            raise ValueError(f"{record['record_id']} schema_version 不受支持")
        record_id = record["record_id"]
        if not isinstance(record_id, str) or not record_id or record_id in seen_ids:
            raise ValueError(f"record_id 非法或重复: {record_id!r}")
        seen_ids.add(record_id)
        sequence = record["sequence"]
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence in seen_sequences
            or sequence <= previous_sequence
        ):
            raise ValueError(f"{record_id} sequence 必须严格递增且唯一")
        seen_sequences.add(sequence)
        previous_sequence = sequence
        if record["record_type"] not in RECORD_TYPES:
            raise ValueError(f"{record_id} record_type 非法")
        expected_boundary = (
            "blind_safe" if scope == "blind" else "post_outcome_training_only"
        )
        if record["hindsight_boundary"] != expected_boundary:
            raise ValueError(
                f"{record_id} hindsight_boundary 应为 {expected_boundary}"
            )
        _optional_day(record["recorded_at"], "recorded_at", record_id)
        _optional_day(record["case_date"], "case_date", record_id)
        _optional_day(
            record["information_cutoff"], "information_cutoff", record_id
        )
        if not isinstance(record["user_signal"], str):
            raise ValueError(f"{record_id} user_signal 必须是字符串")
        if not isinstance(record["public_reasoning_summary"], str):
            raise ValueError(f"{record_id} public_reasoning_summary 必须是字符串")
        if not isinstance(record["accepted_learning"], str):
            raise ValueError(f"{record_id} accepted_learning 必须是字符串")
        if not isinstance(record["supersedes"], list):
            raise ValueError(f"{record_id} supersedes 必须是数组")
        if not isinstance(record["tags"], list):
            raise ValueError(f"{record_id} tags 必须是数组")
    unresolved = sorted(
        {
            superseded
            for record in records
            for superseded in record["supersedes"]
            if superseded not in seen_ids
        }
    )
    return {
        "scope": scope,
        "record_count": len(records),
        "record_ids": sorted(seen_ids),
        "unresolved_supersedes": unresolved,
        "valid": True,
    }


def _message_record(record: dict[str, Any]) -> dict[str, Any] | None:
    user_signal = record["user_signal"].strip()
    reasoning = record["public_reasoning_summary"].strip()
    learning = record["accepted_learning"].strip()
    if not user_signal or not reasoning:
        return None
    response = reasoning
    if learning and learning not in response:
        response = f"{response}\n\n最终保留：{learning}"
    return {
        "messages": [
            {"role": "user", "content": user_signal},
            {"role": "assistant", "content": response},
        ],
        "metadata": {
            "record_id": record["record_id"],
            "sequence": record["sequence"],
            "record_type": record["record_type"],
            "case_date": record["case_date"],
            "information_cutoff": record["information_cutoff"],
            "hindsight_boundary": record["hindsight_boundary"],
            "tags": record["tags"],
        },
    }


def _write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> int:
    rows = [json.dumps(record, ensure_ascii=False) for record in records]
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(rows)
    if rows:
        text += "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return len(rows)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="验证或导出可审计的决策、纠错与蒸馏记录。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "export-sft"):
        child = subparsers.add_parser(command)
        child.add_argument(
            "--scope", choices=("blind", "post-outcome"), default="blind"
        )
        child.add_argument("--allow-post-outcome", action="store_true")
        if command == "export-sft":
            child.add_argument("--output", required=True, help="UTF-8 JSONL 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    path = _journal_path(args.scope, args.allow_post_outcome)
    records = _records(path)
    validation = validate_records(records, args.scope)
    if args.command == "validate":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 0
    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    count = _write_jsonl(
        output,
        (message for record in records if (message := _message_record(record))),
    )
    print(
        json.dumps(
            {"scope": args.scope, "output": str(output), "record_count": count},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
