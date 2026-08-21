# -*- coding: utf-8 -*-
"""更新并校验一个完整交易日的原始事实数据。

默认目标是同花顺官方复盘页已经公开的最新交易日；显式 ``--date``
严格执行指定日期，不自动回退。数据只写入各来源的 canonical 日目录，
不再生成另一套发布快照。
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
from ultraboard.ths.fupan_stories import ensure_day as ensure_story_day
from ultraboard.ths.fupan_stories import latest_available_day
from ultraboard.ths.limit_pool import load_day as load_limit_day


ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "data" / ".daily_update.lock"
KPL_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
THS_LIMIT_DIR = ROOT / "data" / "ths" / "limit_pool"
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


def _ensure_kaipanla(day: str) -> dict[str, Any]:
    directory = KPL_RAW_DIR / day
    if (directory / "_MISMATCH").exists():
        raise RuntimeError(f"{day} 开盘啦来源仍有 _MISMATCH，停止发布")
    historical_complete = (directory / "_DONE").exists()
    current_snapshot = (directory / "_CURRENT_SNAPSHOT").exists()
    existed = historical_complete or current_snapshot
    if not existed:
        result = kaipanla_backfill_main(["--start", day, "--end", day])
        if result != 0:
            raise RuntimeError(f"{day} 开盘啦采集失败: exit={result}")
        historical_complete = (directory / "_DONE").exists()
        if not historical_complete:
            from ultraboard.kaipanla.current_close import collect as collect_current_close

            collect_current_close(
                day,
                screenshots=[],
                expected_limit_up=None,
                expected_limit_down=None,
                expected_themes={},
                height_marks={},
            )
            current_snapshot = True
    payload = load_kaipanla_day(day)
    print(
        f"{'CHECKED' if existed else 'FETCHED'} {day} "
        f"kaipanla_stocks={len(payload['stocks'])} "
        f"snapshot_mode={payload['snapshot_mode']}"
    )
    return payload


def _ensure_limit_pool(day: str) -> dict[str, Any]:
    existed = (THS_LIMIT_DIR / f"{day}.json").exists()
    payload = load_limit_day(day, fetch_missing=True)
    if payload is None:
        raise RuntimeError(f"{day} 同花顺涨停池采集后仍不可用")
    print(
        f"{'CHECKED' if existed else 'FETCHED'} {day} "
        f"ths_limit_stocks={payload['count']}"
    )
    return payload


def _require_complete_day(day: str) -> dict[str, Any]:
    component = build_day_component(day)
    coverage = component["coverage"]
    required = (
        "kpl_ready",
        "ths_limit_pool_ready",
        "ths_story_ready",
        "stock_story_complete",
        "fact_ready",
    )
    missing = [name for name in required if coverage.get(name) is not True]
    if missing:
        raise RuntimeError(
            f"{day} 完整性门禁失败: {missing}; "
            f"coverage={json.dumps(coverage, ensure_ascii=False)}"
        )
    if component.get("source_issues"):
        raise RuntimeError(
            f"{day} 来源集合未闭合: "
            f"{json.dumps(component['source_issues'], ensure_ascii=False)}"
        )
    return component


def update_day(day_value: str) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    _ensure_kaipanla(day)
    _ensure_limit_pool(day)
    story_payload, story_action = ensure_story_day(day)
    story_stock_count = len(story_payload.get("stock_stories") or [])
    if not story_stock_count:
        story_stock_count = sum(
            len(group.get("stocks") or [])
            for group in story_payload.get("stories") or []
            if isinstance(group, dict)
        )
    print(
        f"{story_action.upper()} {day} stories_source={story_payload['source']} "
        f"stock_stories={story_stock_count}"
    )
    component = _require_complete_day(day)
    market = component["market"]
    market_summary_keys = (
        "kaipanla_stock_count",
        "ths_limit_up_count",
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
        "story_source": story_payload["source"],
        "facts_verified": True,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        help=(
            "严格更新指定交易日 YYYY-MM-DD；省略时采用同花顺官方复盘页"
            "已经公开的最新交易日"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = _parser().parse_args(argv)
    official_latest = latest_available_day()
    target = date.fromisoformat(args.date).isoformat() if args.date else official_latest
    if target > official_latest:
        raise RuntimeError(
            f"指定日期尚未进入同花顺官方收盘复盘: "
            f"target={target}, latest={official_latest}"
        )
    mode = "explicit" if args.date else "latest_official_close_recap"
    print(f"TARGET {target} mode={mode}")
    with _update_lock():
        result = update_day(target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
