#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把历史快照规范到当前数据源合同，不生成任何交易判断。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
KAIPANLA_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
THS_LIMIT_POOL_DIR = ROOT / "data" / "ths" / "limit_pool"


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"数据源顶层必须是对象: {path}")
    return payload


def write_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, path)


def normalize_kaipanla(path: Path, payload: dict[str, Any]) -> bool:
    day = path.parent.name
    stocks = payload.get("stocks")
    if payload.get("date") != day or not isinstance(stocks, list):
        raise ValueError(f"开盘啦涨停池合同异常: {path}")
    if payload.get("count") != len(stocks):
        raise ValueError(f"开盘啦涨停池数量不闭合: {path}")

    changed = False
    for stock in stocks:
        raw = stock.get("raw") if isinstance(stock, dict) else None
        if not isinstance(raw, list) or len(raw) <= 19:
            raise ValueError(f"开盘啦个股缺少原始分类字段: {path}")
        primary = str(raw[5] or "").strip()
        tags_text = str(raw[12] or "").strip()
        sector_code = str(raw[19] or "").strip()
        if not primary or not sector_code:
            raise ValueError(f"开盘啦个股分类为空: {path}")
        if str(stock.get("theme") or "").strip() != primary:
            raise ValueError(f"开盘啦主分类与原文不一致: {path} {stock.get('code')}")
        if stock.get("theme_tags_text") != tags_text:
            stock["theme_tags_text"] = tags_text
            changed = True

    source = {
        "provider": "kaipanla",
        "action": "DailyLimitPerformance",
        "primary_field": "stocks[].raw[5]",
        "tags_field": "stocks[].raw[12]",
        "sector_code_field": "stocks[].raw[19]",
    }
    if payload.get("theme_source") != source:
        payload["theme_source"] = source
        changed = True
    return changed


def normalize_ths_limit_pool(path: Path, payload: dict[str, Any]) -> bool:
    source = payload.get("source")
    if payload.get("date") != path.stem or not isinstance(source, dict):
        raise ValueError(f"同花顺涨停池合同异常: {path}")
    if source.get("provider") != "tonghuashun_limit_up_pool":
        raise ValueError(f"同花顺涨停池来源异常: {path}")
    changed = source.pop("theme_contract", None) is not None
    contract = "本接口只提供客观涨停事实；具体分类只认开盘啦"
    if source.get("attribute_contract") != contract:
        source["attribute_contract"] = contract
        changed = True
    return changed


def normalize(
    paths: list[Path], handler: Callable[[Path, dict[str, Any]], bool]
) -> int:
    changed = 0
    for path in paths:
        payload = read_json(path)
        if handler(path, payload):
            write_atomic(path, payload)
            changed += 1
    return changed


def main() -> int:
    kaipanla_paths = sorted(KAIPANLA_RAW_DIR.glob("*/zt_pool.json"))
    ths_paths = sorted(THS_LIMIT_POOL_DIR.glob("*.json"))
    if not kaipanla_paths or not ths_paths:
        raise FileNotFoundError("开盘啦或同花顺涨停池历史数据为空")
    kaipanla_changed = normalize(kaipanla_paths, normalize_kaipanla)
    ths_changed = normalize(ths_paths, normalize_ths_limit_pool)
    print(
        f"kaipanla={len(kaipanla_paths)} changed={kaipanla_changed} "
        f"ths_limit_pool={len(ths_paths)} changed={ths_changed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
