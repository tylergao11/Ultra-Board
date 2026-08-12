# -*- coding: utf-8 -*-
"""采集开盘啦最新收盘快照，并按历史包的核心合同落盘。

历史接口尚未收录当天时，本入口只写可由当前接口和人工截图闭合验证的事实：

- ``sentiment.json``：当前情绪统计；
- ``plate_info.json``：日期校验后的开盘啦市场方向原始响应；
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

from .backfill import DATA_DIR, RAW_DIR, is_bse
from .client import CURRENT_URL, SECTOR_URL, KaipanlaClient, ok
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
    if not ok(plate) or plate.get("snapshot_day") != day:
        raise RuntimeError(f"开盘啦市场方向快照不可用: {plate.get('errmsg') or plate.get('errcode')}")
    expression_raw = client.current_zhangting_expression()

    info = sentiment.get("info") or {}
    sjzt = _as_int(info.get("SJZT"), "开盘啦 SJZT")
    sjdt = _as_int(info.get("SJDT"), "开盘啦 SJDT")
    if expected_limit_up is not None and sjzt != expected_limit_up:
        raise RuntimeError(f"截图涨停 {expected_limit_up} 与开盘啦 SJZT {sjzt} 不一致")
    if expected_limit_down is not None and sjdt != expected_limit_down:
        raise RuntimeError(f"截图跌停 {expected_limit_down} 与开盘啦 SJDT {sjdt} 不一致")

    sectors_raw = plate.get("list")
    if not isinstance(sectors_raw, list) or not sectors_raw:
        raise RuntimeError("GetPlateInfo_w38 缺少市场方向列表")

    stocks: list[dict[str, Any]] = []
    excluded_st: list[dict[str, Any]] = []
    excluded_bse: list[dict[str, Any]] = []
    sector_docs: list[dict[str, Any]] = []
    seen: set[str] = set()
    stock_by_name: dict[str, dict[str, Any]] = {}
    sector_by_name: dict[str, dict[str, Any]] = {}

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
            stock_by_name[stock["name"]] = stock
            brief = {"code": code, "name": stock["name"], "tips": stock["boards_desc"]}
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
        sector_by_name[theme] = doc

    source_row_count = len(stocks) + len(excluded_bse)
    if source_row_count == 0:
        raise RuntimeError("开盘啦市场方向没有返回涨停股票")
    ths_codes = _load_ths_codes(day_dir, day)
    if seen != ths_codes:
        missing_ths = sorted(seen - ths_codes)
        missing_kpl = sorted(ths_codes - seen)
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
        sector_by_name[stock["market_direction"]]["height_marks"].append({
            "code": stock["code"],
            "name": name,
            "tips": tips,
        })

    stocks.sort(key=lambda stock: (-stock["boards"], stock["code"]))
    board_counts = Counter(str(stock["boards"]) for stock in stocks)
    source_board_counts = Counter(
        str(stock["boards"]) for stock in [*stocks, *excluded_bse]
    )
    source_counts = {
        **{str(pid): int(source_board_counts.get(str(pid), 0)) for pid in range(1, 5)},
        "5": sum(
            count for board, count in source_board_counts.items() if int(board) >= 5
        ),
    }
    max_board = max((stock["boards"] for stock in stocks), default=0)
    fanbao_all = [
        {**item, "sector": sector["name"]}
        for sector in sector_docs
        for item in sector["fanbao"]
    ]

    plate_doc = {
        **plate,
        "source": {
            "provider": "开盘啦",
            "endpoint": SECTOR_URL,
            "action": "GetPlateInfo_w38",
            "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
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
        "kaipanla_market_direction_count": source_row_count,
        "target_scope_delta_vs_sentiment": sjzt - source_row_count,
        "tonghuashun_count": len(ths_codes),
        "stock_code_sets_equal": True,
        "snapshot_day": plate.get("snapshot_day"),
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
            "action": "GetPlateInfo_w38",
            "contract": (
                "当前日市场方向 StockList 逐条记账；ST板块和北交所单列排除；"
                "与同花顺代码集合完全对账；SJZT 仅作不同范围参考"
            ),
        },
        "stocks": stocks,
    }
    sector_ladder = {
        "date": day,
        "source": {
            "provider": "开盘啦",
            "action": "GetPlateInfo_w38",
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
