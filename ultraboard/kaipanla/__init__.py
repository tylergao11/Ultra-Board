# -*- coding: utf-8 -*-
"""客观行情采集 / 补全层：写 data/kaipanla/raw/YYYY-MM-DD/。

本包产生的题材、概念与公告字段均不是正式决策真相；题材读侧只允许
使用 ``data/ths/strong_wind``。

入口：
  python -m ultraboard.kaipanla.backfill
  python -m ultraboard.kaipanla.ohlc

扩展：板数、OHLC、封板时间等客观字段补全加在本包；读侧约定见根 README。
"""

from .client import KaipanlaClient

__all__ = [
    "KaipanlaClient",
    "enrich",
    "load_day_ohlc",
    "attach_ohlc_to_stocks",
]


def __getattr__(name: str):
    if name in ("enrich", "load_day_ohlc", "attach_ohlc_to_stocks"):
        from . import ohlc as _o
        return getattr(_o, name)
    raise AttributeError(name)
