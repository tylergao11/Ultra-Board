# -*- coding: utf-8 -*-
"""开盘啦个股属性与原始市场快照。

``stocks[].theme``、``stocks[].raw[12]`` 与 ``sector_ladder.json`` 是具体
题材分类的唯一来源。这里不做节点识别、买点判断或结果评分。

采集入口： ``python -m ultraboard.kaipanla.backfill``。
读取入口： :func:`load_day`。
"""

from .client import KaipanlaClient
from .source import load_day, stock_themes

__all__ = [
    "KaipanlaClient",
    "load_day",
    "stock_themes",
]
