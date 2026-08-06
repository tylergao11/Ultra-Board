# -*- coding: utf-8 -*-
"""梯队列表 theme 的公告／自然分类合同。

公告型 theme 只从 ``data/kaipanla/announcement_taxonomy.json`` 加载。身份只看
当前最高板日的梯队 theme；断板时即看断板前一交易日，不继承更早身份。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_PATH = ROOT / "data" / "kaipanla" / "announcement_taxonomy.json"


@lru_cache(maxsize=1)
def load_taxonomy() -> dict[str, Any]:
    payload = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"不支持的公告分类表版本: {TAXONOMY_PATH}")
    if not payload.get("exact_themes") or not payload.get("sector_codes"):
        raise ValueError(f"公告分类表缺少主题或板块代码: {TAXONOMY_PATH}")
    return payload


ANNOUNCEMENT_TYPES = frozenset(
    str(theme).strip()
    for theme in load_taxonomy()["exact_themes"]
    if str(theme).strip()
)
ANNOUNCEMENT_SECTOR_CODES = {
    str(code).strip(): str(theme).strip()
    for code, theme in load_taxonomy()["sector_codes"].items()
}
ANNOUNCEMENT_THEME_PREFIXES = tuple(
    str(prefix).strip()
    for prefix in load_taxonomy().get("theme_prefixes") or []
    if str(prefix).strip()
)


def announcement_type_of(theme: Any, sector_code: Any = None) -> str | None:
    """按唯一分类表识别公告型梯队 theme；其他 theme 返回 ``None``。"""
    text = str(theme or "").strip()
    normalized_code = str(sector_code or "").strip()
    if normalized_code in ANNOUNCEMENT_SECTOR_CODES:
        return text or ANNOUNCEMENT_SECTOR_CODES[normalized_code]
    normalized_text = text.removesuffix("[公告板]").removesuffix("概念")
    if normalized_text in ANNOUNCEMENT_TYPES:
        return normalized_text
    if any(normalized_text.startswith(prefix) for prefix in ANNOUNCEMENT_THEME_PREFIXES):
        return normalized_text
    return None


def is_announcement_theme(theme: Any, sector_code: Any = None) -> bool:
    return announcement_type_of(theme, sector_code) is not None


def resolve_identity(
    *,
    day: str,
    theme: Any,
    sector_code: Any = None,
) -> dict[str, Any]:
    """只按 ``day`` 当天梯队 theme 分类；更早交易日身份不继承。"""
    theme_text = str(theme or "").strip()
    direct_type = announcement_type_of(theme, sector_code)
    if not direct_type:
        return {
            "is_announcement": False,
            "announcement_type": None,
            "announcement_origin_date": None,
            "announcement_source": None,
            "natural_theme": theme_text or None,
            "natural_theme_date": day if theme_text else None,
            "effective_theme": theme_text,
        }

    return {
        "is_announcement": True,
        "announcement_type": direct_type,
        "announcement_origin_date": day,
        "announcement_source": "same_day_ladder_theme",
        "natural_theme": None,
        "natural_theme_date": None,
        "effective_theme": theme_text,
    }
