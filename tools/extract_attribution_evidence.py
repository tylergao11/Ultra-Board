#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取单日动态归因证据，不改写来源分类，也不输出评分或核心结论。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.kaipanla import load_day as load_kaipanla_day  # noqa: E402
from ultraboard.ths.limit_pool import validate_payload  # noqa: E402
from ultraboard.ths.stories import load_day as load_story_day  # noqa: E402


CN_TZ = timezone(timedelta(hours=8))
THS_LIMIT_POOL_DIR = ROOT / "data" / "ths" / "limit_pool"
THS_STORY_DIR = ROOT / "data" / "ths" / "stories"
SESSION_KEYS = (
    "auction",
    "morning",
    "midday_break",
    "afternoon",
    "after_close",
    "missing",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"数据顶层必须是对象: {path}")
    return payload


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def _local_datetime(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, CN_TZ)


def _time_text(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return _local_datetime(timestamp).strftime("%H:%M:%S")


def _session(timestamp: int | None) -> str:
    if timestamp is None:
        return "missing"
    local_time = _local_datetime(timestamp).time().replace(tzinfo=None)
    if local_time < time(9, 30):
        return "auction"
    if local_time <= time(11, 30):
        return "morning"
    if local_time < time(13, 0):
        return "midday_break"
    if local_time <= time(15, 0):
        return "afternoon"
    return "after_close"


def _limit_pool(day: str) -> dict[str, Any]:
    path = THS_LIMIT_POOL_DIR / f"{day}.json"
    payload = _read_json(path)
    validate_payload(payload, day, path)
    return payload


def _stories(day: str) -> list[dict[str, Any]]:
    path = THS_STORY_DIR / f"{day}.json"
    if not path.exists():
        return []
    return list(load_story_day(day)["stories"])


def _stock_record(
    kaipanla_stock: dict[str, Any],
    limit_stock: dict[str, Any] | None,
) -> dict[str, Any]:
    code = _code(kaipanla_stock.get("code"))
    main_theme = str(kaipanla_stock.get("theme") or "").strip()
    candidate_themes = [
        str(item).strip()
        for item in kaipanla_stock.get("themes") or []
        if str(item).strip()
    ]

    first_limit_ts = None
    final_limit_ts = None
    if limit_stock is not None:
        first_limit_ts = int(limit_stock["first_limit_ts"])
        final_limit_ts = int(limit_stock["final_limit_ts"])

    return {
        "code": code,
        "name": str(kaipanla_stock.get("name") or "").strip(),
        "kpl_main_theme": main_theme,
        "kpl_theme_tags_text": str(
            kaipanla_stock.get("theme_tags_text") or ""
        ).strip(),
        "kpl_candidate_themes": candidate_themes,
        "turnover_rate": kaipanla_stock.get("turnover_rate"),
        "amount": kaipanla_stock.get("amount"),
        "open_pct": kaipanla_stock.get("open_pct"),
        "limit_facts_available": limit_stock is not None,
        "boards": limit_stock.get("boards") if limit_stock else None,
        "boards_desc": limit_stock.get("boards_desc") if limit_stock else None,
        "first_limit_ts": first_limit_ts,
        "first_limit_time": _time_text(first_limit_ts),
        "first_limit_session": _session(first_limit_ts),
        "final_limit_ts": final_limit_ts,
        "final_limit_time": _time_text(final_limit_ts),
        "final_limit_session": _session(final_limit_ts),
        "seal_span_seconds": (
            final_limit_ts - first_limit_ts
            if first_limit_ts is not None and final_limit_ts is not None
            else None
        ),
        "open_count": limit_stock.get("open_count") if limit_stock else None,
        "board_type": limit_stock.get("board_type") if limit_stock else None,
        "one_price": limit_stock.get("one_price") if limit_stock else None,
    }


def _session_counts(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts = Counter(str(record.get(field) or "missing") for record in records)
    return {key: counts.get(key, 0) for key in SESSION_KEYS}


def _candidate_group(theme: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        records,
        key=lambda record: (
            record["first_limit_ts"] is None,
            record["first_limit_ts"] or 0,
            record["code"],
        ),
    )
    timestamped = [
        record for record in ordered if record["first_limit_ts"] is not None
    ]
    sequence = []
    for position, record in enumerate(ordered, 1):
        membership_source = (
            "main" if record["kpl_main_theme"] == theme else "owned"
        )
        current_ts = record["first_limit_ts"]
        if current_ts is None:
            earlier: list[dict[str, Any]] = []
            simultaneous: list[dict[str, Any]] = []
            later: list[dict[str, Any]] = []
            first_limit_rank = None
            next_later_lag_seconds = None
        else:
            earlier = [
                item for item in timestamped if item["first_limit_ts"] < current_ts
            ]
            simultaneous = [
                item
                for item in timestamped
                if item["first_limit_ts"] == current_ts
                and item["code"] != record["code"]
            ]
            later = [
                item for item in timestamped if item["first_limit_ts"] > current_ts
            ]
            first_limit_rank = len(earlier) + 1
            next_later_lag_seconds = (
                int(later[0]["first_limit_ts"]) - current_ts if later else None
            )
        sequence.append(
            {
                "sequence_position": position,
                "first_limit_rank": first_limit_rank,
                "code": record["code"],
                "name": record["name"],
                "membership_source": membership_source,
                "kpl_main_theme": record["kpl_main_theme"],
                "boards": record["boards"],
                "first_limit_time": record["first_limit_time"],
                "first_limit_session": record["first_limit_session"],
                "final_limit_time": record["final_limit_time"],
                "final_limit_session": record["final_limit_session"],
                "seal_span_seconds": record["seal_span_seconds"],
                "open_count": record["open_count"],
                "board_type": record["board_type"],
                "one_price": record["one_price"],
                "earlier_first_limit_count": len(earlier),
                "same_second_member_count": len(simultaneous),
                "later_first_limit_count": len(later),
                "later_first_limit_counts": _session_counts(
                    later, "first_limit_session"
                ),
                "next_later_first_lag_seconds": next_later_lag_seconds,
            }
        )

    main_count = sum(record["kpl_main_theme"] == theme for record in records)
    return {
        "theme": theme,
        "member_count": len(records),
        "main_member_count": main_count,
        "owned_only_member_count": len(records) - main_count,
        "first_limit_counts": _session_counts(records, "first_limit_session"),
        "final_limit_counts": _session_counts(records, "final_limit_session"),
        "first_limit_sequence": sequence,
    }


def build_day(day_value: str) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    kaipanla = load_kaipanla_day(day)
    limit_pool = _limit_pool(day)
    kaipanla_by_code = {_code(stock.get("code")): stock for stock in kaipanla["stocks"]}
    limit_by_code = {_code(stock.get("code")): stock for stock in limit_pool["stocks"]}

    issues = []
    for code in sorted(set(kaipanla_by_code) - set(limit_by_code)):
        issues.append({"code": code, "issue": "missing_ths_limit_facts"})
    for code in sorted(set(limit_by_code) - set(kaipanla_by_code)):
        issues.append({"code": code, "issue": "missing_kaipanla_attributes"})

    stocks = [
        _stock_record(stock, limit_by_code.get(code))
        for code, stock in sorted(kaipanla_by_code.items())
    ]
    groups: dict[str, list[dict[str, Any]]] = {}
    for stock in stocks:
        for theme in stock["kpl_candidate_themes"]:
            groups.setdefault(theme, []).append(stock)

    return {
        "date": day,
        "information_cutoff": day,
        "sources": {
            "classification_base": "kaipanla stocks[].theme",
            "candidate_attributes": "kaipanla stocks[].raw[12] / themes",
            "limit_action": "tonghuashun limit_pool",
            "broad_stories": "tonghuashun headline story when manually available",
        },
        "interpretation_contract": {
            "classification": "开盘啦主 theme 是默认归属，归属题材集合是动态调整候选；本输出不改写源数据。",
            "initiative": "先封只表示时间领先，不能单独证明主动性。",
            "resilience": "首封、终封、炸板次数和板型只提供抗压证据，不自动生成强弱结论。",
            "leadership": "同属性后继封板序列只提供带动性线索；必须排除同步共振和其他触发。",
            "continuation": "上午与下午数量描述题材情绪是否延续，不等于某只早盘票造成了下午封板。",
        },
        "session_contract": {
            "auction": "before 09:30:00 Asia/Shanghai",
            "morning": "09:30:00-11:30:00 Asia/Shanghai",
            "afternoon": "13:00:00-15:00:00 Asia/Shanghai",
        },
        "stories": _stories(day),
        "source_issues": issues,
        "stocks": stocks,
        "candidate_groups": [
            _candidate_group(theme, records)
            for theme, records in sorted(groups.items())
        ],
    }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("day", help="交易日 YYYY-MM-DD")
    parser.add_argument(
        "--theme",
        action="append",
        default=[],
        help="只保留指定候选题材，可重复",
    )
    parser.add_argument(
        "--min-members",
        type=int,
        default=1,
        help="仅用于缩小展示范围，不参与归因判断",
    )
    parser.add_argument(
        "--groups-only",
        action="store_true",
        help="只输出候选题材组，省略重复的个股总表",
    )
    args = parser.parse_args(argv)
    if args.min_members < 1:
        parser.error("--min-members 必须大于等于 1")

    payload = build_day(args.day)
    requested = {item.strip() for item in args.theme if item.strip()}
    payload["candidate_groups"] = [
        group
        for group in payload["candidate_groups"]
        if group["member_count"] >= args.min_members
        and (not requested or group["theme"] in requested)
    ]
    payload["view_filter"] = {
        "themes": sorted(requested),
        "min_members": args.min_members,
        "groups_only": args.groups_only,
    }
    if args.groups_only:
        payload.pop("stocks", None)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
