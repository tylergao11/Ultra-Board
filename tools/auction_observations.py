# -*- coding: utf-8 -*-
"""验证并读取竞价封单快照，不推断强弱。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OBSERVATIONS = ROOT / "data" / "research" / "auction" / "observations.jsonl"
REQUIRED = {
    "schema_version",
    "observation_id",
    "date",
    "information_cutoff",
    "captured_at",
    "code",
    "name",
    "source",
    "source_mode",
    "hindsight_boundary",
    "indicative_price",
    "matched_amount",
    "unmatched_limit_order_amount",
    "note",
}
SOURCE_MODES = {"live_snapshot", "historical_verified"}


def _records() -> list[dict[str, Any]]:
    result = []
    for line_number, line in enumerate(
        OBSERVATIONS.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"竞价 JSONL 解析失败: 第 {line_number} 行") from exc
        if not isinstance(row, dict):
            raise ValueError(f"竞价 JSONL 第 {line_number} 行不是对象")
        row["_line_number"] = line_number
        result.append(row)
    return result


def _optional_number(value: Any, field: str, observation_id: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{observation_id} {field} 必须是非负数字或 null")


def validate(records: list[dict[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    last_timestamp: dict[tuple[str, str], datetime] = {}
    for row in records:
        line_number = row.pop("_line_number")
        missing = REQUIRED.difference(row)
        if missing:
            raise ValueError(
                f"竞价 JSONL 第 {line_number} 行缺少: {', '.join(sorted(missing))}"
            )
        observation_id = row["observation_id"]
        if (
            not isinstance(observation_id, str)
            or not observation_id
            or observation_id in seen
        ):
            raise ValueError(f"observation_id 非法或重复: {observation_id!r}")
        seen.add(observation_id)
        if row["schema_version"] != 1:
            raise ValueError(f"{observation_id} schema_version 不受支持")
        day = date.fromisoformat(row["date"]).isoformat()
        cutoff = date.fromisoformat(row["information_cutoff"]).isoformat()
        if day != cutoff:
            raise ValueError(f"{observation_id} 竞价快照 cutoff 必须等于交易日")
        code = str(row["code"])
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"{observation_id} 股票代码必须是六位数字")
        timestamp = datetime.fromisoformat(row["captured_at"])
        if timestamp.tzinfo is None:
            raise ValueError(f"{observation_id} captured_at 必须带时区")
        if timestamp.date().isoformat() != day:
            raise ValueError(f"{observation_id} captured_at 日期不一致")
        key = (day, code)
        previous = last_timestamp.get(key)
        if previous is not None and timestamp <= previous:
            raise ValueError(f"{observation_id} 同股快照时间必须严格递增")
        last_timestamp[key] = timestamp
        if row["source_mode"] not in SOURCE_MODES:
            raise ValueError(f"{observation_id} source_mode 非法")
        if row["hindsight_boundary"] != "blind_safe":
            raise ValueError(f"{observation_id} 竞价安全层禁止后验记录")
        _optional_number(row["indicative_price"], "indicative_price", observation_id)
        _optional_number(row["matched_amount"], "matched_amount", observation_id)
        _optional_number(
            row["unmatched_limit_order_amount"],
            "unmatched_limit_order_amount",
            observation_id,
        )
    return {
        "information_boundary": "blind_safe",
        "record_count": len(records),
        "valid": True,
        "historical_gap": (
            "record_count=0 时表示没有可靠历史竞价快照，不允许从收盘结果反推。"
        ),
    }


def _series(
    records: list[dict[str, Any]], day_value: str, code_value: str
) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    code = str(code_value).zfill(6)
    selected = [
        row for row in records if row["date"] == day and row["code"] == code
    ]
    changes = []
    for previous, current in zip(selected, selected[1:]):
        changes.append(
            {
                "from": previous["captured_at"],
                "to": current["captured_at"],
                "indicative_price_change": _difference(
                    previous["indicative_price"], current["indicative_price"]
                ),
                "matched_amount_change": _difference(
                    previous["matched_amount"], current["matched_amount"]
                ),
                "unmatched_limit_order_amount_change": _difference(
                    previous["unmatched_limit_order_amount"],
                    current["unmatched_limit_order_amount"],
                ),
            }
        )
    return {
        "view": "auction_series",
        "information_cutoff": day,
        "code": code,
        "snapshots": selected,
        "changes": changes,
        "judgement_boundary": "只计算快照变化，不自动输出减单、转强或买点结论。",
    }


def _difference(previous: Any, current: Any) -> float | None:
    if previous is None or current is None:
        return None
    return current - previous


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="验证或读取竞价封单快照。")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    series = subparsers.add_parser("series")
    series.add_argument("day")
    series.add_argument("code")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    records = _records()
    validation = validate(records)
    payload = (
        validation
        if args.command == "validate"
        else _series(records, args.day, args.code)
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
