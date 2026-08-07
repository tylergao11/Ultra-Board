# -*- coding: utf-8 -*-
"""同花顺当日故事的只读合同。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STORY_DIR = ROOT / "data" / "ths" / "stories"
SOURCE = "tonghuashun_strong_wind_headlines"


def load_day(value: str) -> dict[str, Any]:
    """读取标题后半句故事；不返回个股题材分类。"""
    day = date.fromisoformat(value).isoformat()
    path = STORY_DIR / f"{day}.json"
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    stories = payload.get("stories")
    if (
        payload.get("date") != day
        or payload.get("source") != SOURCE
        or not isinstance(stories, list)
        or not stories
    ):
        raise ValueError(f"同花顺故事合同异常: {path}")
    for expected_position, item in enumerate(stories, 1):
        if (
            not isinstance(item, dict)
            or item.get("source_position") != expected_position
            or not str(item.get("story") or "").strip()
            or not str(item.get("headline") or "").strip()
        ):
            raise ValueError(f"同花顺故事记录异常: {path} #{expected_position}")
    return payload
