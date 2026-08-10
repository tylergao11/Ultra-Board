# -*- coding: utf-8 -*-
"""验证、筛选并导出逐条确认的知识总结。"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "knowledge" / "manifest.json"
REQUIRED_FIELDS = {
    "schema_version",
    "knowledge_id",
    "revision",
    "status",
    "kind",
    "scope",
    "summary",
    "conditions",
    "signals",
    "anti_signals",
    "evidence_refs",
    "supersedes",
    "tags",
    "source",
    "recorded_at",
    "temporal_scope",
}
STATUSES = {"accepted", "hypothesis", "superseded"}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象: {path}")
    return payload


def _manifest() -> dict[str, Any]:
    payload = _read_json(MANIFEST_PATH)
    if payload.get("schema_version") != 2:
        raise ValueError("知识库 manifest 版本不受支持")
    return payload


def _summary_path() -> Path:
    return ROOT / _manifest()["summary_source"]


def _records() -> list[dict[str, Any]]:
    path = _summary_path()
    result: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 解析失败: {path}:{line_number}: {exc}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"JSONL 行必须是对象: {path}:{line_number}")
        row["_line_number"] = line_number
        result.append(row)
    return result


def _string_list(value: Any, field: str, knowledge_id: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{knowledge_id} {field} 必须是非空字符串数组")
    return value


def _timestamp(
    value: Any,
    field: str,
    knowledge_id: str,
    *,
    allow_none: bool = False,
) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{knowledge_id} {field} 必须是 ISO 时间或 null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{knowledge_id} {field} 不是 ISO 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{knowledge_id} {field} 必须包含时区")
    return parsed


def validate(records: list[dict[str, Any]]) -> dict[str, Any]:
    ids: set[str] = set()
    revisions: set[int] = set()
    previous_revision = 0
    for row in records:
        line_number = row.pop("_line_number")
        missing = REQUIRED_FIELDS.difference(row)
        if missing:
            raise ValueError(
                f"第 {line_number} 行缺少字段: {', '.join(sorted(missing))}"
            )
        if row["schema_version"] != 2:
            raise ValueError(f"第 {line_number} 行 schema_version 不受支持")
        knowledge_id = row["knowledge_id"]
        if (
            not isinstance(knowledge_id, str)
            or not knowledge_id.strip()
            or knowledge_id in ids
        ):
            raise ValueError(f"knowledge_id 非法或重复: {knowledge_id!r}")
        ids.add(knowledge_id)
        revision = row["revision"]
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision <= previous_revision
            or revision in revisions
        ):
            raise ValueError(f"{knowledge_id} revision 必须严格递增且唯一")
        revisions.add(revision)
        previous_revision = revision
        if row["status"] not in STATUSES:
            raise ValueError(f"{knowledge_id} status 非法")
        for field in ("kind", "scope", "summary", "source"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ValueError(f"{knowledge_id} {field} 必须是非空字符串")
        for field in (
            "conditions",
            "signals",
            "anti_signals",
            "evidence_refs",
            "supersedes",
            "tags",
        ):
            _string_list(row[field], field, knowledge_id)
        temporal_scope = row["temporal_scope"]
        if temporal_scope not in _manifest()["allowed_temporal_scopes"]:
            raise ValueError(f"{knowledge_id} temporal_scope 非法")
        recorded_at = _timestamp(
            row["recorded_at"], "recorded_at", knowledge_id, allow_none=True
        )
        if temporal_scope == "contemporaneous_evidence" and recorded_at is None:
            raise ValueError(
                f"{knowledge_id} contemporaneous_evidence 必须记录 recorded_at"
            )
    by_id = {row["knowledge_id"]: row for row in records}
    unresolved = sorted(
        {
            old_id
            for row in records
            for old_id in row["supersedes"]
            if old_id not in ids
        }
    )
    if unresolved:
        raise ValueError(f"supersedes 指向不存在的知识: {', '.join(unresolved)}")
    superseded_ids = {
        old_id for row in records for old_id in row["supersedes"]
    }
    for old_id in superseded_ids:
        old = by_id[old_id]
        if old["status"] != "superseded":
            raise ValueError(f"{old_id} 已被新总结替代，status 必须改为 superseded")
        replacements = [row for row in records if old_id in row["supersedes"]]
        if any(row["revision"] <= old["revision"] for row in replacements):
            raise ValueError(f"{old_id} 的替代总结 revision 必须更高")
    unreferenced_superseded = sorted(
        row["knowledge_id"]
        for row in records
        if row["status"] == "superseded"
        and row["knowledge_id"] not in superseded_ids
    )
    if unreferenced_superseded:
        raise ValueError(
            "superseded 总结没有被新记录引用: "
            + ", ".join(unreferenced_superseded)
        )
    return {
        "source": str(_summary_path()),
        "knowledge_revision": max(revisions, default=0),
        "record_count": len(records),
        "status_counts": {
            status: sum(row["status"] == status for row in records)
            for status in sorted(STATUSES)
        },
        "valid": True,
    }


def _chunk(row: dict[str, Any]) -> dict[str, Any]:
    sections = [row["summary"]]
    for label, field in (
        ("适用条件", "conditions"),
        ("观察信号", "signals"),
        ("误用边界", "anti_signals"),
    ):
        if row[field]:
            sections.append(f"{label}：{'；'.join(row[field])}")
    return {
        "id": row["knowledge_id"],
        "text": "\n".join(sections),
        "metadata": {
            "revision": row["revision"],
            "status": row["status"],
            "kind": row["kind"],
            "scope": row["scope"],
            "tags": row["tags"],
            "evidence_refs": row["evidence_refs"],
            "supersedes": row["supersedes"],
            "source": row["source"],
            "recorded_at": row["recorded_at"],
            "temporal_scope": row["temporal_scope"],
        },
    }


def _selected(
    records: list[dict[str, Any]],
    statuses: list[str],
    tags: list[str],
    available_at: datetime | None,
) -> list[dict[str, Any]]:
    requested_statuses = set(statuses or _manifest()["default_retrieval_status"])
    requested_tags = {tag.strip() for tag in tags if tag.strip()}
    selected = []
    for row in records:
        if row["status"] not in requested_statuses:
            continue
        if requested_tags and not requested_tags.intersection(row["tags"]):
            continue
        if available_at is not None:
            if row["temporal_scope"] != "contemporaneous_evidence":
                continue
            recorded_at = _timestamp(
                row["recorded_at"], "recorded_at", row["knowledge_id"]
            )
            assert recorded_at is not None
            if recorded_at > available_at:
                continue
        selected.append(row)
    return selected


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    rendered = [json.dumps(row, ensure_ascii=False) for row in rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(rendered) + ("\n" if rendered else ""),
        encoding="utf-8",
        newline="\n",
    )
    return len(rendered)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    for command in ("list", "export-chunks"):
        child = subparsers.add_parser(command)
        child.add_argument("--status", action="append", choices=sorted(STATUSES), default=[])
        child.add_argument("--tag", action="append", default=[])
        child.add_argument(
            "--available-at",
            help="严格同时态检索；只返回该 ISO 时间以前已有形成证据的总结",
        )
        if command == "export-chunks":
            child.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    records = _records()
    validation = validate(records)
    if args.command == "validate":
        print(json.dumps(validation, ensure_ascii=False, indent=2))
        return 0
    available_at = None
    if args.available_at:
        available_at = _timestamp(args.available_at, "available_at", "query")
    selected = _selected(records, args.status, args.tag, available_at)
    chunks = [_chunk(row) for row in selected]
    if args.command == "list":
        print(
            json.dumps(
                {
                    "knowledge_revision": validation["knowledge_revision"],
                    "record_count": len(chunks),
                    "chunks": chunks,
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
                "knowledge_revision": validation["knowledge_revision"],
                "record_count": count,
                "output": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
