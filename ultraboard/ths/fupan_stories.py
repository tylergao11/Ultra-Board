# -*- coding: utf-8 -*-
"""采集同花顺官方复盘叙事与逐股涨停原因。

日级叙事来自同花顺历史复盘页；逐股故事来自同花顺涨停池显式请求的
``reason_type`` 原文。两者只描述市场传播，不参与开盘啦题材归因。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from ultraboard.kaipanla import load_day as load_kaipanla_day
from ultraboard.ths.limit_pool import ENDPOINT as LIMIT_UP_ENDPOINT
from ultraboard.ths.limit_pool import load_day as load_limit_day
from ultraboard.ths.stories import AUTO_SOURCE, load_day as load_story_day
from ultraboard.ths.stories import validate_payload as validate_story_payload


ROOT = Path(__file__).resolve().parents[2]
STORY_DIR = ROOT / "data" / "ths" / "stories"
FUPAN_LATEST_URL = "https://stock.10jqka.com.cn/fupan/"
FUPAN_DAY_URL = "https://stock.10jqka.com.cn/fupan/{compact}.shtml"
CN_TZ = timezone(timedelta(hours=8))
DATE_ASSIGNMENT_RE = re.compile(r'Global\.date\s*=\s*"(\d{8})"')
TARGET_BLOCKS = frozenset({"block_1890", "block_1891"})


def _session() -> requests.Session:
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
            "Accept": "text/html,application/json,text/plain,*/*",
            "Referer": "https://stock.10jqka.com.cn/fupan/",
        }
    )
    return session


class _BlockParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: dict[str, list[str]] = {key: [] for key in TARGET_BLOCKS}
        self.occurrences: dict[str, int] = {key: 0 for key in TARGET_BLOCKS}
        self._active: str | None = None
        self._depth = 0

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._active is not None:
            self._depth += 1
            return
        attributes = dict(attrs)
        block_id = attributes.get("id")
        if block_id in TARGET_BLOCKS:
            self.occurrences[block_id] += 1
            self._active = block_id
            self._depth = 1

    def handle_endtag(self, tag: str) -> None:
        if self._active is None:
            return
        self._depth -= 1
        if self._depth == 0:
            self._active = None

    def handle_data(self, data: str) -> None:
        if self._active is not None:
            self.blocks[self._active].append(data)


def _compact_text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


def _page_date(body: str, label: str) -> str:
    matches = DATE_ASSIGNMENT_RE.findall(body)
    if not matches:
        raise RuntimeError(f"同花顺复盘页缺少 Global.date: {label}")
    compact = matches[-1]
    return date.fromisoformat(
        f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
    ).isoformat()


def latest_available_day() -> str:
    """返回同花顺官方复盘页已经公开的最新交易日。"""
    session = _session()
    response = session.get(FUPAN_LATEST_URL, timeout=20)
    response.raise_for_status()
    body = response.content.decode("gb18030", errors="strict")
    return _page_date(body, FUPAN_LATEST_URL)


def _fetch_fupan(day: str) -> dict[str, Any]:
    compact = day.replace("-", "")
    url = FUPAN_DAY_URL.format(compact=compact)
    session = _session()
    response = session.get(url, timeout=20)
    response.raise_for_status()
    raw = response.content
    body = raw.decode("gb18030", errors="strict")
    assignments = DATE_ASSIGNMENT_RE.findall(body)
    actual_day = _page_date(body, url)
    if actual_day != day:
        raise RuntimeError(
            f"同花顺复盘页日期不一致: requested={day}, actual={actual_day}"
        )

    parser = _BlockParser()
    parser.feed(body)
    if any(parser.occurrences[key] != 1 for key in TARGET_BLOCKS):
        raise RuntimeError(
            f"同花顺复盘页目标区块数量异常: {url} {parser.occurrences}"
        )
    main_points = _compact_text(parser.blocks["block_1890"])
    market_narrative = _compact_text(parser.blocks["block_1891"])
    if not main_points or not market_narrative:
        raise RuntimeError(f"同花顺复盘页缺少主流看点或盘面脉络: {url}")
    return {
        "url": url,
        "page_date": actual_day,
        "global_date_assignments": assignments,
        "charset": "gb18030",
        "response_sha256": f"sha256:{hashlib.sha256(raw).hexdigest()}",
        "main_points": main_points,
        "market_narrative": market_narrative,
    }


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else ""


def _normalized_name(value: Any) -> str:
    """Normalize presentation-width variants before cross-source name checks."""
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _fetch_reason_rows(day: str) -> tuple[list[dict[str, Any]], str, str]:
    fetched_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
    session = _session()
    rows: list[dict[str, Any]] = []
    response_digest = hashlib.sha256()
    expected_total: int | None = None
    page_number = 1
    while True:
        response = session.get(
            LIMIT_UP_ENDPOINT,
            params={
                "page": page_number,
                "limit": 200,
                "field": "reason_type",
                "filter": "HS,GEM2STAR",
                "order_field": "last_limit_up_time",
                "order_type": 0,
                "date": day.replace("-", ""),
            },
            headers={"Referer": "https://data.10jqka.com.cn/"},
            timeout=20,
        )
        response.raise_for_status()
        response_digest.update(str(page_number).encode("ascii"))
        response_digest.update(b"\0")
        response_digest.update(response.content)
        response_digest.update(b"\0")
        body = response.json()
        if body.get("status_code") != 0:
            raise RuntimeError(
                f"同花顺逐股故事返回失败: {body.get('status_code')}"
            )
        data = body.get("data") or {}
        page_rows = data.get("info") or []
        page = data.get("page") or {}
        try:
            total = int(page.get("total"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("同花顺逐股故事缺少合法 total") from exc
        if not isinstance(page_rows, list) or total < 0:
            raise RuntimeError("同花顺逐股故事响应结构异常")
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise RuntimeError(
                f"同花顺逐股故事分页 total 变化: {expected_total} -> {total}"
            )
        rows.extend(page_rows)
        if len(rows) >= total:
            break
        page_number += 1
        if page_number > math.ceil(total / 200):
            raise RuntimeError(
                f"同花顺逐股故事未完整取回: total={total}, rows={len(rows)}"
            )
    if expected_total is None or len(rows) != expected_total:
        raise RuntimeError(
            f"同花顺逐股故事未完整取回: total={expected_total}, rows={len(rows)}"
        )
    return rows, fetched_at, f"sha256:{response_digest.hexdigest()}"


def fetch_day(day_value: str) -> dict[str, Any]:
    """构建一个自动故事合同；不拆分 ``reason_type``，不生成题材。"""
    day = date.fromisoformat(day_value).isoformat()
    page = _fetch_fupan(day)
    raw_rows, reasons_fetched_at, reasons_response_sha256 = _fetch_reason_rows(day)

    kaipanla = load_kaipanla_day(day)
    limit_pool = load_limit_day(day)
    if limit_pool is None:
        raise FileNotFoundError(f"同花顺涨停池不存在: {day}")
    kpl_by_code = {_code(row.get("code")): row for row in kaipanla["stocks"]}
    limit_by_code = {_code(row.get("code")): row for row in limit_pool["stocks"]}
    reason_by_code = {_code(row.get("code")): row for row in raw_rows}
    if "" in kpl_by_code or "" in limit_by_code or "" in reason_by_code:
        raise RuntimeError(f"{day} 故事来源存在非法股票代码")
    if len(reason_by_code) != len(raw_rows):
        raise RuntimeError(f"{day} 同花顺逐股故事股票代码重复")
    if not (set(kpl_by_code) == set(limit_by_code) == set(reason_by_code)):
        raise RuntimeError(
            f"{day} 正式股票集合未闭合: "
            f"kpl={len(kpl_by_code)}, limit={len(limit_by_code)}, "
            f"reason={len(reason_by_code)}"
        )

    stocks: list[dict[str, Any]] = []
    for position, raw in enumerate(raw_rows, 1):
        code = _code(raw.get("code"))
        name = str(raw.get("name") or "").strip()
        story = str(raw.get("reason_type") or "").strip()
        expected_name = str(limit_by_code[code].get("name") or "").strip()
        kpl_name = str(kpl_by_code[code].get("name") or "").strip()
        normalized_name = _normalized_name(name)
        if (
            not normalized_name
            or normalized_name != _normalized_name(expected_name)
            or normalized_name != _normalized_name(kpl_name)
        ):
            raise RuntimeError(
                f"{day} {code} 故事名码不一致: "
                f"reason={name!r}, limit={expected_name!r}, kpl={kpl_name!r}"
            )
        if not story:
            raise RuntimeError(f"{day} {code} 同花顺 reason_type 为空")
        stocks.append(
            {
                "stock_position": position,
                "code": code,
                "name": name,
                "story": story,
                "story_source": "tonghuashun_limit_up_reason_type",
                "mapping_status": "matched_same_day_stock",
            }
        )

    fetched_at = datetime.now(CN_TZ).isoformat(timespec="seconds")
    return {
        "schema_version": 2,
        "date": day,
        "source": AUTO_SOURCE,
        "source_url": page["url"],
        "source_fetched_at": fetched_at,
        "source_components": {
            "day_story": {
                "provider": "tonghuashun_fupan",
                "url": page["url"],
                "page_date": page["page_date"],
                "global_date_assignments": page["global_date_assignments"],
                "charset": page["charset"],
                "response_sha256": page["response_sha256"],
                "source_blocks": ["block_1890", "block_1891"],
                "availability": "post_close_recap_public_time_unverified",
            },
            "stock_story": {
                "provider": "tonghuashun_limit_up_reason_type",
                "endpoint": LIMIT_UP_ENDPOINT,
                "field": "reason_type",
                "query": {
                    "date": day.replace("-", ""),
                    "filter": "HS,GEM2STAR",
                    "limit": 200,
                },
                "fetched_at": reasons_fetched_at,
                "response_sha256": reasons_response_sha256,
                "availability": "fetched_after_close_may_be_revised",
            },
        },
        "story_contract": (
            "复盘页只提供日级市场叙事，reason_type 原文只提供逐股市场故事；"
            "两者均不参与开盘啦 theme/themes 归因，也不证明盘中公开时间"
        ),
        "market_story": {
            "focus": page["main_points"],
            "headline": f"盘面主流看点：{page['main_points']}",
            "narrative": page["market_narrative"],
        },
        "stock_stories": stocks,
        "coverage": {
            "source_total": len(raw_rows),
            "stock_story_count": len(stocks),
            "missing_codes": [],
            "extra_codes": [],
            "complete": True,
        },
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


def ensure_day(day_value: str, *, refresh: bool = False) -> tuple[dict[str, Any], str]:
    """保留已核对故事；只自动创建缺失日或刷新同一自动来源。"""
    day = date.fromisoformat(day_value).isoformat()
    path = STORY_DIR / f"{day}.json"
    if path.exists():
        existing = load_story_day(day)
        if existing.get("source") != AUTO_SOURCE or not refresh:
            return existing, "checked"
    payload = fetch_day(day)
    validate_story_payload(payload, day, path)
    _write_json_atomic(path, payload)
    return load_story_day(day), "written"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", help="YYYY-MM-DD")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="刷新同一自动来源；人工核对文件仍保留",
    )
    args = parser.parse_args(argv)
    payload, action = ensure_day(args.day, refresh=args.refresh)
    story_count = len(payload.get("stories") or [])
    stock_story_count = len(payload.get("stock_stories") or [])
    print(
        f"{action.upper()} {payload['date']} source={payload['source']} "
        f"market_stories={story_count or int(bool(payload.get('market_story')))} "
        f"stock_stories={stock_story_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
