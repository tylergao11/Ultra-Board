# -*- coding: utf-8 -*-
"""开盘啦历史板块成分研究快照。

正式日事实仍只来自 ``data/kaipanla/raw``。本模块单独保存带明确日期的
``ZhiShuStockList_W8`` 原始响应，用于研究个股在当时是否已经属于某个板块。
它不把板块成分自动解释为涨停原因、补涨血缘或交易结论。
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .client import HIS_URL, KaipanlaClient, ok


ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTE_DIR = ROOT / "data" / "kaipanla" / "research_attributes"
CN_TZ = timezone(timedelta(hours=8))
PLATE_RE = re.compile(r"^\d{6}$")


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _plate_code(value: str) -> str:
    text = str(value).strip()
    if not PLATE_RE.fullmatch(text):
        raise ValueError("板块代码必须是六位数字")
    return text


def snapshot_path(day_value: str, plate_code_value: str) -> Path:
    day = _day(day_value)
    plate_code = _plate_code(plate_code_value)
    return ATTRIBUTE_DIR / day / f"{plate_code}.json"


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def _response_day_value(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    text = str(value or "").strip()
    try:
        return _day(text) if text else None
    except ValueError:
        return None


def _response_day(body: dict[str, Any]) -> str | None:
    return _response_day_value(body.get("Day"))


def capture_plate_membership(
    client: KaipanlaClient,
    day_value: str,
    plate_code_value: str,
    *,
    plate_name: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """采集一个历史交易日的板块成分原始响应并严格校验日期。"""
    day = _day(day_value)
    plate_code = _plate_code(plate_code_value)
    path = snapshot_path(day, plate_code)
    if path.exists() and not overwrite:
        return load_plate_snapshot(day, plate_code)

    body = client.post(
        HIS_URL,
        {
            "Order": "1",
            "a": "ZhiShuStockList_W8",
            # 板块成员可能超过 500。这里一次取足，并在下方用 Count 闭合，
            # 避免“请求成功但成员被静默截断”污染属性叠加研究。
            "st": "2000",
            "c": "ZhiShuRanking",
            "old": "1",
            "Type": "20",
            "PlateID": plate_code,
            "Date": day,
        },
    )
    if not ok(body):
        raise ValueError(
            f"开盘啦板块成分请求失败: {body.get('errcode')} {body.get('errmsg')}"
        )
    minimum_day = _response_day_value(body.get("MinDay"))
    if minimum_day is not None and day < minimum_day:
        raise ValueError(
            f"开盘啦板块成分历史最早可查日期为 {minimum_day}，"
            f"请求日期 {day} 不可得"
        )
    response_day = _response_day(body)
    if response_day != day:
        raise ValueError(f"板块成分日期不匹配: 期望 {day}，实际 {response_day}")
    rows = body.get("list")
    if not isinstance(rows, list):
        raise ValueError("开盘啦板块成分响应缺少 list 数组")
    try:
        declared_count = int(body.get("Count"))
    except (TypeError, ValueError) as error:
        raise ValueError("开盘啦板块成分响应缺少有效 Count") from error
    if declared_count != len(rows):
        raise ValueError(
            "开盘啦板块成分响应不完整: "
            f"接口声明 {declared_count}，实际取得 {len(rows)}"
        )

    payload = {
        "schema_version": 1,
        "view": "kaipanla_historical_plate_membership",
        "query": {
            "date": day,
            "plate_code": plate_code,
            "plate_name": str(plate_name or "").strip() or None,
            "endpoint_action": "ZhiShuStockList_W8",
            "type": 20,
        },
        "response_date": response_day,
        "captured_at": datetime.now(CN_TZ).isoformat(timespec="seconds"),
        "member_count": len(rows),
        "declared_member_count": declared_count,
        "source_contract": (
            "历史板块成分只证明该日关系存在，不自动证明当日涨停原因或资金角色。"
        ),
        "raw_response": body,
    }
    _write_json_atomic(path, payload)
    return payload


def load_plate_snapshot(
    day_value: str,
    plate_code_value: str,
) -> dict[str, Any]:
    day = _day(day_value)
    plate_code = _plate_code(plate_code_value)
    path = snapshot_path(day, plate_code)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"板块成分快照顶层必须是对象: {path}")
    query = payload.get("query") or {}
    if (
        payload.get("view") != "kaipanla_historical_plate_membership"
        or query.get("date") != day
        or query.get("plate_code") != plate_code
        or payload.get("response_date") != day
    ):
        raise ValueError(f"板块成分快照合同异常: {path}")
    rows = (payload.get("raw_response") or {}).get("list")
    if (
        not isinstance(rows, list)
        or payload.get("member_count") != len(rows)
        or payload.get("declared_member_count") != len(rows)
    ):
        raise ValueError(f"板块成分快照成员数量不闭合: {path}")
    return payload


def available_plate_snapshots(day_value: str) -> list[dict[str, Any]]:
    """读取指定日期所有已落盘板块成分快照。"""
    day = _day(day_value)
    directory = ATTRIBUTE_DIR / day
    if not directory.exists():
        return []
    return [
        load_plate_snapshot(day, path.stem)
        for path in sorted(directory.glob("*.json"))
        if PLATE_RE.fullmatch(path.stem)
    ]


def membership_index(day_value: str) -> dict[str, list[dict[str, Any]]]:
    """按股票代码索引同日已验证的板块关系。"""
    day = _day(day_value)
    result: dict[str, list[dict[str, Any]]] = {}
    for payload in available_plate_snapshots(day):
        query = payload["query"]
        source_path = snapshot_path(day, query["plate_code"])
        for row in payload["raw_response"]["list"]:
            if not isinstance(row, list) or len(row) < 2:
                continue
            code = str(row[0] or "").strip().zfill(6)
            if not re.fullmatch(r"\d{6}", code):
                continue
            result.setdefault(code, []).append(
                {
                    "plate_code": query["plate_code"],
                    "plate_name": query.get("plate_name"),
                    "evidence_date": day,
                    "source_path": str(source_path.relative_to(ROOT)).replace("\\", "/"),
                }
            )
    for values in result.values():
        values.sort(key=lambda item: item["plate_code"])
    return result
