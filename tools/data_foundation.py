# -*- coding: utf-8 -*-
"""审计 Ultra-Board 各数据层的日期覆盖，不生成交易结论。"""

from __future__ import annotations

import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
KPL_DIR = ROOT / "data" / "kaipanla" / "raw"
KPL_NON_TRADING_PATH = ROOT / "data" / "kaipanla" / "non_trading_days.json"
AUCTION_FILE = ROOT / "data" / "research" / "auction" / "observations.jsonl"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KPL_REQUIRED = (
    "_DONE",
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


def _weekdays(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    final = date.fromisoformat(end)
    result = []
    while current <= final:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current = date.fromordinal(current.toordinal() + 1)
    return result


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
    all_dates = sorted(kpl_dates)
    if start and end:
        selected = _weekdays(start, end)
    else:
        selected = [
            day
            for day in all_dates
            if (start is None or day >= start) and (end is None or day <= end)
        ]
    non_trading = set()
    if KPL_NON_TRADING_PATH.exists():
        payload = json.loads(KPL_NON_TRADING_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError("non_trading_days.json 顶层必须是数组")
        non_trading = {str(item) for item in payload}

    rows = []
    for day in selected:
        kpl_missing = [
            name for name in KPL_REQUIRED if not (KPL_DIR / day / name).exists()
        ]
        kpl_mismatch = (KPL_DIR / day / "_MISMATCH").exists()
        kpl_ready = day in kpl_dates and not kpl_missing and not kpl_mismatch
        known_non_trading = day in non_trading
        rows.append(
            {
                "date": day,
                "known_non_trading": known_non_trading,
                "kpl_ready": kpl_ready,
                "kpl_missing_files": kpl_missing,
                "kpl_mismatch": kpl_mismatch,
                "fact_view_ready": kpl_ready,
            }
        )

    missing = {
        "kpl": [
            row["date"]
            for row in rows
            if not row["kpl_ready"] and not row["known_non_trading"]
        ],
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
            "weekday_count": len(selected),
            "known_non_trading_count": sum(
                row["known_non_trading"] for row in rows
            ),
            "expected_trading_day_count": sum(
                not row["known_non_trading"] for row in rows
            ),
        },
        "coverage": {
            "kpl_ready": sum(row["kpl_ready"] for row in rows),
            "fact_view_ready": sum(row["fact_view_ready"] for row in rows),
            "unresolved_weekdays": len(missing["kpl"]),
        },
        "missing": missing_view,
        "recorded_observations": {
            "auction_snapshot_count": _jsonl_count(AUCTION_FILE),
        },
        "interpretation": {
            "fact_view_ready": "开盘啦当日目录通过完整性合同，可直接生成日事实视图。",
            "known_non_trading": "开盘啦明确返回未入库的工作日，不计作缺失交易日。",
            "source_contract": "正式数据链只读取开盘啦；同花顺旧文件不参与覆盖率。",
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
