# -*- coding: utf-8 -*-
"""涨跌幅规则与涨停价计算。

整套系统的地基。涨停价算错一分钱，涨停判定、一字板识别、连板计数会全线错误，
上层评分再漂亮也是错的。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum


class Board(str, Enum):
    SH_MAIN = "沪市主板"
    SZ_MAIN = "深市主板"
    CHINEXT = "创业板"
    STAR = "科创板"
    BSE = "北交所"
    B_SHARE = "B股"
    UNKNOWN = "未知"


#: 不参与打板体系的板块
EXCLUDED = {Board.B_SHARE, Board.UNKNOWN}


def classify(code: str) -> Board:
    """按证券代码判断所属板块。"""
    c = str(code).strip()
    if c.startswith(("900", "200")):
        return Board.B_SHARE
    if c.startswith("688"):
        return Board.STAR
    if c.startswith(("300", "301")):
        return Board.CHINEXT
    if c.startswith(("600", "601", "603", "605")):
        return Board.SH_MAIN
    if c.startswith(("000", "001", "002", "003")):
        return Board.SZ_MAIN
    if c.startswith(("430", "830", "831", "832", "833", "834", "835",
                     "836", "837", "838", "839", "870", "871", "872", "873", "920")):
        return Board.BSE
    return Board.UNKNOWN


def is_st(name: str) -> bool:
    """风险警示股。名称里的 ST / *ST / S*ST 都算。"""
    n = str(name).upper().replace(" ", "")
    return "ST" in n


def is_delisting(name: str) -> bool:
    """退市整理期。这类票不参与打板。"""
    return "退" in str(name)


def limit_ratio(code: str, name: str) -> float | None:
    """涨跌幅比例。返回 None 表示不适用或无涨跌幅限制。

    规则依据交易所现行制度：
      沪深主板      10%，风险警示股 5%
      创业板/科创板  20%，风险警示股同为 20%
      北交所         30%
    """
    board = classify(code)
    if board in EXCLUDED or is_delisting(name):
        return None
    if board is Board.BSE:
        return 0.30
    if board in (Board.CHINEXT, Board.STAR):
        return 0.20
    return 0.05 if is_st(name) else 0.10


def _round_half_up(value: float, digits: int = 2) -> float:
    """交易所按四舍五入取到最小价格变动单位。

    不能用内置 round()：它是银行家舍入，且受二进制浮点表示影响，
    round(1.005, 2) 会得到 1.0，直接导致涨停价差一分钱。
    """
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(value)).quantize(q, rounding=ROUND_HALF_UP))


def limit_up_price(prev_close: float, code: str, name: str) -> float | None:
    """涨停价。无涨跌幅限制或不适用时返回 None。"""
    ratio = limit_ratio(code, name)
    if ratio is None or not prev_close:
        return None
    return _round_half_up(prev_close * (1 + ratio))


def limit_down_price(prev_close: float, code: str, name: str) -> float | None:
    ratio = limit_ratio(code, name)
    if ratio is None or not prev_close:
        return None
    return _round_half_up(prev_close * (1 - ratio))


@dataclass(frozen=True)
class LimitState:
    """某一日的涨停状态判定结果。"""
    limit_up: float | None
    at_limit: bool          # 收盘封在涨停价
    one_word: bool          # 一字板：开=高=低=收=涨停价
    t_word: bool            # T字板：开盘即涨停，盘中被砸开过
    applicable: bool        # 该票是否适用涨停判定


def judge(code: str, name: str, prev_close: float,
          open_: float, high: float, low: float, close: float) -> LimitState:
    """按当日 OHLC 判定涨停形态。

    容差取 0.005 元：价格已是分为单位，半分的容差足以吸收浮点误差，
    又不会把相邻价位误判成同一档。
    """
    lp = limit_up_price(prev_close, code, name)
    if lp is None:
        return LimitState(None, False, False, False, applicable=False)

    eq = lambda x: x is not None and abs(x - lp) < 0.005
    at_limit = eq(close)
    one_word = at_limit and eq(open_) and eq(low) and eq(high)
    t_word = at_limit and eq(open_) and not one_word
    return LimitState(lp, at_limit, one_word, t_word, applicable=True)
