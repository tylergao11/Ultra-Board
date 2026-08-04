# -*- coding: utf-8 -*-
"""采集 / 补全层：写 data/kaipanla/raw/YYYY-MM-DD/。

入口：
  python -m ultraboard.kaipanla.backfill
  python -m ultraboard.kaipanla.ohlc

扩展：新数据源或字段补全加在本包；读侧约定见仓库根 README。
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
