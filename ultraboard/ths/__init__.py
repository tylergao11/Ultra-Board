# -*- coding: utf-8 -*-
"""同花顺当日故事与涨停池客观事实。

具体题材分类不属于本包；统一读取 ``ultraboard.kaipanla``。
"""

from .stories import load_day as load_stories

__all__ = ["load_stories"]

