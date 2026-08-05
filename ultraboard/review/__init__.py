# -*- coding: utf-8 -*-
"""复盘派生层：只读 raw，写入 data/kaipanla/ 下派生日录。

入口：
  python -m ultraboard.review.ladder_daily
产物：
  data/kaipanla/ladder_daily/

新复盘视图加在本包；临时探针用完即删，不进入正式路径。
"""

__all__ = ["build_ladder_daily", "RAW_DIR", "OUT_DIR"]


def __getattr__(name: str):
    if name in __all__:
        from . import ladder_daily as _m
        return getattr(_m, name)
    raise AttributeError(name)
