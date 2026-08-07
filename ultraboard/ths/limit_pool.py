# -*- coding: utf-8 -*-
"""采集同花顺历史涨停池客观事实。

产物写入 ``data/ths/limit_pool/YYYY-MM-DD.json``，包含连板数、连板描述、
首封、终封、炸板次数、板型与真一字身份。具体分类不从此接口读取。

用法：

  python -m ultraboard.ths.limit_pool 2026-08-06
  python -m ultraboard.ths.limit_pool --start 2025-10-01 --end 2025-12-31
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "ths" / "limit_pool"
KAIPANLA_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
ENDPOINT = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
STOCK_LINE_ENDPOINT = "https://d.10jqka.com.cn/v6/line/hs_{code}/01/{period}.js"
CN_TZ = timezone(timedelta(hours=8))
REQUEST_FIELDS = (
    "first_limit_up_time",
    "last_limit_up_time",
    "open_num",
    "high_days",
    "limit_up_type",
    "is_again_limit",
    "change_tag",
)
BOARD_TYPES = frozenset({"一字板", "T字板", "换手板"})
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HIGH_DAYS_RE = re.compile(r"^(\d+)天(\d+)板$")

_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.proxies = {"http": "", "https": ""}
_SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://data.10jqka.com.cn/",
})
_RAW_DAY_CACHE: dict[str, tuple[list[dict[str, Any]], int]] = {}
_RAW_CODE_CACHE: dict[str, frozenset[str]] = {}
_STOCK_YEAR_DAYS_CACHE: dict[tuple[str, int], tuple[str, ...]] = {}
_STOCK_ALL_DAYS_CACHE: dict[str, tuple[tuple[str, ...], bool]] = {}


def output_path(day: str) -> Path:
    return OUTPUT_DIR / f"{day}.json"


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else ""


def parse_high_days(description: Any) -> tuple[int, int]:
    text = str(description or "").strip()
    if text == "首板":
        return 1, 1
    match = HIGH_DAYS_RE.fullmatch(text)
    if match is None:
        raise ValueError(f"无法解析同花顺涨停窗口描述: {text!r}")
    window_days = int(match.group(1))
    limit_up_total = int(match.group(2))
    if window_days < 1 or limit_up_total < 1 or limit_up_total > window_days:
        raise ValueError(f"同花顺涨停窗口描述非法: {text!r}")
    return window_days, limit_up_total


def _fetch_page(day: str, page_number: int) -> tuple[list[dict[str, Any]], int]:
    params = {
        "page": page_number,
        "limit": 200,
        "field": ",".join(REQUEST_FIELDS),
        "filter": "HS,GEM2STAR",
        "order_field": "last_limit_up_time",
        "order_type": 0,
        "date": day.replace("-", ""),
    }
    response = _SESSION.get(ENDPOINT, params=params, timeout=20)
    response.raise_for_status()
    body = response.json()
    if body.get("status_code") != 0:
        raise RuntimeError(f"同花顺涨停池返回失败: {body.get('status_code')}")
    data = body.get("data") or {}
    rows = data.get("info") or []
    page = data.get("page") or {}
    if not isinstance(rows, list):
        raise RuntimeError("同花顺涨停池 info 不是数组")
    total = _as_int(page.get("total"))
    if total is None or total < 0:
        raise RuntimeError("同花顺涨停池缺少合法 total")
    return rows, total


def _fetch_raw_day(day: str) -> tuple[list[dict[str, Any]], int]:
    cached = _RAW_DAY_CACHE.get(day)
    if cached is not None:
        return cached

    first_rows, total = _fetch_page(day, 1)
    rows = list(first_rows)
    for page_number in range(2, math.ceil(total / 200) + 1):
        page_rows, page_total = _fetch_page(day, page_number)
        if page_total != total:
            raise RuntimeError(
                f"同花顺涨停池分页 total 变化: {total} -> {page_total}"
            )
        rows.extend(page_rows)
    if len(rows) != total:
        raise RuntimeError(f"同花顺涨停池未完整取回: total={total}, rows={len(rows)}")
    result = (rows, total)
    _RAW_DAY_CACHE[day] = result
    return result


def _parse_line_response(response: requests.Response, label: str) -> dict[str, Any]:
    response.raise_for_status()
    text = response.text.strip()
    left = text.find("(")
    right = text.rfind(")")
    if left < 0 or right <= left:
        raise RuntimeError(f"同花顺个股交易日响应不是合法 JSONP: {label}")
    body = json.loads(text[left + 1:right])
    if not isinstance(body, dict):
        raise RuntimeError(f"同花顺个股交易日响应不是对象: {label}")
    return body


def _line_days(body: dict[str, Any], label: str) -> tuple[str, ...]:
    raw_data = body.get("data")
    if raw_data in (None, ""):
        return ()
    if not isinstance(raw_data, str):
        raise RuntimeError(f"同花顺个股交易日 data 不是字符串: {label}")

    days: list[str] = []
    for record in raw_data.split(";"):
        compact = record.split(",", 1)[0]
        if not re.fullmatch(r"\d{8}", compact):
            raise RuntimeError(f"同花顺个股交易日格式异常: {label} {compact!r}")
        days.append(f"{compact[:4]}-{compact[4:6]}-{compact[6:]}")
    if days != sorted(set(days)):
        raise RuntimeError(f"同花顺个股交易日存在乱序或重复: {label}")
    return tuple(days)


def _stock_year_days(code: str, year: int) -> tuple[str, ...]:
    key = (code, year)
    cached = _STOCK_YEAR_DAYS_CACHE.get(key)
    if cached is not None:
        return cached
    url = STOCK_LINE_ENDPOINT.format(code=code, period=year)
    response = _SESSION.get(
        url,
        headers={"Referer": f"https://stockpage.10jqka.com.cn/{code}/"},
        timeout=20,
    )
    days = _line_days(_parse_line_response(response, f"{code}/{year}"), f"{code}/{year}")
    if any(not day.startswith(f"{year:04d}-") for day in days):
        raise RuntimeError(f"同花顺个股年度交易日越年: {code}/{year}")
    _STOCK_YEAR_DAYS_CACHE[key] = days
    return days


def _stock_all_days(code: str) -> tuple[tuple[str, ...], bool]:
    cached = _STOCK_ALL_DAYS_CACHE.get(code)
    if cached is not None:
        return cached
    url = STOCK_LINE_ENDPOINT.format(code=code, period="last3600")
    response = _SESSION.get(
        url,
        headers={"Referer": f"https://stockpage.10jqka.com.cn/{code}/"},
        timeout=20,
    )
    body = _parse_line_response(response, f"{code}/last3600")
    days = _line_days(body, f"{code}/last3600")
    total = _as_int(body.get("total"))
    if total is None or total < len(days):
        raise RuntimeError(f"同花顺个股全量交易日 total 异常: {code}")
    result = (days, total == len(days))
    _STOCK_ALL_DAYS_CACHE[code] = result
    return result


def _recent_stock_days(code: str, day: str, required: int | None) -> tuple[list[str], bool]:
    if required == 1:
        return [day], True
    if required is None:
        all_days, complete = _stock_all_days(code)
        eligible = [item for item in all_days if item <= day]
        if not eligible or eligible[-1] != day:
            raise RuntimeError(f"同花顺个股交易日不包含涨停日期: {day} {code}")
        return list(reversed(eligible)), complete

    current_year = int(day[:4])
    descending: list[str] = []
    for year in range(current_year, 1989, -1):
        year_days = _stock_year_days(code, year)
        if year == current_year:
            year_days = tuple(item for item in year_days if item <= day)
            if not year_days or year_days[-1] != day:
                raise RuntimeError(f"同花顺个股交易日不包含涨停日期: {day} {code}")
        descending.extend(reversed(year_days))
        if len(descending) >= required:
            return descending[:required], True
    raise RuntimeError(
        f"同花顺个股交易历史不足以核验涨停窗口: {day} {code} required={required}"
    )


def _raw_day_codes(day: str) -> frozenset[str]:
    cached = _RAW_CODE_CACHE.get(day)
    if cached is not None:
        return cached
    rows, _ = _fetch_raw_day(day)
    codes = frozenset(_code(row.get("code")) for row in rows)
    if "" in codes or len(codes) != len(rows):
        raise RuntimeError(f"{day} 同花顺涨停池代码异常或重复")
    _RAW_CODE_CACHE[day] = codes
    return codes


def _derive_consecutive_dates(
    day: str,
    code: str,
    limit_up_total: int | None,
) -> list[str]:
    stock_days, history_complete = _recent_stock_days(code, day, limit_up_total)
    trace = [day]
    for previous_day in stock_days[1:]:
        if code not in _raw_day_codes(previous_day):
            break
        trace.append(previous_day)
    if limit_up_total is None and len(trace) == len(stock_days) and not history_complete:
        raise RuntimeError(f"同花顺个股历史被截断，无法确定当前连板起点: {day} {code}")
    return list(reversed(trace))


def fetch_day(day: str) -> dict[str, Any]:
    date.fromisoformat(day)
    rows, total = _fetch_raw_day(day)

    stocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise RuntimeError("同花顺涨停池出现非对象股票行")
        code = _code(raw.get("code"))
        name = str(raw.get("name") or "").strip()
        if not code or not name or code in seen:
            raise RuntimeError(f"同花顺涨停池代码、名称异常或重复: {code!r}")
        seen.add(code)

        first_ts = _as_int(raw.get("first_limit_up_time"))
        final_ts = _as_int(raw.get("last_limit_up_time"))
        if first_ts is None or final_ts is None or final_ts < first_ts:
            raise RuntimeError(f"{code} 首封/终封时间异常")
        if "open_num" not in raw:
            raise RuntimeError(f"{code} 缺少显式请求的 open_num")
        raw_open_count = raw.get("open_num")
        open_count = 0 if raw_open_count in (None, "") else _as_int(raw_open_count)
        if open_count is None or open_count < 0:
            raise RuntimeError(f"{code} open_num 非法: {raw_open_count!r}")

        boards_desc = str(raw.get("high_days") or "").strip()
        if boards_desc:
            window_days, limit_up_total = parse_high_days(boards_desc)
        else:
            window_days = None
            limit_up_total = None
        if boards_desc == "首板" or (window_days, limit_up_total) == (1, 1):
            boards = 1
            boards_source = "high_days=first_board"
            trace: list[str] | None = [day]
        elif window_days is not None and window_days == limit_up_total:
            boards = limit_up_total
            boards_source = "high_days=continuous_window"
            trace = None
        else:
            trace = _derive_consecutive_dates(day, code, limit_up_total)
            boards = len(trace)
            boards_source = "tonghuashun_stock_trade_days+daily_limit_up_presence"
        if limit_up_total is not None and boards > limit_up_total:
            raise RuntimeError(
                f"{day} {code} 当前 {boards} 连板超过窗口描述 {boards_desc}"
            )
        if (
            window_days is not None
            and window_days == limit_up_total
            and boards != limit_up_total
        ):
            raise RuntimeError(
                f"{day} {code} 连续窗口描述与逐日涨停池冲突: {boards_desc}, 当前{boards}板"
            )
        board_type = str(raw.get("limit_up_type") or "").strip()
        if board_type not in BOARD_TYPES:
            raise RuntimeError(f"{code} 同花顺板型异常: {board_type!r}")
        one_price = (
            board_type == "一字板"
            and open_count == 0
            and first_ts == final_ts
        )
        if board_type == "一字板" and not one_price:
            raise RuntimeError(f"{code} 一字板与封板过程字段冲突")

        stocks.append({
            "code": code,
            "name": name,
            "boards": boards,
            "boards_desc": boards_desc,
            "limit_up_window_days": window_days,
            "limit_up_total": limit_up_total,
            "boards_source": boards_source,
            "consecutive_limit_up_dates": trace,
            "first_limit_ts": first_ts,
            "final_limit_ts": final_ts,
            "open_count": open_count,
            "board_type": board_type,
            "one_price": one_price,
            "is_again_limit": raw.get("is_again_limit"),
            "change_tag": raw.get("change_tag"),
        })
    stocks.sort(key=lambda row: row["code"])
    return {
        "date": day,
        "source": {
            "provider": "tonghuashun_limit_up_pool",
            "endpoint": ENDPOINT,
            "fetched_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
            "query_contract": {
                "fields": list(REQUEST_FIELDS),
                "filter": "HS,GEM2STAR",
            },
            "stock_trade_days_endpoint": STOCK_LINE_ENDPOINT,
            "boards_contract": "首板与N天N板直接采用同花顺无歧义描述；N天M板(N>M)沿个股实际交易日倒推涨停池连续出现记录，M只作上限",
            "attribute_contract": "本接口只提供客观涨停事实；具体分类只认开盘啦",
        },
        "count": len(stocks),
        "stocks": stocks,
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    body = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(body, dict):
        raise ValueError(f"同花顺涨停池顶层不是对象: {path}")
    return body


def validate_payload(payload: dict[str, Any], day: str, path: Path) -> None:
    stocks = payload.get("stocks")
    source = payload.get("source") or {}
    if (
        payload.get("date") != day
        or source.get("provider") != "tonghuashun_limit_up_pool"
        or not isinstance(stocks, list)
        or payload.get("count") != len(stocks)
    ):
        raise ValueError(f"同花顺涨停池合同异常: {path}")
    seen: set[str] = set()
    for row in stocks:
        if not isinstance(row, dict):
            raise ValueError(f"同花顺涨停池股票行异常: {path}")
        code = _code(row.get("code"))
        if not code or code in seen:
            raise ValueError(f"同花顺涨停池股票代码异常或重复: {path} {code}")
        seen.add(code)
        boards = row.get("boards")
        if isinstance(boards, bool) or not isinstance(boards, int) or boards < 1:
            raise ValueError(f"同花顺当前连板数异常: {path} {code}")
        boards_desc = str(row.get("boards_desc") or "").strip()
        window_days = row.get("limit_up_window_days")
        limit_up_total = row.get("limit_up_total")
        if boards_desc:
            parsed_window, parsed_total = parse_high_days(boards_desc)
            if (window_days, limit_up_total) != (parsed_window, parsed_total):
                raise ValueError(f"同花顺涨停窗口字段不一致: {path} {code}")
            if boards > parsed_total:
                raise ValueError(f"同花顺当前连板数超过窗口涨停总数: {path} {code}")
            if parsed_window == parsed_total and boards != parsed_total:
                raise ValueError(f"同花顺连续窗口与当前连板数冲突: {path} {code}")
        elif window_days is not None or limit_up_total is not None:
            raise ValueError(f"同花顺空 high_days 携带了伪造窗口值: {path} {code}")
        boards_source = row.get("boards_source")
        trace = row.get("consecutive_limit_up_dates")
        if boards_source == "high_days=first_board":
            if (window_days, limit_up_total, boards, trace) != (1, 1, 1, [day]):
                raise ValueError(f"同花顺首板合同异常: {path} {code}")
        elif boards_source == "high_days=continuous_window":
            if (
                not isinstance(window_days, int)
                or window_days < 2
                or window_days != limit_up_total
                or boards != limit_up_total
                or trace is not None
            ):
                raise ValueError(f"同花顺连续窗口合同异常: {path} {code}")
        elif boards_source == "tonghuashun_stock_trade_days+daily_limit_up_presence":
            if (
                not isinstance(trace, list)
                or len(trace) != boards
                or trace != sorted(set(trace))
                or trace[-1] != day
                or any(not isinstance(item, str) or not DAY_RE.fullmatch(item) for item in trace)
            ):
                raise ValueError(f"同花顺当前连板日期证据异常: {path} {code}")
            if window_days is not None and window_days == limit_up_total:
                raise ValueError(f"同花顺无歧义窗口不应进入倒推分支: {path} {code}")
        else:
            raise ValueError(f"同花顺连板数来源异常: {path} {code}")
        if row.get("board_type") not in BOARD_TYPES:
            raise ValueError(f"同花顺板型异常: {path} {code}")
        first_ts = row.get("first_limit_ts")
        final_ts = row.get("final_limit_ts")
        open_count = row.get("open_count")
        if (
            isinstance(first_ts, bool)
            or not isinstance(first_ts, int)
            or isinstance(final_ts, bool)
            or not isinstance(final_ts, int)
            or final_ts < first_ts
            or isinstance(open_count, bool)
            or not isinstance(open_count, int)
            or open_count < 0
        ):
            raise ValueError(f"同花顺封板过程字段异常: {path} {code}")
        expected_one_price = (
            row["board_type"] == "一字板"
            and open_count == 0
            and first_ts == final_ts
        )
        if row.get("one_price") != expected_one_price:
            raise ValueError(f"同花顺真一字字段不一致: {path} {code}")


def load_day(day: str, *, fetch_missing: bool = False, force: bool = False) -> dict[str, Any] | None:
    path = output_path(day)
    if path.exists() and not force:
        payload = _read_json(path)
    elif fetch_missing or force:
        payload = fetch_day(day)
        _write_json_atomic(path, payload)
    else:
        return None
    validate_payload(payload, day, path)
    return payload


def _selected_days(args: argparse.Namespace) -> list[str]:
    selected = {date.fromisoformat(day).isoformat() for day in args.dates}
    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("--start 与 --end 必须同时提供")
        start = date.fromisoformat(args.start).isoformat()
        end = date.fromisoformat(args.end).isoformat()
        if start > end:
            raise ValueError("--start 不能晚于 --end")
        source_days = (
            KAIPANLA_RAW_DIR.iterdir() if KAIPANLA_RAW_DIR.exists() else ()
        )
        for path in source_days:
            if path.is_dir() and DAY_RE.fullmatch(path.name) and start <= path.name <= end:
                selected.add(path.name)
        for path in OUTPUT_DIR.glob("*.json"):
            if DAY_RE.fullmatch(path.stem) and start <= path.stem <= end:
                selected.add(path.stem)
    if not selected:
        raise ValueError("请提供交易日，或同时提供 --start/--end")
    return sorted(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", help="交易日 YYYY-MM-DD")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--interval", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.interval < 0:
        raise ValueError("--interval 不能为负数")

    days = _selected_days(args)
    for index, day in enumerate(days):
        existed = output_path(day).exists()
        payload = load_day(day, fetch_missing=True, force=args.force)
        assert payload is not None
        action = "WROTE" if args.force or not existed else "CHECKED"
        print(f"{action} {day} stocks={payload['count']} -> {output_path(day)}")
        if index + 1 < len(days) and (args.force or not existed):
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
