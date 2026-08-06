# -*- coding: utf-8 -*-
"""涨停价格形态的唯一判定入口。"""
from __future__ import annotations

from typing import Any


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def near_equal(left: Any, right: Any) -> bool:
    a, b = _number(left), _number(right)
    if a is None or b is None:
        return False
    return abs(a - b) <= max(1e-6, abs(b) * 1e-6)


def is_one_price(stock: dict[str, Any]) -> bool:
    """收盘涨停池中的真一字：同一复权口径下开盘价=最高价=最低价。"""
    return near_equal(stock.get("open"), stock.get("high")) and near_equal(
        stock.get("high"), stock.get("low")
    )
