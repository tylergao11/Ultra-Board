# -*- coding: utf-8 -*-
"""公告起源的唯一分类合同。

算法只识别三类公告：并购重组、实控人变更、股权转让。原始主属性一旦在
连续连板段中命中公告，后续即使 theme 漂移也保持公告起源。源数据漏标只允许
通过 ``data/kaipanla/announcement_overrides.json`` 修正，禁止在算法中按股票名
或节点日期写特判。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
OVERRIDE_PATH = ROOT / "data" / "kaipanla" / "announcement_overrides.json"

ANNOUNCEMENT_TYPES = frozenset({
    "并购重组",
    "实控人变更",
    "股权转让",
})


def code_of(value: Any) -> str:
    return str(value or "").zfill(6)


def announcement_type_of(theme: Any) -> str | None:
    """把开盘啦主属性归一到三种公告类型；其他属性一律返回 ``None``。"""
    text = str(theme or "").strip()
    if not text:
        return None
    for announcement_type in ANNOUNCEMENT_TYPES:
        if text in {
            announcement_type,
            f"{announcement_type}概念",
            f"{announcement_type}[公告板]",
        }:
            return announcement_type
    return None


def is_announcement_theme(theme: Any) -> bool:
    return announcement_type_of(theme) is not None


@lru_cache(maxsize=1)
def load_overrides() -> tuple[dict[str, Any], ...]:
    if not OVERRIDE_PATH.exists():
        return ()
    payload = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"不支持的公告覆盖表版本: {OVERRIDE_PATH}")

    rows: list[dict[str, Any]] = []
    for raw in payload.get("events") or []:
        row = dict(raw)
        row["code"] = code_of(row.get("code"))
        announcement_type = str(row.get("announcement_type") or "")
        if announcement_type not in ANNOUNCEMENT_TYPES:
            raise ValueError(
                f"公告覆盖类型不在三类合同中: {row.get('name')} {announcement_type}"
            )
        start_date = str(row.get("start_date") or "")
        end_date = str(row.get("end_date") or "")
        if not start_date or not end_date or start_date > end_date:
            raise ValueError(f"公告覆盖日期非法: {row}")
        rows.append(row)
    return tuple(rows)


def override_for(code: Any, day: str) -> dict[str, Any] | None:
    normalized = code_of(code)
    for row in load_overrides():
        if (
            row["code"] == normalized
            and row["start_date"] <= day <= row["end_date"]
        ):
            return dict(row)
    return None


def resolve_identity(
    *,
    code: Any,
    day: str,
    theme: Any,
    boards: int,
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    """解析当日公告起源，``previous`` 只能是上一交易日同股记录。"""
    override = override_for(code, day)
    if override:
        return {
            "is_announcement": True,
            "announcement_type": override["announcement_type"],
            "announcement_origin_date": override["start_date"],
            "announcement_source": "manual_event_override",
        }

    previous_boards = int((previous or {}).get("boards") or 0)
    if (
        previous
        and bool(previous.get("is_gonggao"))
        and boards == previous_boards + 1
    ):
        return {
            "is_announcement": True,
            "announcement_type": previous.get("announcement_type"),
            "announcement_origin_date": previous.get("announcement_origin_date"),
            "announcement_source": previous.get("announcement_source")
            or "limit_run_inheritance",
        }

    direct_type = announcement_type_of(theme)
    if direct_type:
        return {
            "is_announcement": True,
            "announcement_type": direct_type,
            "announcement_origin_date": day,
            "announcement_source": "daily_primary_theme",
        }

    return {
        "is_announcement": False,
        "announcement_type": None,
        "announcement_origin_date": None,
        "announcement_source": None,
    }
