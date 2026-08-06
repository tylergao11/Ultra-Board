# -*- coding: utf-8 -*-
"""同花顺历史涨停池的板上行为事实层。

只采集日内行为字段：首封、终封和炸板次数。题材唯一真相来自
``data/ths/strong_wind``；接口 reason_type 不进入题材判断。

用法：

  python -m ultraboard.kaipanla.ths_limit_pool 2025-12-16
  python -m ultraboard.kaipanla.ths_limit_pool 2025-12-16 --force
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
ENDPOINT = "https://data.10jqka.com.cn/dataapi/limit_up/limit_up_pool"
CN_TZ = timezone(timedelta(hours=8))
REQUEST_FIELDS = (
    "first_limit_up_time",
    "last_limit_up_time",
    "open_num",
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
    return RAW_DIR / day / "ths_limit_pool.json"


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _code(value: Any) -> str:
    return str(value or "").strip().zfill(6)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def fetch_day(day: str) -> dict[str, Any]:
    datetime.strptime(day, "%Y-%m-%d")
    params = {
        "page": 1,
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
    if total is not None and total != len(rows):
        raise RuntimeError(
            f"同花顺涨停池未完整取回：total={total}, rows={len(rows)}"
        )

    stocks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raise RuntimeError("同花顺涨停池出现非对象股票行")
        code = _code(raw.get("code"))
        if not code.strip("0") or code in seen:
            raise RuntimeError(f"同花顺涨停池代码异常或重复: {code}")
        seen.add(code)
        first_ts = _as_int(raw.get("first_limit_up_time"))
        final_ts = _as_int(raw.get("last_limit_up_time"))
        if first_ts is not None and final_ts is not None and final_ts < first_ts:
            raise RuntimeError(f"{code} 终封时间早于首封时间")
        # open_num 在官方响应中以 null 表示 0 次；字段缺失或非法则直接失败，
        # 不能把上游结构变化伪装成 0 次炸板。
        if "open_num" not in raw:
            raise RuntimeError(f"{code} 缺少显式请求的 open_num")
        raw_open_count = raw.get("open_num")
        open_count = 0 if raw_open_count in (None, "") else _as_int(raw_open_count)
        if open_count is None or open_count < 0:
            raise RuntimeError(f"{code} open_num 非法: {raw_open_count!r}")
        stocks.append({
            "code": code,
            "name": str(raw.get("name") or ""),
            "first_limit_ts": first_ts,
            "final_limit_ts": final_ts,
            "open_count": open_count,
        })
    stocks.sort(key=lambda row: row["code"])
    return {
        "date": day,
        "source": {
            "provider": "同花顺涨停揭秘",
            "endpoint": ENDPOINT,
            "fetched_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
            "query": params,
            "theme_contract": "请求不含 reason_type；题材只认 data/ths/strong_wind",
        },
        "count": len(stocks),
        "stocks": stocks,
    }


def load_day(
    day: str,
    *,
    fetch_missing: bool = False,
    force: bool = False,
) -> dict[str, Any] | None:
    path = output_path(day)
    if path.exists() and not force:
        payload = _read_json(path)
    elif fetch_missing or force:
        payload = fetch_day(day)
        _write_json_atomic(path, payload)
    else:
        return None
    if payload.get("date") != day:
        raise RuntimeError(f"同花顺日文件日期错位: {path}")
    stocks = payload.get("stocks")
    if not isinstance(stocks, list) or payload.get("count") != len(stocks):
        raise RuntimeError(f"同花顺日文件未对账: {path}")
    return payload


def stock_map(
    day: str,
    *,
    fetch_missing: bool = False,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    payload = load_day(day, fetch_missing=fetch_missing, force=force)
    if payload is None:
        return {}
    return {_code(row.get("code")): row for row in payload["stocks"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dates", nargs="+", help="交易日 YYYY-MM-DD")
    parser.add_argument("--force", action="store_true", help="重新抓取并覆盖同源日文件")
    args = parser.parse_args(argv)
    for day in args.dates:
        payload = load_day(day, fetch_missing=True, force=args.force)
        assert payload is not None
        print(f"{day}: 同花顺涨停池 {payload['count']} 只 -> {output_path(day)}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
