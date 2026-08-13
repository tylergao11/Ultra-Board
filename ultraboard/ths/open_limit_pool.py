# -*- coding: utf-8 -*-
"""采集同花顺历史炸板池客观事实。

产物写入 ``data/ths/open_limit_pool/YYYY-MM-DD.json``。该池只记录当日
曾触及涨停、收盘未封住的股票；是否属于连板冲板，必须与前一交易日涨停池
按代码求交集，不能在采集层猜测。

用法：

  python -m ultraboard.ths.open_limit_pool 2026-08-11
  python -m ultraboard.ths.open_limit_pool --manifest site/public/agent-data/v1/manifest.json
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "ths" / "open_limit_pool"
KAIPANLA_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
ENDPOINT = "https://data.10jqka.com.cn/dataapi/limit_up/open_limit_pool"
CN_TZ = timezone(timedelta(hours=8))
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUEST_FIELDS = (
    "change_rate",
    "latest",
    "limit_up_suc_rate",
    "turnover_rate",
    "currency_value",
    "market_value",
    "first_limit_up_time",
    "open_num",
    "is_again_limit",
    "change_tag",
    "turnover",
)

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


def output_path(day: str) -> Path:
    return OUTPUT_DIR / f"{day}.json"


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else ""


def _fetch_page(day: str, page_number: int) -> tuple[list[dict[str, Any]], int]:
    compact_day = day.replace("-", "")
    params = {
        "page": page_number,
        "limit": 200,
        "field": ",".join(REQUEST_FIELDS),
        "filter": "HS,GEM2STAR",
        "order_field": "first_limit_up_time",
        "order_type": 0,
        "date": compact_day,
    }
    response = _SESSION.get(ENDPOINT, params=params, timeout=20)
    response.raise_for_status()
    body = response.json()
    if body.get("status_code") != 0:
        raise RuntimeError(f"同花顺炸板池返回失败: {body.get('status_code')}")

    data = body.get("data") or {}
    returned_day = str(data.get("date") or "")
    if returned_day != compact_day:
        raise RuntimeError(
            f"同花顺炸板池日期不匹配: requested={compact_day}, returned={returned_day}"
        )
    rows = data.get("info") or []
    page = data.get("page") or {}
    if not isinstance(rows, list):
        raise RuntimeError("同花顺炸板池 info 不是数组")
    total = _as_int(page.get("total"))
    if total is None or total < 0:
        raise RuntimeError("同花顺炸板池缺少合法 total")
    return rows, total


def _fetch_raw_day(day: str) -> tuple[list[dict[str, Any]], int]:
    first_rows, total = _fetch_page(day, 1)
    rows = list(first_rows)
    for page_number in range(2, math.ceil(total / 200) + 1):
        page_rows, page_total = _fetch_page(day, page_number)
        if page_total != total:
            raise RuntimeError(
                f"同花顺炸板池分页 total 变化: {total} -> {page_total}"
            )
        rows.extend(page_rows)
    if len(rows) != total:
        raise RuntimeError(f"同花顺炸板池未完整取回: total={total}, rows={len(rows)}")
    return rows, total


def _first_limit_time(stamp: int) -> str:
    return datetime.fromtimestamp(stamp, CN_TZ).strftime("%H:%M:%S")


def _parse_stock(raw: dict[str, Any], day: str) -> dict[str, Any]:
    code = _code(raw.get("code"))
    name = str(raw.get("name") or "").strip()
    if not code or not name:
        raise RuntimeError(f"同花顺炸板股票代码或名称异常: {code!r} {name!r}")

    first_limit_ts = _as_int(raw.get("first_limit_up_time"))
    open_count = _as_int(raw.get("open_num"))
    change_tag = str(raw["change_tag"]).strip() or None if raw.get("change_tag") is not None else None
    price = _as_float(raw.get("latest"))
    change_rate = _as_float(raw.get("change_rate"))
    circulating_market_cap = _as_float(raw.get("currency_value"))
    total_market_cap = _as_float(raw.get("market_value"))
    turnover_rate = _as_float(raw.get("turnover_rate"))
    turnover_amount = _as_float(raw.get("turnover"))
    limit_up_success_rate = _as_float(raw.get("limit_up_suc_rate"))
    is_again_limit = _as_int(raw.get("is_again_limit"))

    if first_limit_ts is None or first_limit_ts <= 0:
        raise RuntimeError(f"{day} {code} 首次触板时间异常")
    if datetime.fromtimestamp(first_limit_ts, CN_TZ).date().isoformat() != day:
        raise RuntimeError(f"{day} {code} 首次触板时间不属于目标交易日")
    if open_count is not None and open_count < 1:
        raise RuntimeError(f"{day} {code} 炸板次数异常: {raw.get('open_num')!r}")
    # 炸板事实由 open_limit_pool 端点成员资格确定。change_tag 仅描述收盘状态，
    # 可能是 LIMIT_DOWN，也可能是来源未提供的 null。
    if price is None or price <= 0:
        raise RuntimeError(f"{day} {code} 最新价异常")
    if change_rate is None:
        raise RuntimeError(f"{day} {code} 涨跌幅异常")
    if circulating_market_cap is None or circulating_market_cap <= 0:
        raise RuntimeError(f"{day} {code} 流通市值异常")
    if total_market_cap is not None and total_market_cap <= 0:
        raise RuntimeError(f"{day} {code} 总市值异常")
    if turnover_rate is None or turnover_rate < 0:
        raise RuntimeError(f"{day} {code} 换手率异常")
    if turnover_amount is None or turnover_amount < 0:
        raise RuntimeError(f"{day} {code} 成交额异常")
    if limit_up_success_rate is not None and not 0 <= limit_up_success_rate <= 1:
        raise RuntimeError(f"{day} {code} 封板成功率异常")
    if is_again_limit is not None and is_again_limit not in (0, 1):
        raise RuntimeError(f"{day} {code} 回封标记异常")

    return {
        "code": code,
        "name": name,
        "first_limit_ts": first_limit_ts,
        "first_limit_time": _first_limit_time(first_limit_ts),
        "open_count": open_count,
        "change_tag": change_tag,
        "is_again_limit": is_again_limit,
        "price": price,
        "change_rate": change_rate,
        "circulating_market_cap": circulating_market_cap,
        "total_market_cap": total_market_cap,
        "turnover_rate": turnover_rate,
        "turnover_amount": turnover_amount,
        "limit_up_success_rate": limit_up_success_rate,
        "market_type": str(raw.get("market_type") or "").strip() or None,
    }


def fetch_day(day: str) -> dict[str, Any]:
    day = date.fromisoformat(day).isoformat()
    rows, total = _fetch_raw_day(day)
    stocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise RuntimeError("同花顺炸板池出现非对象股票行")
        stock = _parse_stock(raw, day)
        if stock["code"] in seen:
            raise RuntimeError(f"{day} 同花顺炸板池代码重复: {stock['code']}")
        seen.add(stock["code"])
        stocks.append(stock)

    payload = {
        "date": day,
        "source": {
            "provider": "tonghuashun_open_limit_pool",
            "endpoint": ENDPOINT,
            "fetched_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
            "source_date": day.replace("-", ""),
            "source_total": total,
            "query_contract": {
                "fields": list(REQUEST_FIELDS),
                "filter": "HS,GEM2STAR",
                "order_field": "first_limit_up_time",
                "order_type": 0,
            },
            "contract": (
                "仅保存当日曾触及涨停但最终未封住的客观事实；"
                "连板身份必须与前一交易日涨停池按代码求交集"
            ),
        },
        "count": len(stocks),
        "stocks": stocks,
    }
    validate_payload(payload, day, output_path(day))
    return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def validate_payload(payload: dict[str, Any], day: str, path: Path) -> None:
    if payload.get("date") != day:
        raise ValueError(f"同花顺炸板池日期不一致: {path}")
    source = payload.get("source") or {}
    if (
        source.get("provider") != "tonghuashun_open_limit_pool"
        or source.get("endpoint") != ENDPOINT
        or source.get("source_date") != day.replace("-", "")
    ):
        raise ValueError(f"同花顺炸板池来源合同异常: {path}")
    query_contract = source.get("query_contract") or {}
    if query_contract != {
        "fields": list(REQUEST_FIELDS),
        "filter": "HS,GEM2STAR",
        "order_field": "first_limit_up_time",
        "order_type": 0,
    }:
        raise ValueError(f"同花顺炸板池查询合同异常: {path}")
    rows = payload.get("stocks")
    if not isinstance(rows, list) or payload.get("count") != len(rows):
        raise ValueError(f"同花顺炸板池数量不闭合: {path}")
    if source.get("source_total") != len(rows):
        raise ValueError(f"同花顺炸板池源数量不闭合: {path}")

    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"同花顺炸板池股票记录不是对象: {path}")
        code = _code(row.get("code"))
        if not code or code in seen or row.get("code") != code:
            raise ValueError(f"同花顺炸板池代码异常或重复: {path} {code!r}")
        seen.add(code)
        first_limit_ts = row.get("first_limit_ts")
        if (
            not isinstance(first_limit_ts, int)
            or first_limit_ts <= 0
            or datetime.fromtimestamp(first_limit_ts, CN_TZ).date().isoformat() != day
            or row.get("first_limit_time") != _first_limit_time(first_limit_ts)
        ):
            raise ValueError(f"同花顺炸板池首次触板时间异常: {path} {code}")
        open_count = row.get("open_count")
        if open_count is not None and (
            isinstance(open_count, bool) or not isinstance(open_count, int) or open_count < 1
        ):
            raise ValueError(f"同花顺炸板池开板次数异常: {path} {code}")
        if row.get("change_tag") is not None and (
            not isinstance(row["change_tag"], str) or not row["change_tag"]
        ):
            raise ValueError(f"同花顺炸板池状态异常: {path} {code}")
        if row.get("is_again_limit") is not None and row["is_again_limit"] not in (0, 1):
            raise ValueError(f"同花顺炸板池回封标记异常: {path} {code}")


def load_day(
    day: str,
    *,
    fetch_missing: bool = False,
    force: bool = False,
) -> dict[str, Any] | None:
    day = date.fromisoformat(day).isoformat()
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


def _manifest_days(path: Path) -> list[str]:
    payload = _read_json(path)
    if payload.get("publication_ready") is not True:
        raise ValueError(f"正式 manifest 尚未 ready: {path}")
    raw_days = payload.get("available_dates")
    if not isinstance(raw_days, list) or not raw_days:
        raise ValueError(f"正式 manifest 缺少 available_dates: {path}")
    days = [date.fromisoformat(str(day)).isoformat() for day in raw_days]
    if days != sorted(set(days)):
        raise ValueError(f"正式 manifest 日期乱序或重复: {path}")
    return days


def _selected_days(args: argparse.Namespace) -> list[str]:
    selected = {date.fromisoformat(day).isoformat() for day in args.dates}
    if args.manifest is not None:
        selected.update(_manifest_days(args.manifest))
    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("--start 与 --end 必须同时提供")
        start = date.fromisoformat(args.start).isoformat()
        end = date.fromisoformat(args.end).isoformat()
        if start > end:
            raise ValueError("--start 不能晚于 --end")
        source_days = KAIPANLA_RAW_DIR.iterdir() if KAIPANLA_RAW_DIR.exists() else ()
        for path in source_days:
            if path.is_dir() and DAY_RE.fullmatch(path.name) and start <= path.name <= end:
                selected.add(path.name)
    if not selected:
        raise ValueError("请提供交易日、--manifest，或同时提供 --start/--end")
    return sorted(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="*", help="交易日 YYYY-MM-DD")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--interval", type=float, default=0.25)
    args = parser.parse_args(argv)
    if args.interval < 0:
        raise ValueError("--interval 不能为负数")

    days = _selected_days(args)
    written = 0
    checked = 0
    for index, day in enumerate(days):
        path = output_path(day)
        existed = path.exists()
        payload = load_day(day, fetch_missing=True, force=args.force)
        assert payload is not None
        fetched = args.force or not existed
        if fetched:
            written += 1
        else:
            checked += 1
        completed = index + 1
        if completed == 1 or completed == len(days) or completed % 25 == 0:
            print(
                f"PROGRESS {completed}/{len(days)} day={day} "
                f"stocks={payload['count']} written={written} checked={checked}"
            )
        if completed < len(days) and fetched:
            time.sleep(args.interval)
    print(f"DONE days={len(days)} written={written} checked={checked} -> {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
