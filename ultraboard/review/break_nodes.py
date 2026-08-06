# -*- coding: utf-8 -*-
"""自然最高梯队断板节点检测。

节点是集合事件，不是“最高层任意一只断板”：上一交易日最高自然梯队 H 中，
只要仍有一只股票在当日晋级 H+1，当日就不是节点；只有该层全部断板，才形成
节点。上一交易日最高板 theme 为公告的票不进入自然最高梯队集合；身份不追溯、
不继承。不同涨跌幅制度按真实连板数统一参与。

该模块只读取截至节点日的客观交易日数据，不读取人工标签或后续结果。
"""
from __future__ import annotations

from typing import Any

from ultraboard.kaipanla.ladder_evidence import (
    available_trade_days,
    code_of,
    daily_stock_context,
)


def detect_break_node(day: str) -> dict[str, Any]:
    days = list(available_trade_days())
    if day not in days:
        raise ValueError(f"不存在交易日数据: {day}")
    index = days.index(day)
    if index == 0:
        return {
            "date": day,
            "previous_date": None,
            "is_break_node": False,
            "previous_natural_height": None,
            "previous_natural_leaders": [],
            "continued_leaders": [],
            "reason": "首个数据日没有上一交易日，无法判断断板节点",
        }

    previous_day = days[index - 1]
    previous = daily_stock_context(previous_day)
    previous_natural = []
    for stock in previous["stocks"]:
        code = code_of(stock.get("code"))
        height = int(stock.get("boards") or 0)
        if (
            height >= 2
            and not previous["identities"][code]["announcement"]
        ):
            previous_natural.append({
                "code": code,
                "name": stock.get("name"),
                "height": height,
                "theme": stock.get("theme") or "",
            })

    if not previous_natural:
        return {
            "date": day,
            "previous_date": previous_day,
            "is_break_node": False,
            "previous_natural_height": None,
            "previous_natural_leaders": [],
            "continued_leaders": [],
            "reason": "上一交易日没有二板及以上自然梯队",
        }

    highest = max(row["height"] for row in previous_natural)
    leaders = [row for row in previous_natural if row["height"] == highest]
    current = daily_stock_context(day)
    current_by_code = {
        code_of(stock.get("code")): stock for stock in current["stocks"]
    }
    continued = []
    for leader in leaders:
        stock = current_by_code.get(leader["code"])
        if stock and int(stock.get("boards") or 0) == highest + 1:
            continued.append({
                "code": leader["code"],
                "name": leader["name"],
                "from_height": highest,
                "to_height": highest + 1,
            })

    is_node = not continued
    if is_node:
        reason = f"上一交易日{highest}板最高自然梯队全部断板"
    else:
        names = "、".join(row["name"] for row in continued)
        reason = f"最高自然梯队仍有{names}晋级{highest + 1}板，不构成节点"
    return {
        "date": day,
        "previous_date": previous_day,
        "is_break_node": is_node,
        "previous_natural_height": highest,
        "previous_natural_leaders": leaders,
        "continued_leaders": continued,
        "reason": reason,
    }


def list_break_nodes() -> list[dict[str, Any]]:
    return [
        result
        for day in available_trade_days()
        if (result := detect_break_node(day))["is_break_node"]
    ]
