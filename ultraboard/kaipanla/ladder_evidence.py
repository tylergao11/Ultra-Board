# -*- coding: utf-8 -*-
"""主升梯队人工判断的轻量证据接口。

只取证，不选梯队、不选股票：

  # 第一阶段：只看节点日收盘证据，不加载 T+1
  python -m ultraboard.kaipanla.ladder_evidence node 2025-12-12 2025-12-16

  # 第二阶段：梯队冻结后，才查看该层的 T+1 个股 PK
  python -m ultraboard.kaipanla.ladder_evidence pk 2025-12-12:2 2025-12-16:4

两种命令都支持 ``--format json``。默认输出适合直接阅读的 Markdown。

真相源边界：
- 梯队、公告属性、题材发酵：ladder_daily/by_day/{date}.json
- 个股梯队列表 theme：raw/{date}/zt_pool.json 的 theme
- 连板沿途题材：同一真相源中该股从 2 板到节点日的逐日 theme，仅作辅助证据
- 开盘、首封、成交量额、日内 OHLC：raw/{date}/zt_pool.json + ohlc.json
- 市场破板率：raw/{date}/expression.json 的 info[7]

明确不读取人工判断、自动选层、最终高度、未来收益等裁判字段，也不替人工宣布
“应有竞价”或“资金已迁移”。concepts/raw[12] 是静态概念堆，永不参与题材匹配；
公告／自然身份只看最高板日的梯队 theme；断板时看断板前一交易日，不继承更早身份。当前原始池没有末封时间，
地域也暂不纳入；接口绝不拿首封冒充末封，也不硬编码地域或名称关联。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import ohlc
from .announcements import resolve_identity
from .price_shapes import is_one_price


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
BY_DAY_DIR = DATA_DIR / "by_day"
CN_TZ = timezone(timedelta(hours=8))


@lru_cache(maxsize=None)
def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return int(number) if number is not None else None


def as_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def code_of(value: Any) -> str:
    return str(value or "").zfill(6)


def seal_time(ts: Any) -> str | None:
    seconds = as_int(ts)
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).astimezone(CN_TZ).strftime(
        "%H:%M:%S"
    )


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def nominal_limit_pct(code: str, name: str | None) -> float:
    """用于相对涨停幅度展示的交易所名义涨停幅度。"""
    if "ST" in str(name or "").upper():
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    return 10.0


def raw_pool(day: str) -> dict[str, Any]:
    return load_json(RAW_DIR / day / "zt_pool.json")


@lru_cache(maxsize=None)
def raw_stock_map(day: str) -> dict[str, dict[str, Any]]:
    return {
        code_of(row.get("code")): row
        for row in (raw_pool(day).get("stocks") or [])
    }


def ohlc_map(day: str) -> dict[str, dict[str, Any]]:
    path = RAW_DIR / day / "ohlc.json"
    if not path.exists():
        return {}
    return {
        code_of(code): row
        for code, row in (load_json(path).get("stocks") or {}).items()
    }


def cached_ohlc(code: str, day: str) -> dict[str, Any]:
    """读取已验证的统一未复权缓存；缺失时不联网、不猜值。"""
    path = ohlc.CACHE_DIR / f"{code}.json"
    if not path.exists():
        return {}
    payload = load_json(path)
    if payload.get("price_mode") != ohlc.CACHE_PRICE_MODE:
        return {}
    return (payload.get("bars") or {}).get(day) or {}


@lru_cache(maxsize=1)
def available_trade_days() -> tuple[str, ...]:
    days = tuple(sorted(
        path.name
        for path in RAW_DIR.iterdir()
        if path.is_dir() and (path / "zt_pool.json").exists()
    ))
    for day in days:
        day_dir = RAW_DIR / day
        if not (day_dir / "_DONE").exists() or (day_dir / "_MISMATCH").exists():
            raise RuntimeError(f"{day} 主源未完成，禁止进入梯队算法")
        pool = load_json(day_dir / "zt_pool.json")
        audit = pool.get("source_reconciliation") or {}
        stocks = pool.get("stocks") or []
        if (
            int(audit.get("included_count", -1)) != len(stocks)
            or int(audit.get("source_row_count", -1))
            != len(stocks) + int(audit.get("excluded_bse_count") or 0)
        ):
            raise RuntimeError(f"{day} 主源行未完成同源对账，禁止进入梯队算法")
        ohlc_path = day_dir / "ohlc.json"
        if not ohlc_path.exists():
            raise RuntimeError(f"{day} 缺少 OHLC，禁止进入梯队算法")
        ohlc_doc = load_json(ohlc_path)
        if not isinstance(ohlc_doc, dict) or str(ohlc_doc.get("date") or "") != day:
            raise RuntimeError(f"{day} OHLC 日期不一致，禁止进入梯队算法")
        raw_ohlc_stocks = ohlc_doc.get("stocks")
        if not isinstance(raw_ohlc_stocks, dict):
            raise RuntimeError(f"{day} OHLC 股票表格式错误，禁止进入梯队算法")
        if as_int(ohlc_doc.get("count")) != len(raw_ohlc_stocks):
            raise RuntimeError(f"{day} OHLC 行数未对账，禁止进入梯队算法")

        expected_ohlc_codes = {
            code_of(stock.get("code"))
            for stock in stocks
            if (as_int(stock.get("boards")) or 0) >= 2
        }
        normalized_ohlc: dict[str, dict[str, Any]] = {}
        for raw_code, bar in raw_ohlc_stocks.items():
            code = code_of(raw_code)
            if code in normalized_ohlc:
                raise RuntimeError(f"{day} OHLC 代码重复，禁止进入梯队算法: {code}")
            if not isinstance(bar, dict):
                raise RuntimeError(f"{day} OHLC 行格式错误，禁止进入梯队算法: {code}")
            normalized_ohlc[code] = bar
        actual_ohlc_codes = set(normalized_ohlc)
        if actual_ohlc_codes != expected_ohlc_codes:
            missing = sorted(expected_ohlc_codes - actual_ohlc_codes)
            extra = sorted(actual_ohlc_codes - expected_ohlc_codes)
            raise RuntimeError(
                f"{day} OHLC 代码未与二板以上梯队对齐，禁止进入梯队算法: "
                f"missing={missing[:10]} extra={extra[:10]}"
            )
        missing_file_fields = [
            f"{code}:{key}"
            for code, bar in normalized_ohlc.items()
            for key in ("open", "close", "high", "low", "prev_close")
            if as_float(bar.get(key)) is None
        ]
        if missing_file_fields:
            raise RuntimeError(
                f"{day} OHLC 文件字段不完整，禁止进入梯队算法: "
                f"{missing_file_fields[:10]}"
            )
        missing_ohlc = [
            code_of(stock.get("code"))
            for stock in stocks
            if (as_int(stock.get("boards")) or 0) >= 2
            and any(stock.get(key) is None for key in ("open", "high", "low", "prev_close"))
        ]
        if missing_ohlc:
            raise RuntimeError(
                f"{day} 二板以上 OHLC 不完整，禁止进入梯队算法: {missing_ohlc[:10]}"
            )
    return days


def next_trade_day(day: str) -> str | None:
    return next((item for item in available_trade_days() if item > day), None)


def stock_theme_path(end_day: str, code: str, end_height: int) -> dict[str, Any]:
    """回溯个股当前连板路径从二板起真实出现过的开盘啦 theme。

    板高必须严格按 2 递增到 ``end_height``。个股停牌时会跨过没有该票的
    市场交易日；若遇到该票但板高不连续则立即停止，不向静态 concepts 补属性。
    该路径只作沿途证据，不用于公告／自然身份分类。
    """
    expected_height = end_height
    reverse_steps: list[dict[str, Any]] = []
    days = [item for item in available_trade_days() if item <= end_day]
    for route_day in reversed(days):
        if expected_height < 2:
            break
        stock = raw_stock_map(route_day).get(code)
        if stock is None:
            # 连板数以开盘啦为权威；当前仍为 N 板时，中间缺票只能是该股未交易
            # 或源数据未覆盖，不能把市场交易日误当成该股断板日。
            continue
        actual_height = as_int((stock or {}).get("boards"))
        if actual_height != expected_height:
            break
        reverse_steps.append(
            {
                "date": route_day,
                "height": actual_height,
                "theme": str(stock.get("theme") or ""),
                "sector_code": str(stock.get("sector_code") or ""),
            }
        )
        expected_height -= 1

    steps = list(reversed(reverse_steps))
    themes: list[str] = []
    for step in steps:
        theme = step["theme"]
        if theme and theme not in themes:
            themes.append(theme)
    return {
        "complete": expected_height < 2,
        "themes": themes,
        "steps": steps,
    }


def theme_history(day: str, theme: str, history_days: int) -> list[dict[str, Any]]:
    if history_days == 0:
        return []
    prior_days = [item for item in available_trade_days() if item < day][-history_days:]
    history = []
    for prior_day in prior_days:
        path = BY_DAY_DIR / f"{prior_day}.json"
        if not path.exists():
            continue
        counts = (
            (load_json(path).get("market") or {}).get("theme_first_board_counts")
            or {}
        )
        history.append(
            {"date": prior_day, "first_board_count": as_int(counts.get(theme)) or 0}
        )
    return history


def by_day_stock_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for members in (payload.get("ladder") or {}).values():
        for row in members:
            rows[code_of(row.get("code"))] = row
    return rows


def theme_first_boards(
    stocks: list[dict[str, Any]], theme: str
) -> list[dict[str, Any]]:
    return sorted(
        [
            row
            for row in stocks
            if as_int(row.get("boards")) == 1 and row.get("theme") == theme
        ],
        key=lambda row: as_int(row.get("first_limit_ts")) or 10**20,
    )


def theme_timing(
    all_stocks: list[dict[str, Any]], theme: str, candidate_ts: Any
) -> dict[str, Any]:
    firsts = theme_first_boards(all_stocks, theme)
    cutoff = as_int(candidate_ts)
    before = (
        sum((as_int(row.get("first_limit_ts")) or 10**20) <= cutoff for row in firsts)
        if cutoff
        else None
    )
    return {
        "before_candidate_first_seal": before,
        "close_count": len(firsts),
        "first_times": [seal_time(row.get("first_limit_ts")) for row in firsts],
    }


def market_snapshot(
    day: str,
    by_day: dict[str, Any],
    pool: dict[str, Any],
    *,
    limit_reason_ranking: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expression = load_json(RAW_DIR / day / "expression.json").get("info") or []
    market = by_day.get("market") or {}
    themes = market.get("theme_first_board_counts") or {}
    ranking = limit_reason_ranking or []
    return {
        "limit_count": as_int(pool.get("count")),
        "max_board": as_int(pool.get("max_board")),
        "board_counts": pool.get("board_counts") or {},
        "first_board_count": as_int(market.get("first_board_count")),
        "ge2_count": as_int(market.get("ge2_count")),
        "promotion": {
            "one_to_two_pct": as_float(expression[4]) if len(expression) > 4 else None,
            "two_to_three_pct": as_float(expression[5]) if len(expression) > 5 else None,
            "high_board_pct": as_float(expression[6]) if len(expression) > 6 else None,
        },
        "main_market_break_pct": (
            as_float(expression[7]) if len(expression) > 7 else None
        ),
        "top_themes": [
            {"theme": theme, "first_board_count": as_int(count)}
            for theme, count in sorted(themes.items(), key=lambda item: (-item[1], item[0]))
        ],
        "limit_reason_ranking": ranking,
        "limit_reason_top_two": ranking[:2],
        "limit_reason_ranking_contract": (
            "开盘啦市场动向口径：按涨停家数降序；家数相同按题材成交额降序；"
            "再以接口源位置稳定排序"
        ),
    }


def stock_amount(stock: dict[str, Any]) -> float:
    """读取 DailyLimitPerformance 的当日成交额。"""
    for key in ("amount", "成交额"):
        value = as_float(stock.get(key))
        if value is not None:
            return value
    raw = stock.get("raw")
    if isinstance(raw, list) and len(raw) > 11:
        return as_float(raw[11]) or 0.0
    return 0.0


def limit_reason_ranking(day: str) -> list[dict[str, Any]]:
    """构造进攻模型使用的节点日市场动向排名。

    历史 ``GetYTFP_BKHX`` 的数组位置不是客户端最终展示顺序。2026-03-31 与
    2025-11-10 的同期客户端画面共同确认：先按涨停家数，再按题材成交额；
    最高连板不参与这一级排名，最后仅用接口源位置保证完全相同时稳定。
    """
    path = RAW_DIR / day / "sector_ladder.json"
    if not path.exists():
        return []
    stocks = raw_pool(day).get("stocks") or []
    stocks_by_theme: dict[str, list[dict[str, Any]]] = {}
    for stock in stocks:
        # 市场动向榜与个股都使用梯队列表 theme，维持同一真相源。
        theme = str(stock.get("theme") or "").strip()
        if theme:
            stocks_by_theme.setdefault(theme, []).append(stock)

    ranking = []
    seen = set()
    for fallback_position, sector in enumerate(
        load_json(path).get("sectors") or [],
        1,
    ):
        theme = str(sector.get("name") or "").strip()
        if not theme or theme in seen:
            continue
        seen.add(theme)
        members = stocks_by_theme.get(theme) or []
        source_position = as_int(sector.get("source_position")) or fallback_position
        ranking.append({
            "theme": theme,
            "reported_count": as_int(sector.get("count")) or 0,
            "theme_amount": sum(stock_amount(stock) for stock in members),
            "highest_board": max(
                (as_int(stock.get("boards")) or 0 for stock in members),
                default=0,
            ),
            "source_position": source_position,
        })
    ranking.sort(key=lambda row: (
        -row["reported_count"],
        -row["theme_amount"],
        row["source_position"],
    ))
    for rank, row in enumerate(ranking, 1):
        row["rank"] = rank
        row["display_color"] = (
            "red" if rank == 1 else "orange" if rank == 2 else "neutral"
        )
    return ranking


def announcement_identity(
    day: str,
    stock: dict[str, Any],
) -> dict[str, Any]:
    """只按所判断交易日当天梯队 theme 解析公告／自然身份。"""
    identity = resolve_identity(
        day=day,
        theme=stock.get("theme"),
        sector_code=stock.get("sector_code"),
    )
    return {
        "announcement": identity["is_announcement"],
        "announcement_type": identity["announcement_type"],
        "announcement_origin_date": identity["announcement_origin_date"],
        "announcement_source": identity["announcement_source"],
        "natural_theme": identity["natural_theme"],
        "natural_theme_date": identity["natural_theme_date"],
        "effective_theme": identity["effective_theme"],
    }


@lru_cache(maxsize=None)
def daily_stock_context(day: str) -> dict[str, Any]:
    """构造同日全涨停池的沿途证据与当日身份。

    节点证据和第二阶段初始评分共用这一入口，避免两处分别解释公告身份。
    返回内容严格截止 ``day``，不寻找下一交易日。
    """
    by_day = load_json(BY_DAY_DIR / f"{day}.json")
    if by_day.get("information_cutoff") != day:
        raise ValueError(
            f"{day} 的派生快照没有同日信息截止标记；请先重建 ladder_daily"
        )

    pool = raw_pool(day)
    stocks = pool.get("stocks") or []
    meta_map = by_day_stock_map(by_day)
    routes = {
        code_of(row.get("code")): stock_theme_path(
            day,
            code_of(row.get("code")),
            as_int(row.get("boards")) or 0,
        )
        for row in stocks
    }
    identities = {
        code_of(row.get("code")): announcement_identity(
            day,
            row,
        )
        for row in stocks
    }
    return {
        "day": day,
        "information_cutoff": day,
        "by_day": by_day,
        "pool": pool,
        "stocks": stocks,
        "meta_map": meta_map,
        "routes": routes,
        "identities": identities,
    }


def node_evidence(day: str, history_days: int = 3) -> dict[str, Any]:
    context = daily_stock_context(day)
    by_day = context["by_day"]
    pool = context["pool"]
    all_stocks = context["stocks"]
    meta_map = context["meta_map"]
    ladder_rows = [
        row
        for row in all_stocks
        if (as_int(row.get("boards")) or 0) >= 2
    ]
    theme_counts = (by_day.get("market") or {}).get("theme_first_board_counts") or {}
    all_routes = context["routes"]
    identities = context["identities"]
    routes = {
        code_of(row.get("code")): all_routes[code_of(row.get("code"))]
        for row in ladder_rows
    }

    reason_ranking = limit_reason_ranking(day)
    reason_by_theme = {
        item["theme"]: item for item in reason_ranking
    }
    top_two_themes = {
        item["theme"] for item in reason_ranking[:2]
    }

    distinct_themes: set[str] = set()
    for row in ladder_rows:
        code = code_of(row.get("code"))
        if identities[code]["announcement"]:
            continue
        distinct_themes.update(
            str(theme) for theme in routes[code]["themes"] if theme
        )
    histories = {
        theme: theme_history(day, theme, history_days) for theme in distinct_themes
    }
    height_counts: dict[int, int] = {}
    route_theme_heights: dict[str, list[int]] = {}
    for row in ladder_rows:
        code = code_of(row.get("code"))
        height = as_int(row.get("boards")) or 0
        height_counts[height] = height_counts.get(height, 0) + 1
        if identities[code]["announcement"]:
            continue
        for route_theme in routes[code]["themes"]:
            if route_theme:
                route_theme_heights.setdefault(str(route_theme), []).append(height)

    change = by_day.get("change") or {}
    previous_day = change.get("prev_date")
    broken = []
    for row in change.get("broken") or []:
        code = code_of(row.get("code"))
        height = as_int(row.get("boards_before_break") or row.get("boards")) or 0
        theme = str(row.get("theme") or "")
        route = (
            stock_theme_path(previous_day, code, height)
            if previous_day
            else {"complete": False, "themes": [], "steps": []}
        )
        route_themes = route["themes"] or ([theme] if theme else [])
        identity = resolve_identity(
            day=previous_day or day,
            theme=theme,
            sector_code=row.get("sector_code"),
        )
        broken.append(
            {
                "code": code,
                "name": row.get("name"),
                "height": height,
                "theme": theme,
                "theme_path": route["steps"],
                "theme_path_complete": route["complete"],
                "route_themes": route_themes,
                "announcement": identity["is_announcement"],
                "announcement_type": identity["announcement_type"],
                "announcement_origin_date": identity["announcement_origin_date"],
            }
        )
    broken.sort(key=lambda row: (-(row["height"] or 0), row["code"]))

    candidates = []
    for raw in ladder_rows:
        code = code_of(raw.get("code"))
        meta = meta_map.get(code) or {}
        theme = str(raw.get("theme") or meta.get("theme") or "")
        height = as_int(raw.get("boards")) or 0
        route = routes[code]
        identity = identities[code]
        candidate_ts = raw.get("first_limit_ts")
        route_theme_evidence = []
        attack_route_themes = (
            [str(item) for item in route["themes"] if item]
            if not identity["announcement"]
            else []
        )
        if not attack_route_themes and not identity["announcement"]:
            natural_theme = str(identity.get("natural_theme") or "")
            attack_route_themes = [natural_theme] if natural_theme else []
        for route_theme in attack_route_themes:
            peer_heights = route_theme_heights.get(route_theme) or []
            history = histories.get(route_theme) or []
            same_height_theme_count = sum(item == height for item in peer_heights)
            reason_item = reason_by_theme.get(route_theme)
            route_theme_evidence.append(
                {
                    "theme": route_theme,
                    "path_steps": [
                        {"date": step["date"], "height": step["height"]}
                        for step in route["steps"]
                        if step["theme"] == route_theme
                    ],
                    "current_theme": route_theme == identity.get("effective_theme"),
                    "raw_current_theme": route_theme == theme,
                    "first_board_count": as_int(theme_counts.get(route_theme)) or 0,
                    "limit_reason_rank": (
                        reason_item["rank"] if reason_item else None
                    ),
                    "limit_reason_reported_count": (
                        reason_item["reported_count"] if reason_item else 0
                    ),
                    "limit_reason_top_two_matched": route_theme in top_two_themes,
                    "ferment_history": history,
                    "ferment_history_supported_days": sum(
                        item["first_board_count"] > 0 for item in history
                    ),
                    "ferment_history_count_sum": sum(
                        item["first_board_count"] for item in history
                    ),
                    "timing": theme_timing(all_stocks, route_theme, candidate_ts),
                    "height_core": height == max(peer_heights, default=height),
                    "same_height_count": same_height_theme_count,
                    "same_height_share": (
                        same_height_theme_count / height_counts[height]
                        if height_counts.get(height)
                        else 0.0
                    ),
                    "lower_ladder_count": sum(
                        item < height for item in peer_heights
                    ),
                }
            )
        effective_theme = str(identity.get("effective_theme") or theme)
        current_theme_evidence = next(
            (
                item
                for item in route_theme_evidence
                if item["theme"] == effective_theme
            ),
            {
                "first_board_count": 0,
                "limit_reason_rank": None,
                "limit_reason_reported_count": 0,
                "ferment_history": [],
                "ferment_history_supported_days": 0,
                "ferment_history_count_sum": 0,
                "timing": theme_timing(all_stocks, effective_theme, candidate_ts),
                "height_core": True,
                "same_height_count": 1,
                "same_height_share": 1 / height_counts[height],
                "lower_ladder_count": 0,
            },
        )
        candidates.append(
            {
                "height": height,
                "code": code,
                "name": raw.get("name"),
                "theme": theme,
                "effective_theme": effective_theme,
                "natural_theme": identity.get("natural_theme"),
                "natural_theme_date": identity.get("natural_theme_date"),
                "theme_path": route["steps"],
                "theme_path_complete": route["complete"],
                "route_themes": route["themes"],
                "route_theme_evidence": route_theme_evidence,
                "announcement": identity["announcement"],
                "announcement_type": identity["announcement_type"],
                "announcement_origin_date": identity[
                    "announcement_origin_date"
                ],
                "announcement_source": identity["announcement_source"],
                "open_pct": as_float(raw.get("open_pct")),
                "first_seal": seal_time(candidate_ts),
                "final_seal": None,
                "one_price": is_one_price(raw),
                "theme_first_board_count": current_theme_evidence[
                    "first_board_count"
                ],
                "theme_limit_reason_rank": current_theme_evidence[
                    "limit_reason_rank"
                ],
                "theme_limit_reason_reported_count": current_theme_evidence[
                    "limit_reason_reported_count"
                ],
                "theme_ferment_history": current_theme_evidence[
                    "ferment_history"
                ],
                "theme_ferment_history_supported_days": current_theme_evidence[
                    "ferment_history_supported_days"
                ],
                "theme_ferment_history_count_sum": current_theme_evidence[
                    "ferment_history_count_sum"
                ],
                "theme_timing": current_theme_evidence["timing"],
                "theme_height_core": current_theme_evidence["height_core"],
                "same_theme_same_height_count": current_theme_evidence[
                    "same_height_count"
                ],
                "same_theme_height_share": current_theme_evidence[
                    "same_height_share"
                ],
                "same_theme_lower_ladder_count": current_theme_evidence[
                    "lower_ladder_count"
                ],
                "route_theme_has_first_board_support": any(
                    item["first_board_count"] > 0
                    for item in route_theme_evidence
                ),
                "boards_desc": raw.get("boards_desc") or "",
            }
        )
    candidates.sort(
        key=lambda row: (-(row["height"] or 0), row["first_seal"] or "99:99:99", row["code"])
    )

    layout_candidates = []
    for donor in broken:
        for recipient in candidates:
            matched_themes = [
                theme
                for theme in donor["route_themes"]
                if theme in recipient["route_themes"]
            ]
            if matched_themes and (
                (recipient["height"] or 0) < (donor["height"] or 0)
            ):
                layout_candidates.append(
                    {
                        "evidence_level": "association_hypothesis",
                        "evidence_basis": "shared_theme_on_limit_path",
                        "matched_themes": matched_themes,
                        "donor": donor,
                        "recipient": {
                            key: recipient[key]
                            for key in (
                                "code",
                                "name",
                                "height",
                                "theme",
                                "theme_path",
                                "theme_path_complete",
                                "route_themes",
                            )
                        },
                    }
                )

    return {
        "stage": "node_close_only",
        "date": day,
        "market": market_snapshot(
            day,
            by_day,
            pool,
            limit_reason_ranking=reason_ranking,
        ),
        "broken_previous_ladder": broken,
        "shared_theme_path_layout_candidates": layout_candidates,
        "theme_contract": (
            "公告或自然身份只取节点日最高板当天的梯队theme；"
            "节点日为自然票时，进攻模型使用二板起的真实沿途theme与市场动向榜前二相交；"
            "节点日为公告票时不参与自然进攻候选；榜单按涨停家数、"
            "题材成交额依次排序，最高连板不参与榜单排序；"
            "concepts/raw[12]、主营联想和静态全属性不参与匹配"
        ),
        "announcement_contract": (
            "公告型theme统一读取announcement_taxonomy.json，包含ST摘帽、举牌、"
            "定期报告、订单、再融资、重组等；"
            "公告或自然身份只看最高板日梯队theme，不追溯、不继承；"
            "前一日最高自然梯队断板才触发节点，前一日为公告属性的票断板不触发自然节点"
        ),
        "ferment_history_days": history_days,
        "candidates": candidates,
        "source_gap": "原始涨停池只有首封时间，没有末封时间；地域暂不纳入",
    }


def parse_node_spec(spec: str) -> tuple[str, int]:
    try:
        day, height_text = spec.rsplit(":", 1)
        datetime.strptime(day, "%Y-%m-%d")
        height = int(height_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            f"节点格式应为 YYYY-MM-DD:HEIGHT，收到 {spec!r}"
        ) from exc
    if height < 2:
        raise argparse.ArgumentTypeError("主升梯队高度必须 >= 2")
    return day, height


def low_pct(ohlc: dict[str, Any]) -> float | None:
    low, prev = as_float(ohlc.get("low")), as_float(ohlc.get("prev_close"))
    if low is None or not prev:
        return None
    return (low / prev - 1.0) * 100.0


def high_pct(bar: dict[str, Any]) -> float | None:
    high, prev = as_float(bar.get("high")), as_float(bar.get("prev_close"))
    if high is None or not prev:
        return None
    return (high / prev - 1.0) * 100.0


def pk_evidence(
    specs: list[tuple[str, int]], history_days: int = 3
) -> list[dict[str, Any]]:
    packs = []
    for day, height in specs:
        node = node_evidence(day, history_days=history_days)
        candidates = [row for row in node["candidates"] if row["height"] == height]
        if not candidates:
            raise ValueError(f"{day} 不存在 {height} 板候选")
        action_day = next_trade_day(day)
        if not action_day:
            raise ValueError(f"{day} 没有可用的下一交易日")

        action_pool = raw_pool(action_day)
        action_stocks = action_pool.get("stocks") or []
        action_raw = {code_of(row.get("code")): row for row in action_stocks}
        action_ohlc = ohlc_map(action_day)
        action_by_day = load_json(BY_DAY_DIR / f"{action_day}.json")
        action_meta_map = by_day_stock_map(action_by_day)
        action_theme_counts = (
            (action_by_day.get("market") or {}).get("theme_first_board_counts") or {}
        )

        rows = []
        for candidate in candidates:
            code = candidate["code"]
            action = action_raw.get(code) or {}
            action_meta = action_meta_map.get(code) or {}
            bar = action_ohlc.get(code) or cached_ohlc(code, action_day) or action
            action_theme = str(
                action.get("theme") or action_meta.get("theme") or candidate["theme"]
            )
            action_announcement = bool(action_meta.get("is_gonggao"))
            limit_pct = nominal_limit_pct(code, candidate["name"])
            action_first_ts = action.get("first_limit_ts")
            visible_ferment = theme_timing(
                action_stocks, action_theme, action_first_ts
            )
            actual_pct = as_float(bar.get("open_pct"))
            actual_norm = (
                actual_pct / limit_pct
                if actual_pct is not None and limit_pct
                else None
            )
            near_limit = bool(
                actual_pct is not None and actual_pct >= limit_pct * 0.9
            )
            touched = bool(
                action
                or (
                    (intraday_high := high_pct(bar)) is not None
                    and intraday_high >= limit_pct * 0.98
                )
            )
            rows.append(
                {
                    "code": code,
                    "name": candidate["name"],
                    "height": height,
                    "theme": candidate["theme"],
                    "action_theme": action_theme,
                    "node_close": {
                        "announcement": candidate["announcement"],
                        "theme_path": candidate["theme_path"],
                        "theme_path_complete": candidate["theme_path_complete"],
                        "route_themes": candidate["route_themes"],
                        "route_theme_evidence": candidate[
                            "route_theme_evidence"
                        ],
                        "open_pct": candidate["open_pct"],
                        "first_seal": candidate["first_seal"],
                        "final_seal": None,
                        "one_price": candidate["one_price"],
                        "theme_first_board_count": candidate[
                            "theme_first_board_count"
                        ],
                        "theme_ferment_history": candidate[
                            "theme_ferment_history"
                        ],
                        "theme_first_boards_before_seal": candidate["theme_timing"][
                            "before_candidate_first_seal"
                        ],
                    },
                    "available_at_09_25": {
                        "expected_open_pct": None,
                        "expected_source": "manual_judgment_required",
                        "actual_open_pct": actual_pct,
                        "actual_open_norm": actual_norm,
                        "actual_minus_expected_pp": None,
                        "near_limit": near_limit,
                        "action_announcement": action_announcement,
                        "zero_ferment_near_limit_risk": (
                            not candidate["route_theme_has_first_board_support"]
                            and near_limit
                        ),
                    },
                    "available_intraday_when_first_seal_observed": {
                        "first_seal": seal_time(action_first_ts),
                        "final_seal": None,
                        "opened_at_limit": bool(
                            actual_pct is not None
                            and actual_pct >= limit_pct * 0.98
                        ),
                        "low_pct": low_pct(bar),
                        "theme_first_boards_already_sealed": visible_ferment[
                            "before_candidate_first_seal"
                        ],
                    },
                    "available_after_close_only": {
                        "touched_limit": touched,
                        "continued": bool(action),
                        "one_price": bool(touched and is_one_price(bar or action)),
                        "theme_first_board_count": as_int(
                            action_theme_counts.get(action_theme)
                        )
                        or 0,
                    },
                }
            )
        rows.sort(key=lambda row: row["code"])
        packs.append(
            {
                "stage": "frozen_ladder_t1_pk",
                "node_date": day,
                "frozen_height": height,
                "action_date": action_day,
                "candidates": rows,
                "source_gap": (
                    "末封时间和炸板次数缺失；地域暂不纳入；"
                    "应有竞价与关系类型须由人工判断，收盘结果不得倒灌到盘中买点"
                ),
            }
        )
    return packs


def format_theme_path(steps: list[dict[str, Any]]) -> str:
    if not steps:
        return "—"
    groups: list[dict[str, Any]] = []
    for step in steps:
        if groups and groups[-1]["theme"] == step["theme"]:
            groups[-1]["end"] = step["height"]
            continue
        groups.append(
            {
                "theme": step["theme"] or "（无）",
                "start": step["height"],
                "end": step["height"],
            }
        )
    return "→".join(
        (
            f"{group['start']}板{group['theme']}"
            if group["start"] == group["end"]
            else f"{group['start']}-{group['end']}板{group['theme']}"
        )
        for group in groups
    )


def markdown_node(pack: dict[str, Any]) -> str:
    market = pack["market"]
    lines = [
        f"## {pack['date']}｜节点日证据（不含T+1）",
        "",
        (
            f"市场：涨停{market['limit_count']}，最高{market['max_board']}板，"
            f"2板以上{market['ge2_count']}；主市场破板率"
            f"{number(market['main_market_break_pct'])}%｜一进二"
            f"{number(market['promotion']['one_to_two_pct'])}%｜二进三"
            f"{number(market['promotion']['two_to_three_pct'])}%｜高位晋级"
            f"{number(market['promotion']['high_board_pct'])}%"
        ),
        "",
    ]
    broken = pack["broken_previous_ladder"]
    max_broken_height = max((row["height"] or 0 for row in broken), default=0)
    top_broken = [row for row in broken if (row["height"] or 0) == max_broken_height]
    lines.append(
        "断板旧梯队："
        + (
            "、".join(
                f"{row['name']}{row['height']}板/{row['theme']}"
                + ("[公告]" if row["announcement"] else "")
                for row in top_broken
            )
            if top_broken
            else "无"
        )
    )
    links = pack["shared_theme_path_layout_candidates"]
    lines.append(
        "沿途theme重合布局候选（未确认迁移）："
        + (
            "；".join(
                f"{row['donor']['name']}{row['donor']['height']}板→"
                f"{row['recipient']['name']}{row['recipient']['height']}板"
                f"[{','.join(row['matched_themes'])}]"
                for row in links
            )
            if links
            else "无沿途theme高低位映射；补涨、让位或跨题材切换均留给人工判断"
        )
    )
    lines.extend([
        "",
        f"theme读取合同：{pack['theme_contract']}",
        f"公告合同：{pack['announcement_contract']}",
        "",
        "涨停原因发酵前二：" + "、".join(
            f"{row['rank']}.{row['theme']}({row['reported_count']}家/"
            f"{row['theme_amount'] / 1e8:.2f}亿)"
            for row in market["limit_reason_top_two"]
        ),
        "题材首板计数（非排名真相）：" + "、".join(
            f"{row['theme']}{row['first_board_count']}"
            for row in market["top_themes"][:10]
        ),
        "",
    ])
    lines.append("|板|股票|沿途theme|当日公告|开盘|首封|一字|当日自然theme 封前/首板/原因榜名次/历史|当日theme地位|")
    lines.append("|---:|---|---|:---:|---:|---:|:---:|---:|---|")
    for row in pack["candidates"]:
        route_support = []
        for item in row["route_theme_evidence"]:
            timing = item["timing"]
            history_text = "/".join(
                str(history["first_board_count"])
                for history in item["ferment_history"]
            ) or "—"
            route_support.append(
                f"{item['theme']}:"
                f"{timing['before_candidate_first_seal'] if timing['before_candidate_first_seal'] is not None else '—'}"
                f"/{item['first_board_count']}"
                f"/{item['limit_reason_rank'] or '—'}"
                f"/{history_text}"
            )
        position = "高度核心" if row["theme_height_core"] else "非高度核心"
        position += (
            f"；同高{row['same_theme_same_height_count']}"
            f"/{row['same_theme_height_share']:.0%}，低位{row['same_theme_lower_ladder_count']}"
        )
        path_text = format_theme_path(row["theme_path"])
        if not row["theme_path_complete"]:
            path_text += "[路径不完整]"
        lines.append(
            f"|{row['height']}|{row['name']} `{row['code']}`|{path_text}|"
            f"{row['announcement_type'] if row['announcement'] else '否'}|{pct(row['open_pct'])}|"
            f"{row['first_seal'] or '—'}|{'是' if row['one_price'] else '否'}|"
            f"{'；'.join(route_support) or '—'}|{row['theme']}:{position}|"
        )
    lines.extend(["", f"数据缺口：{pack['source_gap']}。"])
    return "\n".join(lines)


def markdown_pk(pack: dict[str, Any]) -> str:
    lines = [
        f"## {pack['node_date']}｜冻结{pack['frozen_height']}板 → {pack['action_date']}个股PK",
        "",
        "|股票|沿途theme|实际竞价|相对涨停|09:25风险|盘中首封|最低涨幅|首封前可见首板|连板*|",
        "|---|---|---:|---:|---|---:|---:|---:|:---:|",
    ]
    for row in pack["candidates"]:
        auction = row["available_at_09_25"]
        intraday = row["available_intraday_when_first_seal_observed"]
        close = row["available_after_close_only"]
        risks = []
        if row["node_close"]["announcement"] or auction["action_announcement"]:
            risks.append("公告")
        if auction["zero_ferment_near_limit_risk"]:
            risks.append("当日theme零发酵近板")
        if intraday["opened_at_limit"]:
            risks.append("涨停开勿排队")
        theme_text = format_theme_path(row["node_close"]["theme_path"])
        if row["action_theme"] not in row["node_close"]["route_themes"]:
            theme_text += f"→{row['action_theme']}"
        lines.append(
            f"|{row['name']} `{row['code']}`|{theme_text}|"
            f"{pct(auction['actual_open_pct'])}|{number(auction['actual_open_norm'])}|"
            f"{'、'.join(risks) or '—'}|"
            f"{intraday['first_seal'] or '—'}|{pct(intraday['low_pct'])}|"
            f"{intraday['theme_first_boards_already_sealed'] if intraday['theme_first_boards_already_sealed'] is not None else '—'}|"
            f"{'是' if close['continued'] else '否'}|"
        )
    lines.extend(
        [
            "",
            "判断边界：应有竞价、补涨/切换/让位、布局线索是否兑现以及 buy/abstain 均由人工基于本包判断；脚本不自动评分。",
            "说明：最终发酵数和是否连板只可用于复盘或下一交易日，不能倒灌到盘中买点。",
            f"数据缺口：{pack['source_gap']}。",
        ]
    )
    return "\n".join(lines)


def emit(payload: Any, output_format: str, renderer) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    packs = payload if isinstance(payload, list) else [payload]
    print("\n\n".join(renderer(pack) for pack in packs))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    node_parser = subparsers.add_parser(
        "node", help="节点日收盘证据；此阶段不会加载T+1"
    )
    node_parser.add_argument("dates", nargs="+", help="节点日 YYYY-MM-DD")
    node_parser.add_argument(
        "--history-days", type=int, default=3, help="展示此前几个交易日的题材发酵，默认3"
    )
    node_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")

    pk_parser = subparsers.add_parser(
        "pk", help="梯队冻结后的T+1个股PK；参数为 YYYY-MM-DD:HEIGHT"
    )
    pk_parser.add_argument("nodes", nargs="+", type=parse_node_spec)
    pk_parser.add_argument(
        "--history-days", type=int, default=3, help="节点日发酵历史窗口，默认3"
    )
    pk_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")

    args = parser.parse_args()
    if args.history_days < 0:
        parser.error("--history-days 不能小于0")
    if args.command == "node":
        payload = [
            node_evidence(day, history_days=args.history_days) for day in args.dates
        ]
        emit(payload, args.format, markdown_node)
    else:
        payload = pk_evidence(args.nodes, history_days=args.history_days)
        emit(payload, args.format, markdown_pk)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
