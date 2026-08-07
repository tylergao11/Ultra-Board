# -*- coding: utf-8 -*-
"""审计 Ultra-Board 各数据层的日期覆盖，不生成交易结论。"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KPL_DIR = ROOT / "data" / "kaipanla" / "raw"
THS_LIMIT_DIR = ROOT / "data" / "ths" / "limit_pool"
THS_STORY_DIR = ROOT / "data" / "ths" / "stories"
KNOWLEDGE_FILE = ROOT / "data" / "knowledge" / "summaries.jsonl"
BLIND_DECISIONS_FILE = ROOT / "data" / "training" / "decisions.jsonl"
AUCTION_FILE = ROOT / "data" / "research" / "auction" / "observations.jsonl"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KPL_REQUIRED = (
    "zt_pool.json",
    "sector_ladder.json",
    "sentiment.json",
    "expression.json",
)


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _date_names(directory: Path, *, directories: bool) -> set[str]:
    if not directory.exists():
        return set()
    paths = directory.iterdir()
    result = set()
    for path in paths:
        if directories != path.is_dir():
            continue
        candidate = path.name if directories else path.stem
        if DAY_RE.fullmatch(candidate):
            result.add(candidate)
    return result


def _jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(
        bool(line.strip())
        for line in path.read_text(encoding="utf-8-sig").splitlines()
    )


def _knowledge_status_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    counts: Counter[str] = Counter()
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"知识 JSONL 解析失败: {path}:{line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"知识 JSONL 行必须是对象: {path}:{line_number}")
        counts[str(row.get("status") or "missing_status")] += 1
    return dict(sorted(counts.items()))


def _compact_days(days: list[str], sample_size: int) -> dict[str, Any]:
    if len(days) <= sample_size * 2:
        sample = days
    else:
        sample = days[:sample_size] + days[-sample_size:]
    return {
        "count": len(days),
        "first": days[0] if days else None,
        "last": days[-1] if days else None,
        "sample": sample,
        "sample_truncated": len(sample) < len(days),
    }


def build_audit(
    start_value: str | None,
    end_value: str | None,
    details: bool,
    sample_size: int,
) -> dict[str, Any]:
    start = _day(start_value) if start_value else None
    end = _day(end_value) if end_value else None
    if start and end and start > end:
        raise ValueError("--start 不能晚于 --end")

    kpl_dates = _date_names(KPL_DIR, directories=True)
    limit_dates = _date_names(THS_LIMIT_DIR, directories=False)
    story_dates = _date_names(THS_STORY_DIR, directories=False)
    all_dates = sorted(kpl_dates | limit_dates | story_dates)
    selected = [
        day
        for day in all_dates
        if (start is None or day >= start) and (end is None or day <= end)
    ]

    rows = []
    for day in selected:
        kpl_missing = [
            name for name in KPL_REQUIRED if not (KPL_DIR / day / name).exists()
        ]
        kpl_ready = day in kpl_dates and not kpl_missing
        limit_ready = day in limit_dates
        story_ready = day in story_dates
        rows.append(
            {
                "date": day,
                "kpl_ready": kpl_ready,
                "kpl_missing_files": kpl_missing,
                "ths_limit_pool_ready": limit_ready,
                "ths_story_ready": story_ready,
                "fact_view_ready": kpl_ready and limit_ready,
                "story_context_ready": kpl_ready and limit_ready and story_ready,
            }
        )

    missing = {
        "kpl": [row["date"] for row in rows if not row["kpl_ready"]],
        "ths_limit_pool": [
            row["date"] for row in rows if not row["ths_limit_pool_ready"]
        ],
        "ths_story": [row["date"] for row in rows if not row["ths_story_ready"]],
    }
    missing_view = {
        name: days if details else _compact_days(days, sample_size)
        for name, days in missing.items()
    }
    return {
        "view": "data_foundation_audit",
        "information_boundary": "coverage_only_no_trading_judgement",
        "range": {
            "start": start,
            "end": end,
            "available_first": selected[0] if selected else None,
            "available_last": selected[-1] if selected else None,
            "trading_day_count": len(selected),
        },
        "coverage": {
            "kpl_ready": sum(row["kpl_ready"] for row in rows),
            "ths_limit_pool_ready": sum(
                row["ths_limit_pool_ready"] for row in rows
            ),
            "ths_story_ready": sum(row["ths_story_ready"] for row in rows),
            "fact_view_ready": sum(row["fact_view_ready"] for row in rows),
            "story_context_ready": sum(
                row["story_context_ready"] for row in rows
            ),
        },
        "missing": missing_view,
        "research_memory": {
            "knowledge_status_counts": _knowledge_status_counts(KNOWLEDGE_FILE),
            "blind_decision_count": _jsonl_count(BLIND_DECISIONS_FILE),
            "auction_snapshot_count": _jsonl_count(AUCTION_FILE),
        },
        "interpretation": {
            "fact_view_ready": "开盘啦分类合同与同花顺涨停池同时存在。",
            "story_context_ready": "事实视图之外，同花顺标题后半句故事也已经人工录入。",
            "missing_story": "缺失表示尚未录入，不代表当天没有市场故事。",
        },
        **({"days": rows} if details else {}),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--sample-size", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.sample_size < 1:
        raise ValueError("--sample-size 必须大于等于 1")
    payload = build_audit(args.start, args.end, args.details, args.sample_size)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
