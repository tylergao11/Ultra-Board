# -*- coding: utf-8 -*-
"""将 Ultra-Board 事实按日规范化导出给 Agent API 站点。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.day_facts import available_days, build_day_component  # noqa: E402


CN_TZ = timezone(timedelta(hours=8))
DEFAULT_OUTPUT = ROOT / "site" / "public" / "agent-data" / "v1"
SCHEMA_VERSION = 1
API_VERSION = "v1"
SOURCE_CONTRACT = {
    "stock_attributes": "kaipanla theme + themes only",
    "market_and_limit_facts": "tonghuashun limit_pool only",
    "stories": "tonghuashun story schema v1/v2; stock detail required",
    "judgement_boundary": "facts_only",
}


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=False,
        )
        + "\n"
    ).encode("utf-8")
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)
    return body


def _update_digest(
    digest: Any, relative_path: str, body: bytes
) -> None:
    """用路径和边界符为组件内容分帧，避免裸字节串拼接歧义。"""
    digest.update(relative_path.encode("utf-8"))
    digest.update(b"\0")
    digest.update(body)
    digest.update(b"\0")


def _selected_range(
    days: list[str], start: str | None, end: str | None
) -> list[str]:
    if not days:
        raise ValueError("没有可导出的本地数据日")
    if (start is None) != (end is None):
        raise ValueError("--start 与 --end 必须同时提供")
    if start is None:
        requested = list(days)
    else:
        if start > end:
            raise ValueError("--start 不能晚于 --end")
        requested = [day for day in days if start <= day <= end]
        if not requested:
            raise ValueError(f"指定区间没有本地数据日: {start}..{end}")

    return requested


def _require_coverage(
    day_output: dict[str, Any],
) -> None:
    coverage = day_output["coverage"]
    if not coverage.get("kpl_ready"):
        raise ValueError(f"{day_output['date']} 开盘啦数据不完整，禁止导出")
    if not coverage.get("ths_limit_pool_ready"):
        raise ValueError(f"{day_output['date']} 同花顺涨停池不完整，禁止导出")
    if not coverage.get("ths_story_ready"):
        raise ValueError(f"{day_output['date']} 同花顺故事不完整，禁止导出")
    if not coverage.get("stock_story_complete"):
        raise ValueError(f"{day_output['date']} 个股故事覆盖不完整，禁止导出")


def _export_components_to_directory(
    *,
    output_dir: Path,
    start: str | None,
    end: str | None,
    ready_only: bool,
) -> dict[str, Any]:
    source_days = available_days()
    candidate_days = _selected_range(source_days, start, end)
    component_days: list[str] = []
    skipped_day_count = 0
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            {
                "schema_version": SCHEMA_VERSION,
                "api_version": API_VERSION,
                "source_contract": SOURCE_CONTRACT,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    digest.update(b"\0")
    exported_day_count = 0
    for day in candidate_days:
        day_output = build_day_component(day)
        try:
            _require_coverage(day_output)
        except ValueError:
            if not ready_only:
                raise
            skipped_day_count += 1
            continue

        day_component = {
            "schema_version": SCHEMA_VERSION,
            "api_version": API_VERSION,
            "component_type": "day",
            "date": day,
            "day": day_output,
        }
        day_path = f"days/{day}.json"
        day_body = _write_json_atomic(
            output_dir / day_path,
            day_component,
        )
        _update_digest(digest, day_path, day_body)
        exported_day_count += 1
        component_days.append(day)

    if not component_days:
        raise ValueError("所选范围没有满足发布条件的交易日")

    generated_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
    revision = f"sha256:{digest.hexdigest()}"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "api_version": API_VERSION,
        "component_type": "manifest",
        "status": "ready",
        "publication_ready": True,
        "export_mode": "release",
        "generated_at": generated_at,
        "data_revision": revision,
        "available_dates": component_days,
        "range": {
            "start": component_days[0],
            "end": component_days[-1],
        },
        "counts": {
            "candidate_dates": len(candidate_days),
            "day_components": exported_day_count,
            "available_dates": len(component_days),
            "skipped_dates": skipped_day_count,
        },
        "source_contract": SOURCE_CONTRACT,
    }
    _write_json_atomic(output_dir / "manifest.json", manifest)
    return manifest


def export_components(
    *,
    output_dir: Path,
    start: str | None,
    end: str | None,
    ready_only: bool,
) -> dict[str, Any]:
    """先在同级临时目录完成全部校验和写入，再原子替换公开目录。"""
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.tmp")
    backup = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.backup")
    for path in (staging, backup):
        if path.exists():
            shutil.rmtree(path)
    try:
        manifest = _export_components_to_directory(
            output_dir=staging,
            start=start,
            end=end,
            ready_only=ready_only,
        )
        if output_dir.exists():
            os.replace(output_dir, backup)
        try:
            os.replace(staging, output_dir)
        except Exception:
            if backup.exists() and not output_dir.exists():
                os.replace(backup, output_dir)
            raise
        if backup.exists():
            shutil.rmtree(backup)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if backup.exists() and output_dir.exists():
            shutil.rmtree(backup)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", help="首个公开截止日 YYYY-MM-DD")
    parser.add_argument("--end", help="最后公开截止日 YYYY-MM-DD")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--ready-only",
        action="store_true",
        help="只发布完整交易日；不完整日期整体跳过",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    manifest = export_components(
        output_dir=args.output_dir.resolve(),
        start=args.start,
        end=args.end,
        ready_only=args.ready_only,
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "range": manifest["range"],
                "counts": manifest["counts"],
                "data_revision": manifest["data_revision"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
