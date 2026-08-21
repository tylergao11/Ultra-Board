# -*- coding: utf-8 -*-
"""更新并校验开盘啦单源市场事实。

默认刷新最近一个月并选择开盘啦已经发布的最新完整交易日；显式
``--date`` 严格更新单日；``--start``/``--end`` 批量回灌闭区间。
所有模式都复用同一幂等回灌器，失败后重跑原命令即可续传。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from ultraboard.day_facts import build_day_component
from ultraboard.kaipanla import load_day as load_kaipanla_day
from ultraboard.kaipanla.backfill import main as kaipanla_backfill_main


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / ".daily_update.lock"
KPL_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
KPL_NON_TRADING_PATH = ROOT / "data" / "kaipanla" / "non_trading_days.json"
CN_TZ = timezone(timedelta(hours=8))


@contextmanager
def _update_lock() -> Iterator[None]:
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        owner = LOCK_PATH.read_text(encoding="utf-8-sig")
        raise RuntimeError(f"已有每日数据更新正在运行: {owner.strip()}") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
                },
                handle,
                ensure_ascii=False,
            )
            handle.write("\n")
        yield
    finally:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()


def _historical_complete(day: str) -> bool:
    directory = KPL_RAW_DIR / day
    return (
        directory.is_dir()
        and (directory / "_DONE").exists()
        and not (directory / "_MISMATCH").exists()
    )


def _complete_days(start: str, end: str) -> list[str]:
    if not KPL_RAW_DIR.exists():
        return []
    return sorted(
        path.name
        for path in KPL_RAW_DIR.iterdir()
        if path.is_dir()
        and start <= path.name <= end
        and _historical_complete(path.name)
    )


def _weekdays(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    final = date.fromisoformat(end)
    result = []
    while current <= final:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def _require_closed_range(start: str, end: str, complete_days: list[str]) -> None:
    non_trading = set()
    if KPL_NON_TRADING_PATH.exists():
        payload = json.loads(KPL_NON_TRADING_PATH.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise RuntimeError("开盘啦 non_trading_days.json 格式错误")
        non_trading = {str(item) for item in payload}
    complete = set(complete_days)
    unresolved = [
        day
        for day in _weekdays(start, end)
        if day not in complete and day not in non_trading
    ]
    if unresolved:
        preview = unresolved[:10]
        suffix = "..." if len(unresolved) > len(preview) else ""
        raise RuntimeError(
            f"区间仍有 {len(unresolved)} 个工作日未闭合: {preview}{suffix}"
        )


def _run_backfill(start: str, end: str) -> None:
    result = kaipanla_backfill_main(["--start", start, "--end", end])
    if result != 0:
        raise RuntimeError(
            f"开盘啦区间回灌失败: start={start}, end={end}, exit={result}"
        )


def _ensure_kaipanla(day: str) -> dict[str, Any]:
    existed = _historical_complete(day)
    if not existed:
        _run_backfill(day, day)
    if not _historical_complete(day):
        raise RuntimeError(f"{day} 不是开盘啦已发布的完整交易日")
    payload = load_kaipanla_day(day)
    print(
        f"{'CHECKED' if existed else 'FETCHED'} {day} "
        f"kaipanla_stocks={len(payload['stocks'])}"
    )
    return payload


def _require_complete_day(day: str) -> dict[str, Any]:
    component = build_day_component(day)
    coverage = component["coverage"]
    required = ("kpl_ready", "fact_ready")
    missing = [name for name in required if coverage.get(name) is not True]
    if missing:
        raise RuntimeError(
            f"{day} 完整性门禁失败: {missing}; "
            f"coverage={json.dumps(coverage, ensure_ascii=False)}"
        )
    if component.get("source_issues"):
        raise RuntimeError(
            f"{day} 开盘啦来源异常: "
            f"{json.dumps(component['source_issues'], ensure_ascii=False)}"
        )
    return component


def update_day(day_value: str) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    _ensure_kaipanla(day)
    component = _require_complete_day(day)
    market = component["market"]
    market_summary_keys = (
        "kaipanla_stock_count",
        "limit_up_count",
        "missing_main_theme_count",
        "first_board_count",
        "higher_board_count",
        "max_boards",
        "max_board_holders",
        "board_counts",
        "market_mood",
        "rise_count",
        "fall_count",
        "limit_down_count",
        "natural_limit_down_count",
    )
    return {
        "target_date": day,
        "market": {key: market.get(key) for key in market_summary_keys},
        "coverage": component["coverage"],
        "source": "kaipanla_only",
        "facts_verified": True,
    }


def update_range(start_value: str, end_value: str) -> dict[str, Any]:
    start = date.fromisoformat(start_value).isoformat()
    end = date.fromisoformat(end_value).isoformat()
    if start > end:
        raise ValueError("--start 不能晚于 --end")
    if end > date.today().isoformat():
        raise ValueError("--end 不能晚于今天")
    _run_backfill(start, end)
    days = _complete_days(start, end)
    if not days:
        raise RuntimeError(f"区间内没有开盘啦完整交易日: {start} ~ {end}")
    _require_closed_range(start, end, days)
    for index, day in enumerate(days, 1):
        _require_complete_day(day)
        print(f"VERIFIED [{index}/{len(days)}] {day}")
    return {
        "start": start,
        "end": end,
        "first_trade_date": days[0],
        "last_trade_date": days[-1],
        "trade_day_count": len(days),
        "source": "kaipanla_only",
        "facts_verified": True,
    }


def update_latest() -> dict[str, Any]:
    today = date.today()
    start = today - timedelta(days=31)
    _run_backfill(start.isoformat(), today.isoformat())
    days = _complete_days(start.isoformat(), today.isoformat())
    if not days:
        raise RuntimeError("最近31日没有开盘啦完整交易日")
    return update_day(days[-1])


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--date", help="严格更新指定交易日 YYYY-MM-DD")
    target.add_argument("--start", help="批量回灌起始日期 YYYY-MM-DD")
    parser.add_argument("--end", help="批量回灌结束日期 YYYY-MM-DD")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    if bool(args.start) != bool(args.end):
        raise ValueError("--start 与 --end 必须同时提供")
    if args.date and args.end:
        raise ValueError("--date 不能与 --end 同时使用")

    with _update_lock():
        if args.start:
            result = update_range(args.start, args.end)
        elif args.date:
            result = update_day(args.date)
        else:
            result = update_latest()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
