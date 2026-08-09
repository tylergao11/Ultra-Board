# -*- coding: utf-8 -*-
"""同花顺当日故事的只读合同。"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STORY_DIR = ROOT / "data" / "ths" / "stories"
MANUAL_SOURCE = "tonghuashun_strong_wind_headlines"
AUTO_SOURCE = "tonghuashun_fupan_and_limit_up_reasons"
SOURCES = frozenset({MANUAL_SOURCE, AUTO_SOURCE})
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def validate_payload(payload: dict[str, Any], day: str, path: Path) -> None:
    """校验 canonical 故事合同，不做题材解释。"""
    source = payload.get("source")
    if payload.get("date") != day or source not in SOURCES:
        raise ValueError(f"同花顺故事合同异常: {path}")
    if source == MANUAL_SOURCE:
        stories = payload.get("stories")
        if not isinstance(stories, list) or not stories:
            raise ValueError(f"同花顺故事合同异常: {path}")
        for expected_position, item in enumerate(stories, 1):
            if (
                not isinstance(item, dict)
                or item.get("source_position") != expected_position
                or not str(item.get("story") or "").strip()
                or not str(item.get("headline") or "").strip()
            ):
                raise ValueError(
                    f"同花顺故事记录异常: {path} #{expected_position}"
                )
        source_image = str(payload.get("source_image") or "").strip()
        if not source_image or not (ROOT / source_image).exists():
            raise ValueError(f"同花顺故事原图不存在: {path}")
    else:
        components = payload.get("source_components")
        day_story = components.get("day_story") if isinstance(components, dict) else None
        stock_story = components.get("stock_story") if isinstance(components, dict) else None
        market_story = payload.get("market_story")
        stock_stories = payload.get("stock_stories")
        coverage = payload.get("coverage")
        compact = day.replace("-", "")
        if (
            payload.get("schema_version") != 2
            or not str(payload.get("source_url") or "").strip()
            or not str(payload.get("source_fetched_at") or "").strip()
            or not isinstance(components, dict)
            or not isinstance(day_story, dict)
            or day_story.get("provider") != "tonghuashun_fupan"
            or day_story.get("page_date") != day
            or not str(day_story.get("url") or "").endswith(f"/{compact}.shtml")
            or not isinstance(day_story.get("global_date_assignments"), list)
            or not day_story.get("global_date_assignments")
            or day_story["global_date_assignments"][-1] != compact
            or day_story.get("source_blocks") != ["block_1890", "block_1891"]
            or not SHA256_RE.fullmatch(str(day_story.get("response_sha256") or ""))
            or not isinstance(stock_story, dict)
            or stock_story.get("provider") != "tonghuashun_limit_up_reason_type"
            or stock_story.get("field") != "reason_type"
            or (stock_story.get("query") or {}).get("date") != compact
            or not SHA256_RE.fullmatch(str(stock_story.get("response_sha256") or ""))
            or not isinstance(market_story, dict)
            or not str(market_story.get("focus") or "").strip()
            or not str(market_story.get("headline") or "").strip()
            or not str(market_story.get("narrative") or "").strip()
            or not isinstance(stock_stories, list)
            or not stock_stories
            or not isinstance(coverage, dict)
            or coverage.get("source_total") != len(stock_stories)
            or coverage.get("stock_story_count") != len(stock_stories)
            or coverage.get("missing_codes") != []
            or coverage.get("extra_codes") != []
            or coverage.get("complete") is not True
        ):
            raise ValueError(f"同花顺自动故事来源合同异常: {path}")
        seen: set[str] = set()
        for expected_position, item in enumerate(stock_stories, 1):
            code = str(item.get("code") or "").zfill(6) if isinstance(item, dict) else ""
            if (
                not isinstance(item, dict)
                or item.get("stock_position") != expected_position
                or not code.isdigit()
                or len(code) != 6
                or code in seen
                or not str(item.get("name") or "").strip()
                or not str(item.get("story") or "").strip()
                or item.get("story_source") != "tonghuashun_limit_up_reason_type"
                or item.get("mapping_status") != "matched_same_day_stock"
            ):
                raise ValueError(
                    f"同花顺自动个股故事记录异常: {path} #{expected_position}"
                )
            seen.add(code)
    return None


def load_day(value: str) -> dict[str, Any]:
    """读取同花顺市场故事；不返回个股题材分类。"""
    day = date.fromisoformat(value).isoformat()
    path = STORY_DIR / f"{day}.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"同花顺故事顶层不是对象: {path}")
    validate_payload(payload, day, path)
    return payload
