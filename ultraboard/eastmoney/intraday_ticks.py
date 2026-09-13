# -*- coding: utf-8 -*-
"""采集最近交易日涨停与炸板股票的秒级分时样本。

东方财富公开分时成交端点只返回最近交易日。本模块先用同花顺分时日期校验
目标日，再保存源端点约三秒一条的原始样本和触板/离板转换。转换只描述价
格事实，不自动判断两只股票之间的资金因果。

用法：

  python -m ultraboard.eastmoney.intraday_ticks 2026-09-04
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

from ultraboard.ths.stock_profiles import latest_market_day


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "data" / "eastmoney" / "intraday_ticks"
ENDPOINT = "https://push2ex.eastmoney.com/getStockFenShi"
TOKEN = "7eea3edcaed734bea9cbfc24409ed989"
CN_TZ = timezone(timedelta(hours=8))
SAMPLE_FIELDS = ("time_hhmmss", "price_x1000", "volume_lots", "side_code")


def output_path(day: str) -> Path:
    return OUTPUT_DIR / f"{day}.json"


def _new_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.proxies = {"http": "", "https": ""}
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://quote.eastmoney.com/",
        }
    )
    return session


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else ""


def _name_key(value: Any) -> str:
    # 东方财富会把“深华发A”写成全角“深华发Ａ”，比较前统一到 NFKC 半角形式
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split())


_EX_RIGHTS_PREFIXES = ("XD", "XR", "DR")


def _names_match(expected: Any, returned: Any) -> bool:
    left = _name_key(expected)
    right = _name_key(returned)
    if left == right:
        return True
    # 除权除息日东方财富返回“XD剑桥科”这类带前缀且截短的名称
    for prefix in _EX_RIGHTS_PREFIXES:
        if right.startswith(prefix):
            stem = right[len(prefix):]
            return bool(stem) and left.startswith(stem)
    return False


def _market(code: str) -> int:
    if code.startswith(("5", "6", "9")):
        return 1
    if code.startswith(("0", "1", "2", "3")):
        return 0
    raise ValueError(f"无法判断东方财富市场: {code}")


def _load_universe(day: str) -> list[dict[str, str]]:
    from ultraboard.ths.stock_profiles import load_day as load_profile_day

    profile = load_profile_day(day)
    if profile is None:
        raise FileNotFoundError(f"缺少同花顺完整概念与地域快照: {day}")
    return [
        {"code": str(row["code"]), "name": str(row["name"])}
        for row in profile["stocks"]
    ]


def _time_text(value: int) -> str:
    text = str(value).zfill(6)
    return f"{text[:2]}:{text[2:4]}:{text[4:]}"


def _limit_transitions(
    samples: list[list[int | float]], limit_price: int
) -> list[dict[str, Any]]:
    continuous = [row for row in samples if row[0] >= 93000]
    if not continuous:
        return []
    result: list[dict[str, Any]] = []
    at_limit: bool | None = None
    for sample in continuous:
        now_at_limit = sample[1] == limit_price
        if at_limit is None:
            at_limit = now_at_limit
            if now_at_limit:
                result.append(
                    {
                        "time": _time_text(sample[0]),
                        "time_hhmmss": sample[0],
                        "event": "continuous_session_starts_at_limit",
                        "price_x1000": sample[1],
                    }
                )
            continue
        if now_at_limit == at_limit:
            continue
        result.append(
            {
                "time": _time_text(sample[0]),
                "time_hhmmss": sample[0],
                "event": "touch_limit" if now_at_limit else "leave_limit",
                "price_x1000": sample[1],
            }
        )
        at_limit = now_at_limit
    return result


def _fetch_stock(stock: dict[str, str]) -> dict[str, Any]:
    code = stock["code"]
    market = _market(code)
    params = {
        "pagesize": 10000,
        "ut": TOKEN,
        "dpt": "wzfscj",
        "pageindex": 0,
        "id": f"{code}{market}",
        "sort": 1,
        "ft": 1,
        "code": code,
        "market": market,
    }
    response = _new_session().get(ENDPOINT, params=params, timeout=20)
    response.raise_for_status()
    body = response.json()
    data = body.get("data")
    if body.get("rc") != 0 or not isinstance(data, dict):
        raise RuntimeError(f"东方财富分时接口异常: {code}")
    returned_code = _code(data.get("c"))
    returned_name = str(data.get("n") or "").strip()
    if returned_code != code or not _names_match(stock["name"], returned_name):
        raise RuntimeError(
            f"东方财富分时名码不一致: {code} {stock['name']!r} "
            f"returned={returned_code} {returned_name!r}"
        )
    previous_close = data.get("cp")
    raw_samples = data.get("data")
    if (
        isinstance(previous_close, bool)
        or not isinstance(previous_close, int)
        or previous_close <= 0
        or not isinstance(raw_samples, list)
        or not raw_samples
    ):
        raise RuntimeError(f"东方财富分时核心字段异常: {code}")

    samples: list[list[int | float]] = []
    prior_time = -1
    for item in raw_samples:
        if not isinstance(item, dict):
            raise RuntimeError(f"东方财富分时样本不是对象: {code}")
        time_value = item.get("t")
        price_value = item.get("p")
        volume_value = item.get("v")
        side_value = item.get("bs")
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int)
                for value in (time_value, price_value, side_value)
            )
            or isinstance(volume_value, bool)
            or not isinstance(volume_value, (int, float))
        ):
            values = [time_value, price_value, volume_value, side_value]
            raise RuntimeError(f"东方财富分时样本字段异常: {code} {values!r}")
        values = [time_value, price_value, volume_value, side_value]
        if values[0] < prior_time:
            raise RuntimeError(f"东方财富分时样本时间乱序: {code}")
        if values[1] <= 0 or values[2] < 0:
            raise RuntimeError(f"东方财富分时价格或成交量异常: {code}")
        prior_time = values[0]
        samples.append(values)

    continuous_prices = [row[1] for row in samples if row[0] >= 93000]
    if not continuous_prices:
        raise RuntimeError(f"东方财富分时缺少连续竞价样本: {code}")
    limit_price = max(continuous_prices)
    transitions = _limit_transitions(samples, limit_price)
    return {
        "code": code,
        "name": stock["name"],
        "market": market,
        "previous_close_x1000": previous_close,
        "limit_price_x1000": limit_price,
        "source_total_count": data.get("tc"),
        "sample_count": len(samples),
        "samples": samples,
        "limit_transitions": transitions,
    }


def fetch_day(day_value: str, *, workers: int = 8) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    if workers < 1 or workers > 12:
        raise ValueError("workers 必须在 1 到 12 之间")
    universe = _load_universe(day)
    if not universe:
        raise RuntimeError(f"{day} 分时抓取股票集合为空")
    source_latest_day = latest_market_day(universe[0]["code"])
    if source_latest_day != day:
        raise RuntimeError(
            "东方财富秒级分时只返回最近交易日，禁止历史错配: "
            f"requested={day}, source_latest={source_latest_day}"
        )

    with ThreadPoolExecutor(max_workers=workers) as executor:
        stocks = list(executor.map(_fetch_stock, universe))
    stocks.sort(key=lambda row: row["code"])
    fetched_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
    payload = {
        "schema_version": 1,
        "date": day,
        "information_cutoff": fetched_at,
        "source": {
            "provider": "eastmoney_recent_intraday_transactions",
            "endpoint": ENDPOINT,
            "fetched_at": fetched_at,
            "source_latest_market_day": source_latest_day,
            "sample_fields": list(SAMPLE_FIELDS),
            "price_scale": 1000,
            "temporal_contract": (
                "源端点只返回最近交易日；采集前用同花顺 last 分时日期校验。"
                "约三秒一条的源样本可定位成交价离开/回到涨停，但不能单独证明个股间因果"
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
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def validate_payload(payload: dict[str, Any], day: str, path: Path) -> None:
    source = payload.get("source") or {}
    rows = payload.get("stocks")
    if (
        payload.get("schema_version") != 1
        or payload.get("date") != day
        or source.get("provider") != "eastmoney_recent_intraday_transactions"
        or source.get("source_latest_market_day") != day
        or source.get("sample_fields") != list(SAMPLE_FIELDS)
        or source.get("price_scale") != 1000
        or not isinstance(rows, list)
        or payload.get("count") != len(rows)
    ):
        raise ValueError(f"东方财富秒级分时合同异常: {path}")
    datetime.fromisoformat(str(payload.get("information_cutoff") or ""))
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"东方财富分时股票行不是对象: {path}")
        code = _code(row.get("code"))
        samples = row.get("samples")
        if not code or code in seen or row.get("code") != code:
            raise ValueError(f"东方财富分时代码异常或重复: {path} {code!r}")
        seen.add(code)
        if not isinstance(samples, list) or row.get("sample_count") != len(samples):
            raise ValueError(f"东方财富分时样本数量不闭合: {path} {code}")
        prior_time = -1
        for sample in samples:
            if (
                not isinstance(sample, list)
                or len(sample) != len(SAMPLE_FIELDS)
                or any(
                    isinstance(value, bool) or not isinstance(value, int)
                    for value in (sample[0], sample[1], sample[3])
                )
                or isinstance(sample[2], bool)
                or not isinstance(sample[2], (int, float))
                or sample[0] < prior_time
                or sample[1] <= 0
                or sample[2] < 0
            ):
                raise ValueError(f"东方财富分时样本异常: {path} {code}")
            prior_time = sample[0]
        if row.get("limit_transitions") != _limit_transitions(
            samples, row.get("limit_price_x1000")
        ):
            raise ValueError(f"东方财富涨停转换不闭合: {path} {code}")


def load_day(
    day_value: str,
    *,
    fetch_missing: bool = False,
    force: bool = False,
    workers: int = 8,
) -> dict[str, Any] | None:
    day = date.fromisoformat(day_value).isoformat()
    path = output_path(day)
    if path.exists() and not force:
        payload = _read_json(path)
    elif fetch_missing or force:
        payload = fetch_day(day, workers=workers)
        _write_json_atomic(path, payload)
    else:
        return None
    validate_payload(payload, day, path)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("date", help="接口当前最后交易日 YYYY-MM-DD")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args(argv)
    day = date.fromisoformat(args.date).isoformat()
    existed = output_path(day).exists()
    payload = load_day(
        day,
        fetch_missing=True,
        force=args.force,
        workers=args.workers,
    )
    assert payload is not None
    print(
        f"{'WROTE' if args.force or not existed else 'CHECKED'} {day} "
        f"stocks={payload['count']} -> {output_path(day)}"
    )
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
