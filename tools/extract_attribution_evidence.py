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
KAIPANLA_RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
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
        "limit_facts_available": limit_stock is not None,
        "boards": limit_stock.get("boards") if limit_stock else None,
        "boards_desc": limit_stock.get("boards_desc") if limit_stock else None,
        "price": limit_stock.get("price") if limit_stock else None,
        "change_rate": limit_stock.get("change_rate") if limit_stock else None,
        "circulating_market_cap": (
            limit_stock.get("circulating_market_cap") if limit_stock else None
        ),
        "total_market_cap": (
            limit_stock.get("total_market_cap") if limit_stock else None
        ),
        "turnover_rate": (
            limit_stock.get("turnover_rate") if limit_stock else None
        ),
        "seal_order_amount": (
            limit_stock.get("seal_order_amount") if limit_stock else None
        ),
        "seal_order_volume": (
            limit_stock.get("seal_order_volume") if limit_stock else None
        ),
        "seal_order_ratio": (
            limit_stock.get("seal_order_ratio") if limit_stock else None
        ),
        "limit_up_success_rate": (
            limit_stock.get("limit_up_success_rate") if limit_stock else None
        ),
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


def _nonzero_session_counts(
    records: list[dict[str, Any]],
    field: str,
) -> dict[str, int]:
    return {
        key: value
        for key, value in _session_counts(records, field).items()
        if value
    }


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
                "price": record["price"],
                "circulating_market_cap": record["circulating_market_cap"],
                "turnover_rate": record["turnover_rate"],
                "seal_order_amount": record["seal_order_amount"],
                "seal_order_ratio": record["seal_order_ratio"],
                "limit_up_success_rate": record["limit_up_success_rate"],
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
    available_boards = [
        int(record["boards"])
        for record in records
        if isinstance(record.get("boards"), int)
        and not isinstance(record.get("boards"), bool)
    ]
    height_counts = Counter(available_boards)
    height_ordered = sorted(
        records,
        key=lambda record: (
            record["boards"] is None,
            -(record["boards"] or 0),
            record["first_limit_ts"] is None,
            record["first_limit_ts"] or 0,
            record["code"],
        ),
    )
    return {
        "theme": theme,
        "member_count": len(records),
        "main_member_count": main_count,
        "owned_only_member_count": len(records) - main_count,
        "max_boards": max(available_boards, default=None),
        "height_counts": {
            str(boards): height_counts[boards]
            for boards in sorted(height_counts, reverse=True)
        },
        "height_sequence": [
            {
                "code": record["code"],
                "name": record["name"],
                "boards": record["boards"],
                "membership_source": (
                    "main" if record["kpl_main_theme"] == theme else "owned"
                ),
                "price": record["price"],
                "circulating_market_cap": record["circulating_market_cap"],
                "first_limit_time": record["first_limit_time"],
                "final_limit_time": record["final_limit_time"],
                "open_count": record["open_count"],
                "board_type": record["board_type"],
            }
            for record in height_ordered
        ],
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
            "market_and_limit_facts": "tonghuashun limit_pool",
            "broad_stories": "tonghuashun headline story when manually available",
        },
        "interpretation_contract": {
            "classification": "开盘啦主 theme 是默认归属，归属题材集合是动态调整候选；本输出不改写源数据。",
            "position": "连板身位先于其他载体条件展示，但身位本身不等于核心结论。",
            "tradability": "股价、流通市值、换手率和封单事实只取同花顺，不从开盘啦拼接。",
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


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _market_summary(
    kaipanla: dict[str, Any],
    stocks: list[dict[str, Any]],
) -> dict[str, Any]:
    sentiment = kaipanla.get("sentiment")
    info = sentiment.get("info") if isinstance(sentiment, dict) else None
    info = info if isinstance(info, dict) else {}
    board_values = [
        int(stock["boards"])
        for stock in stocks
        if isinstance(stock.get("boards"), int)
        and not isinstance(stock.get("boards"), bool)
    ]
    board_counts = Counter(board_values)
    return {
        "market_mood": str(info.get("sign") or "").strip() or None,
        "rise_count": _optional_int(info.get("SZJS")),
        "fall_count": _optional_int(info.get("XDJS")),
        "limit_up_count": _optional_int(info.get("ZT")),
        "natural_limit_up_count": _optional_int(info.get("SJZT")),
        "limit_down_count": _optional_int(info.get("DT")),
        "natural_limit_down_count": _optional_int(info.get("SJDT")),
        "max_boards": max(board_values, default=None),
        "board_counts": {
            str(boards): board_counts[boards]
            for boards in sorted(board_counts, reverse=True)
        },
    }


def _previous_trading_day(day: str) -> str | None:
    if not KAIPANLA_RAW_DIR.exists():
        return None
    candidates = []
    for path in KAIPANLA_RAW_DIR.iterdir():
        if not path.is_dir() or path.name >= day:
            continue
        try:
            candidate = date.fromisoformat(path.name).isoformat()
        except ValueError:
            continue
        if candidate != path.name:
            continue
        if not (path / "zt_pool.json").exists():
            continue
        if not (path / "sector_ladder.json").exists():
            continue
        candidates.append(candidate)
    return max(candidates, default=None)


def _candidate_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    return (
        -(record.get("boards") or 0),
        bool(record.get("one_price")),
        record.get("first_limit_ts") is None,
        record.get("first_limit_ts") or 0,
        record.get("code") or "",
    )


def _decision_candidate(
    stock: dict[str, Any],
    previous_by_code: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    previous_day: dict[str, Any] | None
    if previous_by_code is None:
        previous_day = None
    else:
        previous = previous_by_code.get(stock["code"])
        previous_day = (
            {
                "limit_up": True,
                "boards": previous.get("boards"),
                "first_limit_time": previous.get("first_limit_time"),
                "final_limit_time": previous.get("final_limit_time"),
                "one_price": previous.get("one_price"),
            }
            if previous is not None
            else {"limit_up": False}
        )
    return {
        "code": stock["code"],
        "name": stock["name"],
        "boards": stock["boards"],
        "boards_desc": stock["boards_desc"],
        "node_board_access": (
            "one_price_locked" if stock["one_price"] else "turnover_occurred"
        ),
        "attributes": {
            "kpl_main_theme": stock["kpl_main_theme"],
            "kpl_candidate_themes": stock["kpl_candidate_themes"],
        },
        "carrier": {
            "price": stock["price"],
            "circulating_market_cap": stock["circulating_market_cap"],
            "turnover_rate": stock["turnover_rate"],
            "seal_order_ratio": stock["seal_order_ratio"],
        },
        "board_action": {
            "first_limit_time": stock["first_limit_time"],
            "first_limit_session": stock["first_limit_session"],
            "final_limit_time": stock["final_limit_time"],
            "final_limit_session": stock["final_limit_session"],
            "seal_span_seconds": stock["seal_span_seconds"],
            "open_count": stock["open_count"],
            "board_type": stock["board_type"],
            "one_price": stock["one_price"],
        },
        "previous_day": previous_day,
    }


def _timeline_member(theme: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": record["code"],
        "name": record["name"],
        "boards": record["boards"],
        "membership_source": (
            "main" if record["kpl_main_theme"] == theme else "owned"
        ),
        "kpl_main_theme": record["kpl_main_theme"],
        "first_limit_time": record["first_limit_time"],
        "first_limit_session": record["first_limit_session"],
        "final_limit_time": record["final_limit_time"],
        "final_limit_session": record["final_limit_session"],
        "open_count": record["open_count"],
        "board_type": record["board_type"],
        "one_price": record["one_price"],
    }


def _position_member(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": record["code"],
        "name": record["name"],
        "boards": record["boards"],
        "first_limit_time": record["first_limit_time"],
        "final_limit_time": record["final_limit_time"],
        "open_count": record["open_count"],
        "one_price": record["one_price"],
    }


def _timing_relation(
    anchor: dict[str, Any],
    records: list[dict[str, Any]],
    *,
    timestamp_field: str,
    time_field: str,
    session_field: str,
) -> dict[str, Any]:
    anchor_timestamp = anchor.get(timestamp_field)
    if anchor_timestamp is None:
        return {
            "anchor_time": None,
            "before_count": 0,
            "same_second_count": 0,
            "after_count": 0,
            "after_session_counts": {},
            "next_after": None,
        }
    timestamped = [
        record
        for record in records
        if record["code"] != anchor["code"]
        and record.get(timestamp_field) is not None
    ]
    before = [
        record
        for record in timestamped
        if record[timestamp_field] < anchor_timestamp
    ]
    same_second = [
        record
        for record in timestamped
        if record[timestamp_field] == anchor_timestamp
    ]
    after = sorted(
        (
            record
            for record in timestamped
            if record[timestamp_field] > anchor_timestamp
        ),
        key=lambda record: (record[timestamp_field], record["code"]),
    )
    next_after = None
    if after:
        next_record = after[0]
        next_after = {
            "code": next_record["code"],
            "name": next_record["name"],
            "boards": next_record["boards"],
            "time": next_record[time_field],
            "lag_seconds": next_record[timestamp_field] - anchor_timestamp,
        }
    return {
        "anchor_time": anchor[time_field],
        "before_count": len(before),
        "same_second_count": len(same_second),
        "after_count": len(after),
        "after_session_counts": _nonzero_session_counts(after, session_field),
        "next_after": next_after,
    }


def _theme_timeline(
    theme: str,
    records: list[dict[str, Any]],
    research_codes: set[str],
) -> dict[str, Any]:
    first_ordered = sorted(
        records,
        key=lambda record: (
            record["first_limit_ts"] is None,
            record["first_limit_ts"] or 0,
            record["code"],
        ),
    )
    board_values = [
        int(record["boards"])
        for record in records
        if isinstance(record.get("boards"), int)
        and not isinstance(record.get("boards"), bool)
    ]
    height_counts = Counter(board_values)
    relations = []
    for anchor in sorted(
        (record for record in records if record["code"] in research_codes),
        key=_candidate_sort_key,
    ):
        higher = sorted(
            (
                record
                for record in records
                if record["code"] != anchor["code"]
                and (record.get("boards") or 0) > (anchor.get("boards") or 0)
            ),
            key=_candidate_sort_key,
        )
        same_position = sorted(
            (
                record
                for record in records
                if record["code"] != anchor["code"]
                and record.get("boards") == anchor.get("boards")
            ),
            key=_candidate_sort_key,
        )
        relations.append(
            {
                "code": anchor["code"],
                "name": anchor["name"],
                "boards": anchor["boards"],
                "higher_position_members": [
                    _position_member(record) for record in higher
                ],
                "same_position_members": [
                    _position_member(record) for record in same_position
                ],
                "first_limit_relation": _timing_relation(
                    anchor,
                    records,
                    timestamp_field="first_limit_ts",
                    time_field="first_limit_time",
                    session_field="first_limit_session",
                ),
                "final_limit_relation": _timing_relation(
                    anchor,
                    records,
                    timestamp_field="final_limit_ts",
                    time_field="final_limit_time",
                    session_field="final_limit_session",
                ),
            }
        )
    return {
        "theme": theme,
        "member_count": len(records),
        "main_member_count": sum(
            record["kpl_main_theme"] == theme for record in records
        ),
        "owned_only_member_count": sum(
            record["kpl_main_theme"] != theme for record in records
        ),
        "max_boards": max(board_values, default=None),
        "height_counts": {
            str(boards): height_counts[boards]
            for boards in sorted(height_counts, reverse=True)
        },
        "first_limit_counts": _nonzero_session_counts(
            records, "first_limit_session"
        ),
        "final_limit_counts": _nonzero_session_counts(
            records, "final_limit_session"
        ),
        "members_by_first_limit": [
            _timeline_member(theme, record) for record in first_ordered
        ],
        "candidate_relations": relations,
    }


def _ladder_transition(
    previous_stocks: list[dict[str, Any]],
    current_by_code: dict[str, dict[str, Any]],
    min_boards: int,
) -> list[dict[str, Any]]:
    previous_ladder = [
        stock
        for stock in previous_stocks
        if isinstance(stock.get("boards"), int)
        and not isinstance(stock.get("boards"), bool)
        and stock["boards"] >= min_boards
    ]
    result = []
    for previous in sorted(previous_ladder, key=_candidate_sort_key):
        current = current_by_code.get(previous["code"])
        if current is None:
            status = "not_in_current_limit_pool"
            current_facts = None
        else:
            status = (
                "advanced"
                if (current.get("boards") or 0) > (previous.get("boards") or 0)
                else "current_limit_up_present"
            )
            current_facts = {
                "boards": current["boards"],
                "first_limit_time": current["first_limit_time"],
                "final_limit_time": current["final_limit_time"],
                "open_count": current["open_count"],
                "one_price": current["one_price"],
            }
        result.append(
            {
                "code": previous["code"],
                "name": previous["name"],
                "previous": {
                    "boards": previous["boards"],
                    "kpl_main_theme": previous["kpl_main_theme"],
                    "kpl_candidate_themes": previous["kpl_candidate_themes"],
                    "first_limit_time": previous["first_limit_time"],
                    "final_limit_time": previous["final_limit_time"],
                    "open_count": previous["open_count"],
                    "one_price": previous["one_price"],
                },
                "current_status": status,
                "current": current_facts,
            }
        )
    return result


def _locked_guidance(
    research_stocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    locked = [stock for stock in research_stocks if stock.get("one_price")]
    turnover = [stock for stock in research_stocks if not stock.get("one_price")]
    result = []
    for guide in locked:
        guide_themes = set(guide["kpl_candidate_themes"])
        peers = []
        for candidate in turnover:
            if candidate.get("boards") != guide.get("boards"):
                continue
            shared_themes = sorted(
                guide_themes.intersection(candidate["kpl_candidate_themes"])
            )
            if not shared_themes:
                continue
            peers.append(
                {
                    "code": candidate["code"],
                    "name": candidate["name"],
                    "boards": candidate["boards"],
                    "shared_themes": shared_themes,
                    "first_limit_time": candidate["first_limit_time"],
                    "final_limit_time": candidate["final_limit_time"],
                    "open_count": candidate["open_count"],
                    "board_type": candidate["board_type"],
                }
            )
        result.append(
            {
                "guide": {
                    "code": guide["code"],
                    "name": guide["name"],
                    "boards": guide["boards"],
                    "kpl_candidate_themes": guide["kpl_candidate_themes"],
                },
                "same_position_turnover_peers": peers,
            }
        )
    return result


def build_decision_view(
    day_value: str,
    candidate_min_boards: int = 1,
) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    if candidate_min_boards < 1:
        raise ValueError("candidate_min_boards 必须大于等于 1")
    evidence = build_day(day)
    kaipanla = load_kaipanla_day(day)
    current_stocks = evidence["stocks"]
    current_by_code = {stock["code"]: stock for stock in current_stocks}
    warnings: list[dict[str, Any]] = []

    stories = [
        {
            "source_position": story["source_position"],
            "story": story["story"],
        }
        for story in evidence["stories"]
    ]
    if not stories:
        warnings.append(
            {
                "code": "story_missing",
                "date": day,
                "message": "同花顺标题后半句故事尚未人工录入。",
            }
        )
    if evidence["source_issues"]:
        warnings.append(
            {
                "code": "current_source_reconciliation_issue",
                "date": day,
                "details": evidence["source_issues"],
            }
        )
    if not isinstance(kaipanla.get("sentiment"), dict):
        warnings.append(
            {
                "code": "sentiment_missing",
                "date": day,
                "message": "开盘啦情绪快照缺失。",
            }
        )

    previous_day = _previous_trading_day(day)
    previous_evidence = None
    if previous_day is None:
        warnings.append(
            {
                "code": "previous_trading_day_missing",
                "date": day,
                "message": "没有找到更早的开盘啦交易日快照。",
            }
        )
    elif not (THS_LIMIT_POOL_DIR / f"{previous_day}.json").exists():
        warnings.append(
            {
                "code": "previous_limit_pool_missing",
                "date": previous_day,
                "message": "上一交易日缺少同花顺涨停池，无法生成梯队迁移。",
            }
        )
    else:
        previous_evidence = build_day(previous_day)
        if previous_evidence["source_issues"]:
            warnings.append(
                {
                    "code": "previous_source_reconciliation_issue",
                    "date": previous_day,
                    "details": previous_evidence["source_issues"],
                }
            )

    previous_by_code = (
        {stock["code"]: stock for stock in previous_evidence["stocks"]}
        if previous_evidence is not None
        else None
    )
    research_stocks = sorted(
        (
            stock
            for stock in current_stocks
            if isinstance(stock.get("boards"), int)
            and not isinstance(stock.get("boards"), bool)
            and stock["boards"] >= candidate_min_boards
        ),
        key=_candidate_sort_key,
    )
    research_codes = {stock["code"] for stock in research_stocks}
    research_themes = {
        theme
        for stock in research_stocks
        for theme in stock["kpl_candidate_themes"]
    }
    theme_records: dict[str, list[dict[str, Any]]] = {
        theme: [] for theme in research_themes
    }
    for stock in current_stocks:
        for theme in stock["kpl_candidate_themes"]:
            if theme in theme_records:
                theme_records[theme].append(stock)
    theme_timelines = [
        _theme_timeline(theme, records, research_codes)
        for theme, records in theme_records.items()
        if len(records) >= 2
    ]
    theme_timelines.sort(
        key=lambda group: (
            -(group["max_boards"] or 0),
            -group["member_count"],
            group["theme"],
        )
    )

    data_days_used = [day]
    if previous_evidence is not None and previous_day is not None:
        data_days_used.insert(0, previous_day)
    return {
        "date": day,
        "information_cutoff": day,
        "view": "decision_evidence",
        "data_days_used": data_days_used,
        "previous_trading_day": previous_day,
        "decision_contract": {
            "candidate_scope": "默认保留全部涨停；板数只是事实。candidate_min_boards 仅缩小展示范围，不代表交易排除条件。",
            "one_price": "真一字买不到时只作为方向与身位指引；优先映射同身位、共享属性的非一字票，但不自动产生买点。若其后来开板换手，再按换手行为重新判断。",
            "timeline": "首封与最终回封分别比较；先后关系只提供主动性、抗压性和带动性证据。",
            "theme_scope": "候选全部属性保留在个股记录中；只有当日至少两只涨停的属性展开时序。",
            "judgement": "本视图不评分、不自动改写开盘啦分类，也不输出核心或买点结论。",
            "execution_boundary": "只包含T日收盘及更早事实，不包含T+1竞价或盘中结果。",
        },
        "warnings": warnings,
        "market": _market_summary(kaipanla, current_stocks),
        "stories": stories,
        "ladder_transition": (
            _ladder_transition(
                previous_evidence["stocks"],
                current_by_code,
                candidate_min_boards,
            )
            if previous_evidence is not None
            else []
        ),
        "candidates": [
            _decision_candidate(stock, previous_by_code)
            for stock in research_stocks
        ],
        "locked_guidance": _locked_guidance(research_stocks),
        "theme_timelines": theme_timelines,
        "display_filter": {"candidate_min_boards": candidate_min_boards},
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
    parser.add_argument(
        "--decision-view",
        action="store_true",
        help="输出涨停候选池、上一交易日梯队迁移与候选属性双时序",
    )
    parser.add_argument(
        "--candidate-min-boards",
        type=int,
        default=1,
        help="仅缩小 decision-view 展示范围；默认1，不构成交易排除条件",
    )
    args = parser.parse_args(argv)
    if args.min_members < 1:
        parser.error("--min-members 必须大于等于 1")
    if args.candidate_min_boards < 1:
        parser.error("--candidate-min-boards 必须大于等于 1")

    if args.decision_view:
        if args.theme or args.min_members != 1 or args.groups_only:
            parser.error(
                "--decision-view 不能与 --theme、--min-members 或 --groups-only 同时使用"
            )
        payload = build_decision_view(args.day, args.candidate_min_boards)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

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
