# -*- coding: utf-8 -*-
"""采集开盘啦最新收盘快照，并按历史包的核心合同落盘。

历史接口尚未收录当天时，本入口只写可由当前接口和人工截图闭合验证的事实。
市场方向接口若暂时返回空列表，则回退到同源当日 ``DailyLimitPerformance``
五档原始行，并用情绪日期、逐股首封日期和源行总数三重闭合：

- ``sentiment.json``：当前情绪统计；
- ``plate_info.json``：日期校验后的开盘啦市场方向原始响应；
- ``market_highlights.json``：日期校验后的盘面亮点事件时间轴；
- ``market_drawdowns.json``：日期校验后的大幅回撤股票列表；
- ``zt_pool.json``：非 ST 涨停池，theme 只取市场方向分组；
- ``sector_ladder.json``：市场方向及其日内梯队；
- ``expression.json``：保留当前接口响应；若为反爬占位符则显式标不可用；
- ``manual_evidence.json``：用户截图的文件哈希与人工断言。

当前快照不写 ``_DONE``。历史接口补齐后仍由 ``backfill`` 覆盖标准文件并完成
正式同源对账，避免把当前接口缺失的梯队指标伪装成历史完整包。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from .backfill import DATA_DIR, MAX_PID, RAW_DIR, is_bse, parse_stock
from .client import CN_TZ, CURRENT_URL, SECTOR_URL, KaipanlaClient, ok
from ultraboard.ths.limit_pool import _fetch_raw_day as fetch_ths_raw_day

ST_SECTOR_CODE = "801314"
ST_SECTOR_NAME = "ST板块"
PLACEHOLDER = "kaipanla.com"


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(obj, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _as_int(value: Any, label: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} 不是整数: {value!r}") from exc


def _parse_theme_assertion(text: str) -> tuple[str, int]:
    name, sep, raw_count = text.rpartition("=")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError("题材断言格式应为 NAME=COUNT")
    try:
        count = int(raw_count)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("题材家数必须是整数") from exc
    return name.strip(), count


def _parse_height_mark(text: str) -> tuple[str, str]:
    name, sep, tips = text.partition("=")
    if not sep or not name.strip() or not tips.strip():
        raise argparse.ArgumentTypeError("打开高度格式应为 股票名=提示")
    return name.strip(), tips.strip()


def _is_placeholder(body: dict[str, Any]) -> bool:
    values: list[Any] = []
    stack: list[Any] = [body.get("list")]
    while stack:
        value = stack.pop()
        if isinstance(value, list):
            stack.extend(value)
        elif value is not None:
            values.append(value)
    return bool(values) and all(value == PLACEHOLDER for value in values)


def _is_st_sector(sector: dict[str, Any]) -> bool:
    return (
        str(sector.get("ZSCode") or "") == ST_SECTOR_CODE
        or str(sector.get("ZSName") or "") == ST_SECTOR_NAME
    )


def _is_fanbao(boards: int, boards_desc: str) -> bool:
    match = re.fullmatch(r"(\d+)天(\d+)板", boards_desc.strip())
    return bool(match and int(match.group(2)) > boards)


def _stock_from_row(
    row: Any,
    *,
    market_direction: str,
    sector_code: str,
) -> dict[str, Any]:
    if not isinstance(row, list) or len(row) < 19:
        raise RuntimeError(
            f"GetPlateInfo_w38 股票行长度异常: "
            f"{len(row) if isinstance(row, list) else type(row).__name__}"
        )
    code = str(row[0] or "").strip()
    name = str(row[1] or "").strip()
    if not re.fullmatch(r"\d{6}", code) or not name:
        raise RuntimeError(f"股票代码或名称异常: {row[:2]!r}")
    boards = _as_int(row[7], f"{code} {name} 连板数")
    if boards < 1:
        raise RuntimeError(f"{code} {name} 连板数非法: {boards}")
    boards_desc = str(row[9] or "").strip()
    # “其他”分组在客户端卡片上仍显示每只股票自己的题材；该字段位于 raw[16]。
    # 非“其他”分组严格使用市场方向名，与截图中的红/橙/灰题材一致。
    theme = (
        str(row[16] or "").strip()
        if market_direction == "其他"
        else market_direction
    ) or market_direction
    return {
        "code": code,
        "name": name,
        "boards": boards,
        "boards_desc": boards_desc,
        "theme": theme,
        "sector_code": sector_code,
        "market_direction": market_direction,
        "first_limit_ts": row[6],
        "turnover_rate": row[14],
        "amount": row[13],
        "price": None,
        "limit_pct": row[4],
        "is_fanbao": _is_fanbao(boards, boards_desc),
        "raw_source": "GetPlateInfo_w38.StockList",
        "raw": row,
    }


def _load_ths_codes(day_dir: Path, day: str) -> set[str]:
    path = day_dir / "ths_limit_pool.json"
    if path.exists():
        body = json.loads(path.read_text(encoding="utf-8-sig"))
        stocks = body.get("stocks")
        if str(body.get("date") or "") != day or not isinstance(stocks, list):
            raise RuntimeError("同花顺涨停池日期或股票表格式错误")
        codes = {str(stock.get("code") or "") for stock in stocks}
        if len(codes) != len(stocks) or _as_int(body.get("count"), "同花顺 count") != len(codes):
            raise RuntimeError("同花顺涨停池代码重复或 count 未对账")
        return codes

    rows, total = fetch_ths_raw_day(day)
    codes = {str(stock.get("code") or "").strip() for stock in rows}
    if len(codes) != len(rows) or total != len(rows):
        raise RuntimeError("同花顺当日涨停池代码重复或总数未对账")
    return codes


def _performance_rows(body: dict[str, Any], pid: int) -> list[list[Any]]:
    info = body.get("info")
    if not isinstance(info, list) or not info or not isinstance(info[0], list):
        raise RuntimeError(f"DailyLimitPerformance pid={pid} 响应结构异常")
    rows = info[0]
    if not all(isinstance(row, list) for row in rows):
        raise RuntimeError(f"DailyLimitPerformance pid={pid} 出现非数组源行")
    return rows


def _current_performance_snapshot(
    client: KaipanlaClient,
    day: str,
) -> dict[str, Any]:
    stocks: list[dict[str, Any]] = []
    excluded_bse: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    seen: set[str] = set()

    for pid in range(1, MAX_PID + 1):
        body = client.current_daily_limit_performance(pid)
        if not ok(body):
            raise RuntimeError(
                f"开盘啦当日涨停池 pid={pid} 不可用: "
                f"{body.get('errmsg') or body.get('errcode')}"
            )
        rows = _performance_rows(body, pid)
        source_counts[str(pid)] = len(rows)
        for row in rows:
            stock, error = parse_stock(row, pid)
            if error or stock is None:
                raise RuntimeError(error or f"pid={pid} 存在未解析源行")
            code = stock["code"]
            if not re.fullmatch(r"\d{6}", code):
                raise RuntimeError(f"开盘啦当日涨停池代码异常: {code!r}")
            if code in seen:
                raise RuntimeError(f"开盘啦当日涨停池出现重复代码: {code}")
            seen.add(code)
            stamp = stock.get("first_limit_ts")
            if not isinstance(stamp, (int, float)) or stamp <= 0:
                raise RuntimeError(f"{code} 首封时间戳异常: {stamp!r}")
            actual_day = datetime.fromtimestamp(stamp, CN_TZ).date().isoformat()
            if actual_day != day:
                raise RuntimeError(
                    f"{code} 首封日期不匹配: {actual_day} expected={day}"
                )
            stock["market_direction"] = stock.get("theme")
            stock["is_fanbao"] = _is_fanbao(
                int(stock["boards"]), str(stock.get("boards_desc") or "")
            )
            stock["raw_source"] = "DailyLimitPerformance.info[0]"
            if is_bse(code):
                excluded_bse.append(stock)
            else:
                stocks.append(stock)

    if not seen:
        raise RuntimeError("开盘啦当日 DailyLimitPerformance 没有返回涨停股票")

    sector_by_name: dict[str, dict[str, Any]] = {}
    sector_docs: list[dict[str, Any]] = []
    for stock in stocks:
        theme = str(stock.get("theme") or "").strip()
        if not theme:
            continue
        sector = sector_by_name.get(theme)
        if sector is None:
            sector = {
                "code": stock.get("sector_code"),
                "name": theme,
                "count": "0",
                "source_position": None,
                "source_meta": {
                    "mode": "grouped_from_current_DailyLimitPerformance",
                    "ordering_contract": "源未提供板块顺序，不解释先后",
                },
                "tiers": {},
                "fanbao": [],
                "height_marks": [],
            }
            sector_by_name[theme] = sector
            sector_docs.append(sector)
        elif (
            sector.get("code")
            and stock.get("sector_code")
            and sector["code"] != stock["sector_code"]
        ):
            raise RuntimeError(f"题材 {theme} 出现多个板块代码")
        brief = {
            "code": stock["code"],
            "name": stock["name"],
            "tips": stock.get("boards_desc") or "",
        }
        if stock["is_fanbao"]:
            sector["fanbao"].append(brief)
        else:
            sector["tiers"].setdefault(str(stock["boards"]), []).append(brief)

    for sector in sector_docs:
        sector["count"] = str(
            sum(len(items) for items in sector["tiers"].values())
            + len(sector["fanbao"])
        )

    stocks.sort(key=lambda stock: (-stock["boards"], stock["code"]))
    excluded_bse.sort(key=lambda stock: (-stock["boards"], stock["code"]))
    return {
        "stocks": stocks,
        "excluded_bse": excluded_bse,
        "sector_docs": sector_docs,
        "source_counts": source_counts,
        "source_row_count": sum(source_counts.values()),
    }


def _evidence_doc(
    screenshots: list[Path],
    *,
    day: str,
    expected_limit_up: int | None,
    expected_limit_down: int | None,
    expected_themes: dict[str, int],
) -> dict[str, Any]:
    files = []
    for path in screenshots:
        if not path.is_file():
            raise RuntimeError(f"截图不存在: {path}")
        payload = path.read_bytes()
        files.append({
            "name": path.name,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    return {
        "date": day,
        "source": "用户提供的开盘啦收盘截图",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": files,
        "assertions": {
            "limit_up": expected_limit_up,
            "limit_down": expected_limit_down,
            "market_directions": expected_themes,
        },
        "contract": "截图只用于复核可见事实；代码、原始行与完整股票集合取日期校验后的开盘啦当前接口",
    }


def collect(
    day: str,
    *,
    screenshots: list[Path],
    expected_limit_up: int | None,
    expected_limit_down: int | None,
    expected_themes: dict[str, int],
    height_marks: dict[str, str],
) -> dict[str, Any]:
    day_dir = RAW_DIR / day
    if (day_dir / "_DONE").exists():
        raise RuntimeError(f"{day} 已有历史完整包，拒绝用当前快照覆盖")

    client = KaipanlaClient(DATA_DIR, interval_min=0.5, interval_max=1.0)
    sentiment = client.current_zhangfu()
    if not ok(sentiment) or str(sentiment.get("date") or "") != day:
        raise RuntimeError(
            f"开盘啦当前情绪日期不匹配: errcode={sentiment.get('errcode')} "
            f"date={sentiment.get('date')} expected={day}"
        )
    plate = client.plate_info(day)
    performance_snapshot: dict[str, Any] | None = None
    if (
        not ok(plate)
        or plate.get("snapshot_day") != day
        or not isinstance(plate.get("list"), list)
        or not plate.get("list")
    ):
        performance_snapshot = _current_performance_snapshot(client, day)
    market_highlights_raw = client.current_market_highlights()
    highlights = market_highlights_raw.get("List")
    if (
        not ok(market_highlights_raw)
        or str(market_highlights_raw.get("date") or "") != day
        or not isinstance(highlights, list)
        or not highlights
    ):
        raise RuntimeError(
            "开盘啦盘面亮点不可用或日期不匹配: "
            f"errcode={market_highlights_raw.get('errcode')} "
            f"date={market_highlights_raw.get('date')} expected={day}"
        )
    for event in highlights:
        if not isinstance(event, dict):
            raise RuntimeError("开盘啦盘面亮点出现非对象记录")
        stamp = event.get("TimeMin")
        if not isinstance(stamp, (int, float)) or stamp <= 0:
            raise RuntimeError(f"开盘啦盘面亮点时间戳异常: {stamp!r}")
        event_day = datetime.fromtimestamp(stamp, CN_TZ).date().isoformat()
        if event_day != day:
            raise RuntimeError(
                f"开盘啦盘面亮点事件日期不匹配: {event_day} expected={day}"
            )
    market_drawdowns_raw = client.current_market_drawdowns()
    drawdowns = market_drawdowns_raw.get("List")
    if (
        not ok(market_drawdowns_raw)
        or str(market_drawdowns_raw.get("date") or "") != day
        or not isinstance(drawdowns, list)
    ):
        raise RuntimeError(
            "开盘啦大幅回撤不可用或日期不匹配: "
            f"errcode={market_drawdowns_raw.get('errcode')} "
            f"date={market_drawdowns_raw.get('date')} expected={day}"
        )
    for row in drawdowns:
        if (
            not isinstance(row, list)
            or len(row) < 4
            or not re.fullmatch(r"\d{6}", str(row[0] or ""))
            or not str(row[1] or "").strip()
        ):
            raise RuntimeError(f"开盘啦大幅回撤股票行异常: {row!r}")
    expression_raw = client.current_zhangting_expression()

    info = sentiment.get("info") or {}
    sjzt = _as_int(info.get("SJZT"), "开盘啦 SJZT")
    sjdt = _as_int(info.get("SJDT"), "开盘啦 SJDT")
    if expected_limit_up is not None and sjzt != expected_limit_up:
        raise RuntimeError(f"截图涨停 {expected_limit_up} 与开盘啦 SJZT {sjzt} 不一致")
    if expected_limit_down is not None and sjdt != expected_limit_down:
        raise RuntimeError(f"截图跌停 {expected_limit_down} 与开盘啦 SJDT {sjdt} 不一致")

    excluded_st: list[dict[str, Any]] = []
    if performance_snapshot is not None:
        stocks = performance_snapshot["stocks"]
        excluded_bse = performance_snapshot["excluded_bse"]
        sector_docs = performance_snapshot["sector_docs"]
        source_row_count = performance_snapshot["source_row_count"]
        if source_row_count != sjzt:
            raise RuntimeError(
                "开盘啦当日涨停池与情绪口径不闭合: "
                f"source_rows={source_row_count} SJZT={sjzt}"
            )
    else:
        sectors_raw = plate.get("list")
        if not isinstance(sectors_raw, list) or not sectors_raw:
            raise RuntimeError("GetPlateInfo_w38 缺少市场方向列表")

        stocks = []
        excluded_bse = []
        sector_docs = []
        seen: set[str] = set()
        for source_position, sector in enumerate(sectors_raw, 1):
            if not isinstance(sector, dict):
                raise RuntimeError("GetPlateInfo_w38 市场方向出现非对象记录")
            theme = str(sector.get("ZSName") or "").strip()
            sector_code = str(sector.get("ZSCode") or "").strip()
            rows = sector.get("StockList")
            if not theme or not sector_code or not isinstance(rows, list):
                raise RuntimeError(f"市场方向字段异常: {theme!r} {sector_code!r}")
            if _as_int(sector.get("num"), f"{theme} num") != len(rows):
                raise RuntimeError(f"{theme} 报告家数与 StockList 不一致")

            parsed = [
                _stock_from_row(
                    row,
                    market_direction=theme,
                    sector_code=sector_code,
                )
                for row in rows
            ]
            if _is_st_sector(sector):
                excluded_st.extend(parsed)
                continue

            tiers: dict[str, list[dict[str, Any]]] = {}
            fanbao: list[dict[str, Any]] = []
            for stock in parsed:
                code = stock["code"]
                if is_bse(code):
                    excluded_bse.append(stock)
                    continue
                if code in seen:
                    raise RuntimeError(f"开盘啦市场方向出现重复代码: {code}")
                seen.add(code)
                stocks.append(stock)
                brief = {
                    "code": code,
                    "name": stock["name"],
                    "tips": stock["boards_desc"],
                }
                if stock["is_fanbao"]:
                    fanbao.append(brief)
                else:
                    tiers.setdefault(str(stock["boards"]), []).append(brief)

            included_count = sum(len(items) for items in tiers.values()) + len(fanbao)
            doc = {
                "code": sector_code,
                "name": theme,
                "count": str(included_count),
                "source_position": source_position,
                "source_meta": {
                    key: value for key, value in sector.items() if key != "StockList"
                },
                "tiers": tiers,
                "fanbao": fanbao,
                "height_marks": [],
            }
            sector_docs.append(doc)

        source_row_count = len(stocks) + len(excluded_bse)
        if source_row_count == 0:
            raise RuntimeError("开盘啦市场方向没有返回涨停股票")

    stock_by_name = {stock["name"]: stock for stock in stocks}
    sector_by_name = {sector["name"]: sector for sector in sector_docs}
    kaipanla_codes = {stock["code"] for stock in stocks}
    if len(kaipanla_codes) != len(stocks):
        raise RuntimeError("开盘啦当日涨停池存在重复代码")
    ths_codes = _load_ths_codes(day_dir, day)
    if kaipanla_codes != ths_codes:
        missing_ths = sorted(kaipanla_codes - ths_codes)
        missing_kpl = sorted(ths_codes - kaipanla_codes)
        raise RuntimeError(
            f"开盘啦/同花顺股票集合不一致: 同花顺缺 {missing_ths}，开盘啦缺 {missing_kpl}"
        )

    actual_themes = {doc["name"]: int(doc["count"]) for doc in sector_docs}
    for theme, expected in expected_themes.items():
        actual = actual_themes.get(theme)
        if actual != expected:
            raise RuntimeError(f"截图题材 {theme}={expected}，当前接口为 {actual}")

    for name, tips in height_marks.items():
        stock = stock_by_name.get(name)
        if stock is None:
            raise RuntimeError(f"打开高度股票不在当日涨停池: {name}")
        sector = sector_by_name.get(stock["market_direction"])
        if sector is None:
            raise RuntimeError(f"打开高度股票缺少当日主分类: {name}")
        sector["height_marks"].append({
            "code": stock["code"],
            "name": name,
            "tips": tips,
        })

    stocks.sort(key=lambda stock: (-stock["boards"], stock["code"]))
    board_counts = Counter(str(stock["boards"]) for stock in stocks)
    if performance_snapshot is not None:
        source_counts = dict(performance_snapshot["source_counts"])
    else:
        source_board_counts = Counter(
            str(stock["boards"]) for stock in [*stocks, *excluded_bse]
        )
        source_counts = {
            **{
                str(pid): int(source_board_counts.get(str(pid), 0))
                for pid in range(1, 5)
            },
            "5": sum(
                count
                for board, count in source_board_counts.items()
                if int(board) >= 5
            ),
        }
    max_board = max((stock["boards"] for stock in stocks), default=0)
    fanbao_all = [
        {**item, "sector": sector["name"]}
        for sector in sector_docs
        for item in sector["fanbao"]
    ]

    if performance_snapshot is None:
        snapshot_day = plate.get("snapshot_day")
        source_action = "GetPlateInfo_w38"
        source_endpoint = SECTOR_URL
        source_contract = (
            "当前日市场方向 StockList 逐条记账；ST板块和北交所单列排除；"
            "板数与题材仅取开盘啦同源字段；SJZT 仅作不同范围参考"
        )
        plate_doc = {
            **plate,
            "source": {
                "provider": "开盘啦",
                "endpoint": source_endpoint,
                "action": source_action,
                "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
        }
    else:
        snapshot_day = day
        source_action = "DailyLimitPerformance"
        source_endpoint = CURRENT_URL
        source_contract = (
            "当前日 DailyLimitPerformance 五档源行逐条记账；每只股票首封时间"
            "必须属于目标日，五档源行总数必须等于同源 SJZT；板块顺序不可得，"
            "仅按 raw[5] 当日主分类确定性分组"
        )
        plate_doc = {
            "date": day,
            "snapshot_day": day,
            "available": False,
            "unavailable_source": plate,
            "fallback": {
                "action": source_action,
                "source_counts_by_pid": source_counts,
                "source_row_count": source_row_count,
            },
            "source": {
                "provider": "开盘啦",
                "endpoint": source_endpoint,
                "action": source_action,
                "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            },
            "contract": "市场方向接口为空；不伪造板块顺序，使用同源当日涨停池闭合股票事实",
        }
    sentiment_doc = {
        **sentiment,
        "source": {
            "provider": "开盘啦",
            "endpoint": CURRENT_URL,
            "action": "ZhangFuDetail",
            "mode": "current_close_snapshot",
        },
    }
    market_highlights_doc = {
        **market_highlights_raw,
        "source": {
            "provider": "开盘啦",
            "endpoint": CURRENT_URL,
            "action": "GetPMSL_PMLD",
            "mode": "current_close_snapshot",
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "contract": (
            "盘面亮点为平台整理的日内事件标签，只用于补充时序与负反馈；"
            "不得单独作为题材归属或资金因果证明"
        ),
    }
    market_drawdowns_doc = {
        **market_drawdowns_raw,
        "source": {
            "provider": "开盘啦",
            "endpoint": CURRENT_URL,
            "action": "GetPMSL_KQXY",
            "mode": "current_close_snapshot",
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "contract": (
            "大幅回撤为平台整理的亏钱效应列表；保留原始数组，"
            "在字段合同确认前不猜测未命名列含义"
        ),
    }
    expression_doc = {
        "date": day,
        "info": [],
        "errcode": "ANTI_CRAWL_PLACEHOLDER" if _is_placeholder(expression_raw) else expression_raw.get("errcode"),
        "available": False,
        "source": {
            "provider": "开盘啦",
            "endpoint": CURRENT_URL,
            "action": "ZhangTingExpression",
            "mode": "current_close_snapshot",
        },
        "contract": "当前接口未返回可信梯队指标；不猜测晋级率或破板率，等待历史接口补齐",
        "raw_response": expression_raw,
    }
    if not _is_placeholder(expression_raw):
        raise RuntimeError("当前梯队指标响应不再是已知占位结构，需先确认字段合同")

    evidence = _evidence_doc(
        screenshots,
        day=day,
        expected_limit_up=expected_limit_up,
        expected_limit_down=expected_limit_down,
        expected_themes=expected_themes,
    )
    evidence["verification"] = {
        "status": "matched",
        "kaipanla_sjzt": sjzt,
        "kaipanla_source_row_count": source_row_count,
        "source_action": source_action,
        "target_scope_delta_vs_sentiment": sjzt - source_row_count,
        "tonghuashun_count": len(ths_codes),
        "stock_code_sets_equal": True,
        "snapshot_day": snapshot_day,
    }
    zt_pool = {
        "date": day,
        "sjzt": sjzt,
        "count": len(stocks),
        "max_board": max_board,
        "board_counts": dict(sorted(board_counts.items(), key=lambda item: -int(item[0]))),
        "fanbao_count": len(fanbao_all),
        "source_reconciliation": {
            "source_row_count": source_row_count,
            "source_counts_by_pid": source_counts,
            "included_count": len(stocks),
            "excluded_bse_count": len(excluded_bse),
            "excluded_bse": [
                {"code": stock["code"], "name": stock["name"]}
                for stock in excluded_bse
            ],
            "observed_total_with_st": (
                len(stocks) + len(excluded_bse) + len(excluded_st)
            ),
            "excluded_st_count": len(excluded_st),
            "sentiment_sjzt_reference": sjzt,
            "target_scope_delta_vs_sentiment": sjzt - source_row_count,
            "action": source_action,
            "contract": f"{source_contract}；与同花顺代码集合完全对账",
        },
        "stocks": stocks,
    }
    sector_ladder = {
        "date": day,
        "source": {
            "provider": "开盘啦",
            "action": source_action,
            "mode": "current_close_snapshot",
        },
        "sectors": sector_docs,
        "fanbao_all": fanbao_all,
        "height_marks_contract": "仅录入用户截图中可见的打开高度",
    }

    day_dir.mkdir(parents=True, exist_ok=True)
    _write_json(day_dir / "manual_evidence.json", evidence)
    _write_json(day_dir / "plate_info.json", plate_doc)
    _write_json(day_dir / "sentiment.json", sentiment_doc)
    _write_json(day_dir / "market_highlights.json", market_highlights_doc)
    _write_json(day_dir / "market_drawdowns.json", market_drawdowns_doc)
    _write_json(day_dir / "expression.json", expression_doc)
    _write_json(day_dir / "sector_ladder.json", sector_ladder)
    _write_json(day_dir / "zt_pool.json", zt_pool)
    (day_dir / "_CURRENT_SNAPSHOT").write_text(
        "current close snapshot; historical expression pending\n",
        encoding="utf-8",
    )
    return {
        "day": day,
        "count": len(stocks),
        "st_excluded": len(excluded_st),
        "bse_excluded": len(excluded_bse),
        "max_board": max_board,
        "board_counts": dict(board_counts),
        "fanbao_count": len(fanbao_all),
        "themes": len(sector_docs),
        "market_highlights_count": len(highlights),
        "market_drawdowns_count": len(drawdowns),
        "expression_available": False,
        "directory": str(day_dir),
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="开盘啦最新收盘快照采集")
    parser.add_argument("day", help="期望交易日 YYYY-MM-DD")
    parser.add_argument("--screenshot", action="append", type=Path, default=[])
    parser.add_argument("--expected-limit-up", type=int)
    parser.add_argument("--expected-limit-down", type=int)
    parser.add_argument(
        "--expected-theme",
        action="append",
        type=_parse_theme_assertion,
        default=[],
        metavar="NAME=COUNT",
    )
    parser.add_argument(
        "--height-mark",
        action="append",
        type=_parse_height_mark,
        default=[],
        metavar="股票名=提示",
    )
    args = parser.parse_args(argv)
    summary = collect(
        args.day,
        screenshots=args.screenshot,
        expected_limit_up=args.expected_limit_up,
        expected_limit_down=args.expected_limit_down,
        expected_themes=dict(args.expected_theme),
        height_marks=dict(args.height_mark),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
