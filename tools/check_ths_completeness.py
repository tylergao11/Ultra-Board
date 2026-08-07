#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查同花顺逐日真相与涨停池在指定区间内是否齐全。

用法：

    python tools/check_ths_completeness.py 2025-10-01 2026-08-06

默认通过同花顺涨停池确认两套目录共同缺少的工作日是否确属休市；
传入 ``--offline`` 时只检查本地文件和正式数据合同。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.limits import Board, classify  # noqa: E402
from ultraboard.ths.ladder_selector import list_nodes  # noqa: E402
from ultraboard.ths.limit_pool import _fetch_raw_day  # noqa: E402


STRONG_WIND_DIR = ROOT / "data" / "ths" / "strong_wind"
LIMIT_POOL_DIR = ROOT / "data" / "ths" / "limit_pool"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day_files(folder: Path, start: str, end: str) -> dict[str, Path]:
    return {
        path.stem: path
        for path in folder.glob("*.json")
        if DAY_RE.fullmatch(path.stem) and start <= path.stem <= end
    }


def _load_object(path: Path) -> dict[str, Any]:
    body = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(body, dict):
        raise ValueError(f"JSON 顶层不是对象: {path}")
    return body


def _poster_stocks(body: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for group in body.get("groups") or []:
        for stock in group.get("stocks") or []:
            code = str(stock.get("code") or "").strip().zfill(6)
            result[code] = str(stock.get("name") or "").strip()
    return result


def _pool_stocks(body: dict[str, Any]) -> dict[str, str]:
    return {
        str(stock.get("code") or "").strip().zfill(6):
        str(stock.get("name") or "").strip()
        for stock in body.get("stocks") or []
    }


def _missing_weekdays(start: date, end: date, present: set[str]) -> list[str]:
    result: list[str] = []
    current = start
    while current <= end:
        if current.weekday() < 5 and current.isoformat() not in present:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def check(start: str, end: str, *, offline: bool) -> int:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    if start_date > end_date:
        raise ValueError("start 不能晚于 end")

    strong_files = _day_files(STRONG_WIND_DIR, start, end)
    pool_files = _day_files(LIMIT_POOL_DIR, start, end)
    strong_days = set(strong_files)
    pool_days = set(pool_files)
    common_days = sorted(strong_days & pool_days)
    errors: list[str] = []

    strong_without_pool = sorted(strong_days - pool_days)
    pool_without_strong = sorted(pool_days - strong_days)
    if strong_without_pool:
        errors.append(f"仅 strong_wind 存在的日期: {','.join(strong_without_pool)}")
    if pool_without_strong:
        errors.append(f"仅 limit_pool 存在的日期: {','.join(pool_without_strong)}")

    bse_rows_filtered = 0
    poster_only_non_bse_rows = 0
    pool_missing_from_poster: list[str] = []
    for day in common_days:
        poster = _poster_stocks(_load_object(strong_files[day]))
        pool = _pool_stocks(_load_object(pool_files[day]))
        poster_non_bse = {
            code: name
            for code, name in poster.items()
            if classify(code) is not Board.BSE
        }
        pool_non_bse = {
            code: name
            for code, name in pool.items()
            if classify(code) is not Board.BSE
        }
        bse_rows_filtered += len(poster) - len(poster_non_bse)
        poster_only_non_bse_rows += len(set(poster_non_bse) - set(pool_non_bse))
        pool_missing_from_poster.extend(
            f"{day}:{code}"
            for code in sorted(set(pool_non_bse) - set(poster_non_bse))
        )

    if pool_missing_from_poster:
        preview = ",".join(pool_missing_from_poster[:20])
        suffix = "..." if len(pool_missing_from_poster) > 20 else ""
        errors.append(
            f"涨停池股票缺少最强风口归属 {len(pool_missing_from_poster)} 条: "
            f"{preview}{suffix}"
        )

    contract_error: str | None = None
    contract_result: dict[str, Any] | None = None
    try:
        contract_result = list_nodes(start, end)
    except Exception as exc:  # 正式入口的异常就是完整性失败证据
        contract_error = str(exc)
        errors.append(f"正式入口合同校验失败: {contract_error}")

    present_days = strong_days | pool_days
    missing_weekdays = _missing_weekdays(start_date, end_date, present_days)
    trading_day_gaps: list[str] = []
    calendar_error: str | None = None
    if not offline:
        try:
            for day in missing_weekdays:
                _, total = _fetch_raw_day(day)
                if total:
                    trading_day_gaps.append(f"{day}({total})")
        except Exception as exc:
            calendar_error = str(exc)
            errors.append(f"同花顺休市核验失败: {calendar_error}")
        if trading_day_gaps:
            errors.append(
                "两套本地数据共同缺少的交易日: " + ",".join(trading_day_gaps)
            )

    print("# 同花顺数据完整性")
    print(f"range={start}..{end}")
    print(f"information_cutoff={end}")
    print(f"strong_wind_days={len(strong_days)}")
    print(f"limit_pool_days={len(pool_days)}")
    print(f"paired_days={len(common_days)}")
    print(f"bse_poster_rows_filtered={bse_rows_filtered}")
    print(f"poster_only_non_bse_rows={poster_only_non_bse_rows}")
    print(f"pool_missing_from_poster={len(pool_missing_from_poster)}")
    print(f"missing_weekdays={len(missing_weekdays)}")
    print(f"calendar_verified={str(not offline and calendar_error is None).lower()}")
    print(f"trading_day_gaps={len(trading_day_gaps)}")
    if contract_result is not None:
        print(f"contract_trade_days={contract_result['trade_day_count']}")
        print(f"contract_nodes={contract_result['node_count']}")
        print(f"boundary_warning={contract_result['boundary_warning'] or 'none'}")

    if errors:
        print("status=incomplete")
        for error in errors:
            print(f"error={error}")
        return 1
    if offline:
        print("status=local-complete-calendar-unverified")
        return 0
    print("status=complete")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="检查同花顺逐日数据区间完整性")
    parser.add_argument("start", help="开始日期 YYYY-MM-DD")
    parser.add_argument("end", help="结束日期 YYYY-MM-DD")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="不访问同花顺核验两套目录共同缺少的工作日",
    )
    args = parser.parse_args()
    return check(args.start, args.end, offline=args.offline)


if __name__ == "__main__":
    raise SystemExit(main())
