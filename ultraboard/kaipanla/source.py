# -*- coding: utf-8 -*-
"""开盘啦数据源的唯一读取接口。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "kaipanla" / "raw"


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
    """返回可安全用于历史截面的开盘啦当日主分类。

    ``raw[12]``/``theme_tags_text`` 是平台附加概念元数据。历史接口会把后来
    出现的概念回填到旧日期，因此这里只保留 ``raw[5]`` 归一化出的 ``theme``。
    原始附加标签仍保存在落盘记录中，供溯源使用，但不进入正式历史事实。
    """
    primary = str(stock.get("theme") or "").strip()
    return [primary] if primary else []


def historical_circulating_market_cap(stock: dict[str, Any]) -> int | float:
    """读取 DailyLimitPerformance 原始行下标 13 的流通市值。"""
    raw = stock.get("raw")
    if not isinstance(raw, list) or len(raw) <= 13:
        raise ValueError(f"开盘啦历史个股缺少流通市值原始字段: {stock.get('code')}")
    value = raw[13]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"开盘啦历史个股流通市值非法: {stock.get('code')} {value!r}")
    return value


def load_day(value: str) -> dict[str, Any]:
    """读取一天的开盘啦原始快照，不附加任何交易判断。"""
    day = _day(value)
    directory = RAW_DIR / day
    if (directory / "_MISMATCH").exists():
        raise ValueError(f"开盘啦日快照尚未闭合: {directory / '_MISMATCH'}")
    historical_complete = (directory / "_DONE").exists()
    current_snapshot = (directory / "_CURRENT_SNAPSHOT").exists()
    if not historical_complete and not current_snapshot:
        raise FileNotFoundError(f"开盘啦日快照缺少完成标记: {directory}")
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
        if historical_complete:
            stock["circulating_market_cap"] = historical_circulating_market_cap(stock)
            stock["circulating_market_cap_source"] = "DailyLimitPerformance.raw[13]"
        normalized_stocks.append(stock)

    return {
        "date": day,
        "provider": "kaipanla",
        "snapshot_mode": (
            "historical_complete" if historical_complete else "current_close_snapshot"
        ),
        "stocks": normalized_stocks,
        "sectors": ladder["sectors"],
        "sentiment": _read(directory / "sentiment.json"),
        "expression": _read(directory / "expression.json"),
        "plate_info": _read(directory / "plate_info.json", required=False),
    }
