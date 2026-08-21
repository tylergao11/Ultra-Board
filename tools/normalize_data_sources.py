#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把历史快照规范到当前数据源合同，不生成任何交易判断。"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
KAIPANLA_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"数据源顶层必须是对象: {path}")
    return payload


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def normalize_kaipanla(path: Path, payload: dict[str, Any]) -> bool:
    day = path.parent.name
    stocks = payload.get("stocks")
    if payload.get("date") != day or not isinstance(stocks, list):
        raise ValueError(f"开盘啦涨停池合同异常: {path}")
    if payload.get("count") != len(stocks):
        raise ValueError(f"开盘啦涨停池数量不闭合: {path}")

    changed = False
    for stock in stocks:
        raw = stock.get("raw") if isinstance(stock, dict) else None
        if not isinstance(raw, list) or len(raw) <= 19:
            raise ValueError(f"开盘啦个股缺少原始分类字段: {path}")
        primary = str(raw[5] or "").strip()
        tags_text = str(raw[12] or "").strip()
        sector_code = str(raw[19] or "").strip()
        normalized_primary = primary or None
        if stock.get("theme") != normalized_primary:
            raise ValueError(f"开盘啦主分类与原文不一致: {path} {stock.get('code')}")
        if stock.get("theme_tags_text") != tags_text:
            stock["theme_tags_text"] = tags_text
            changed = True
        normalized_sector_code = sector_code or None
        if stock.get("sector_code") != normalized_sector_code:
            stock["sector_code"] = normalized_sector_code
            changed = True

    source = {
        "provider": "kaipanla",
        "action": "DailyLimitPerformance",
        "primary_field": "stocks[].raw[5]",
        "tags_field": "stocks[].raw[12]",
        "tags_temporal_contract": "raw_only_not_point_in_time_safe",
        "sector_code_field": "stocks[].raw[19]",
        "sector_code_required": False,
    }
    if payload.get("theme_source") != source:
        payload["theme_source"] = source
        changed = True
    missing_main_theme_count = sum(
        not str(stock.get("theme") or "").strip() for stock in stocks
    )
    if payload.get("missing_main_theme_count") != missing_main_theme_count:
        payload["missing_main_theme_count"] = missing_main_theme_count
        changed = True
    return changed


def normalize(
    paths: list[Path], handler: Callable[[Path, dict[str, Any]], bool]
) -> int:
    changed = 0
    for path in paths:
        payload = read_json(path)
        if handler(path, payload):
            write_atomic(path, payload)
            changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start")
    parser.add_argument("--end")
    args = parser.parse_args(argv)
    start = date.fromisoformat(args.start).isoformat() if args.start else None
    end = date.fromisoformat(args.end).isoformat() if args.end else None
    if start and end and start > end:
        raise ValueError("--start 不能晚于 --end")
    kaipanla_paths = sorted(
        path
        for path in KAIPANLA_RAW_DIR.glob("*/zt_pool.json")
        if (path.parent / "_DONE").exists()
        and not (path.parent / "_MISMATCH").exists()
        and (start is None or path.parent.name >= start)
        and (end is None or path.parent.name <= end)
    )
    if not kaipanla_paths:
        raise FileNotFoundError("开盘啦涨停池历史数据为空")
    kaipanla_changed = normalize(kaipanla_paths, normalize_kaipanla)
    print(f"kaipanla={len(kaipanla_paths)} changed={kaipanla_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
