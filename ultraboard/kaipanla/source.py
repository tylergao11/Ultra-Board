# -*- coding: utf-8 -*-
"""开盘啦数据源的唯一读取接口。"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
THEME_SEPARATOR_RE = re.compile(r"[、，,]+")


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _read(path: Path, *, required: bool = True) -> dict[str, Any] | None:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return None
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"数据源顶层必须是对象: {path}")
    return payload


def stock_themes(stock: dict[str, Any]) -> list[str]:
    """返回开盘啦给出的全部具体分类，保持源顺序并去重。"""
    candidates: list[str] = []
    primary = str(stock.get("theme") or "").strip()
    if primary:
        candidates.append(primary)

    tags_text = str(stock.get("theme_tags_text") or "").strip()
    raw = stock.get("raw")
    if not tags_text and isinstance(raw, list) and len(raw) > 12:
        tags_text = str(raw[12] or "").strip()
    if tags_text:
        candidates.extend(
            part.strip()
            for part in THEME_SEPARATOR_RE.split(tags_text)
            if part.strip()
        )

    result: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item not in seen:
            seen.add(item)
            result.append(item)
    if not result:
        code = stock.get("code") or "?"
        raise ValueError(f"开盘啦个股缺少具体分类: {code}")
    return result


def load_day(value: str) -> dict[str, Any]:
    """读取一天的开盘啦原始快照，不附加任何交易判断。"""
    day = _day(value)
    directory = RAW_DIR / day
    pool = _read(directory / "zt_pool.json")
    ladder = _read(directory / "sector_ladder.json")
    assert pool is not None and ladder is not None

    stocks = pool.get("stocks")
    if pool.get("date") != day or not isinstance(stocks, list):
        raise ValueError(f"开盘啦涨停池合同异常: {directory / 'zt_pool.json'}")
    if pool.get("count") != len(stocks):
        raise ValueError(f"开盘啦涨停池数量不闭合: {directory / 'zt_pool.json'}")
    if ladder.get("date") != day or not isinstance(ladder.get("sectors"), list):
        raise ValueError(f"开盘啦题材梯队合同异常: {directory / 'sector_ladder.json'}")

    normalized_stocks = []
    for source_stock in stocks:
        if not isinstance(source_stock, dict):
            raise ValueError(f"开盘啦个股记录不是对象: {day}")
        stock = dict(source_stock)
        stock["themes"] = stock_themes(stock)
        normalized_stocks.append(stock)

    return {
        "date": day,
        "provider": "kaipanla",
        "stocks": normalized_stocks,
        "sectors": ladder["sectors"],
        "sentiment": _read(directory / "sentiment.json"),
        "expression": _read(directory / "expression.json"),
        "plate_info": _read(directory / "plate_info.json", required=False),
    }
