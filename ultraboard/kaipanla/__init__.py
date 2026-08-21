# -*- coding: utf-8 -*-
"""开盘啦个股属性与原始市场快照。

历史题材归属只使用 ``stocks[].theme`` 与 ``sector_ladder.json``。
``stocks[].raw[12]`` 可能回填后来概念，只保留溯源，不进入历史事实。
这里不做节点识别、买点判断或结果评分。

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
