# -*- coding: utf-8 -*-
"""单交易日市场事实。

默认展开当日全市场全部来源股票，包括首板；题材与板数参数只缩小返回范围。
本模块只整理日期 T 及以前的来源事实，不输出核心、强弱、接力或买点判断。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from ultraboard.kaipanla import load_day as load_kaipanla_day
from ultraboard.ths.limit_pool import load_day as load_limit_day
from ultraboard.ths.stories import load_day as load_story_day


ROOT = Path(__file__).resolve().parents[1]
KPL_DIR = ROOT / "data" / "kaipanla" / "raw"
THS_LIMIT_DIR = ROOT / "data" / "ths" / "limit_pool"
THS_STORY_DIR = ROOT / "data" / "ths" / "stories"
KPL_REQUIRED_FILES = (
    "zt_pool.json",
    "sector_ladder.json",
    "sentiment.json",
    "expression.json",
)
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CN_TZ = timezone(timedelta(hours=8))


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def _time_text(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, CN_TZ).strftime("%H:%M:%S")


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _date_names(directory: Path, *, directories: bool) -> set[str]:
    if not directory.exists():
        return set()
    result = set()
    for path in directory.iterdir():
        if path.is_dir() != directories:
            continue
        candidate = path.name if directories else path.stem
        if not DAY_RE.fullmatch(candidate):
            continue
        try:
            normalized = _day(candidate)
        except ValueError:
            continue
        if normalized == candidate:
            result.add(candidate)
    return result


def available_days() -> list[str]:
    """返回任一正式来源存在的日期，避免用交集静默跳过缺失日。"""
    return sorted(
        _date_names(KPL_DIR, directories=True)
        | _date_names(THS_LIMIT_DIR, directories=False)
        | _date_names(THS_STORY_DIR, directories=False)
    )


def _neighbor_day(day_value: str, *, direction: int) -> str | None:
    day = _day(day_value)
    days = available_days()
    if day not in days:
        return None
    position = days.index(day) + direction
    return days[position] if 0 <= position < len(days) else None


def _coverage(day: str) -> dict[str, Any]:
    directory = KPL_DIR / day
    kpl_missing = [name for name in KPL_REQUIRED_FILES if not (directory / name).exists()]
    kpl_mismatch = (directory / "_MISMATCH").exists()
    historical_complete = (directory / "_DONE").exists()
    current_snapshot = (directory / "_CURRENT_SNAPSHOT").exists()
    kpl_ready = bool(
        directory.is_dir()
        and not kpl_missing
        and not kpl_mismatch
        and (historical_complete or current_snapshot)
    )
    limit_ready = (THS_LIMIT_DIR / f"{day}.json").exists()
    story_ready = (THS_STORY_DIR / f"{day}.json").exists()
    return {
        "date": day,
        "kpl_ready": kpl_ready,
        "kpl_snapshot_mode": (
            "historical_complete"
            if historical_complete
            else "current_close_snapshot"
            if current_snapshot
            else None
        ),
        "kpl_missing_files": kpl_missing,
        **({"kpl_mismatch": True} if kpl_mismatch else {}),
        "ths_limit_pool_ready": limit_ready,
        "ths_story_ready": story_ready,
        "fact_ready": kpl_ready and limit_ready and story_ready,
    }


def _load_sources(
    day: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    try:
        kaipanla = load_kaipanla_day(day)
    except (FileNotFoundError, ValueError) as exc:
        kaipanla = None
        issues.append(
            {"kind": "kaipanla_unavailable", "date": day, "detail": str(exc)}
        )

    try:
        limit_pool = load_limit_day(day)
    except (FileNotFoundError, ValueError) as exc:
        limit_pool = None
        issues.append(
            {"kind": "ths_limit_pool_unavailable", "date": day, "detail": str(exc)}
        )

    try:
        stories = load_story_day(day)
    except (FileNotFoundError, ValueError) as exc:
        stories = None
        issues.append(
            {
                "kind": "ths_story_unavailable",
                "date": day,
                "required_for_fact_view": True,
                "detail": str(exc),
            }
        )
    return kaipanla, limit_pool, stories, issues


def _stock_record(
    day: str,
    code: str,
    kaipanla_stock: dict[str, Any] | None,
    limit_stock: dict[str, Any] | None,
    requested_themes: tuple[str, ...],
) -> dict[str, Any]:
    main_theme = (
        str(kaipanla_stock.get("theme") or "").strip()
        if kaipanla_stock is not None
        else ""
    )
    candidate_themes = (
        [
            str(item).strip()
            for item in kaipanla_stock.get("themes") or []
            if str(item).strip()
        ]
        if kaipanla_stock is not None
        else []
    )
    attribute_set = set(candidate_themes)
    if main_theme:
        attribute_set.add(main_theme)
    matched_attributes = [
        {
            "theme": theme,
            "membership_source": "main" if theme == main_theme else "candidate",
        }
        for theme in requested_themes
        if theme in attribute_set
    ]

    first_ts = int(limit_stock["first_limit_ts"]) if limit_stock else None
    final_ts = int(limit_stock["final_limit_ts"]) if limit_stock else None
    name = str(
        (limit_stock or {}).get("name")
        or (kaipanla_stock or {}).get("name")
        or ""
    ).strip()
    return {
        "date": day,
        "code": code,
        "name": name,
        "attributes": (
            {
                "source_main_theme": main_theme or None,
                "source_candidate_themes": candidate_themes,
                "source_sector_code": kaipanla_stock.get("sector_code"),
                "source_is_fanbao": bool(kaipanla_stock.get("is_fanbao")),
                **(
                    {"matched_attributes": matched_attributes}
                    if requested_themes
                    else {}
                ),
            }
            if kaipanla_stock is not None
            else None
        ),
        "limit_facts": (
            {
                "boards": limit_stock.get("boards"),
                "boards_desc": limit_stock.get("boards_desc"),
                "limit_up_window_days": limit_stock.get("limit_up_window_days"),
                "limit_up_total": limit_stock.get("limit_up_total"),
                "boards_source": limit_stock.get("boards_source"),
                "consecutive_limit_up_dates": limit_stock.get(
                    "consecutive_limit_up_dates"
                ),
                "first_limit_ts": first_ts,
                "first_limit_time": _time_text(first_ts),
                "final_limit_ts": final_ts,
                "final_limit_time": _time_text(final_ts),
                "seal_span_seconds": (
                    final_ts - first_ts
                    if first_ts is not None and final_ts is not None
                    else None
                ),
                "open_count": limit_stock.get("open_count"),
                "board_type": limit_stock.get("board_type"),
                "one_price": limit_stock.get("one_price"),
                "is_again_limit": limit_stock.get("is_again_limit"),
                "change_tag": limit_stock.get("change_tag"),
                "price": limit_stock.get("price"),
                "change_rate": limit_stock.get("change_rate"),
                "circulating_market_cap": limit_stock.get(
                    "circulating_market_cap"
                ),
                "total_market_cap": limit_stock.get("total_market_cap"),
                "turnover_rate": limit_stock.get("turnover_rate"),
                "seal_order_amount": limit_stock.get("seal_order_amount"),
                "seal_order_volume": limit_stock.get("seal_order_volume"),
                "seal_order_ratio": limit_stock.get("seal_order_ratio"),
                "limit_up_success_rate": limit_stock.get(
                    "limit_up_success_rate"
                ),
            }
            if limit_stock is not None
            else None
        ),
    }


def _record_matches(
    record: dict[str, Any],
    themes: tuple[str, ...],
    theme_match: str,
) -> bool:
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        return False
    candidates = set(attributes.get("source_candidate_themes") or [])
    main_theme = attributes.get("source_main_theme")
    if main_theme:
        candidates.add(main_theme)
    if theme_match == "all":
        return all(theme in candidates for theme in themes)
    return bool(candidates.intersection(themes))


def _limit_boards(record: dict[str, Any] | None) -> int | None:
    if record is None:
        return None
    facts = record.get("limit_facts")
    boards = facts.get("boards") if isinstance(facts, dict) else None
    return boards if isinstance(boards, int) and not isinstance(boards, bool) else None


def _theme_index(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        attributes = record.get("attributes")
        if not isinstance(attributes, dict):
            continue
        themes = dict.fromkeys(
            [
                theme
                for theme in [
                    attributes.get("source_main_theme"),
                    *(attributes.get("source_candidate_themes") or []),
                ]
                if theme
            ]
        )
        for theme in themes:
            groups[str(theme)].append(record)

    result = []
    for theme, members in groups.items():
        boards = [value for value in (_limit_boards(row) for row in members) if value]
        result.append(
            {
                "theme": theme,
                "member_count": len(members),
                "main_member_count": sum(
                    (row.get("attributes") or {}).get("source_main_theme") == theme
                    for row in members
                ),
                "first_board_count": sum(value == 1 for value in boards),
                "higher_board_count": sum(value >= 2 for value in boards),
                "missing_board_fact_count": len(members) - len(boards),
                "max_boards": max(boards, default=None),
            }
        )
    result.sort(
        key=lambda row: (
            -(row["max_boards"] or 0),
            -row["member_count"],
            row["theme"],
        )
    )
    return result


def _sector_index(kaipanla: dict[str, Any] | None) -> list[dict[str, Any]]:
    if kaipanla is None:
        return []
    result = []
    for sector in kaipanla.get("sectors") or []:
        tiers = sector.get("tiers") or {}
        result.append(
            {
                "code": sector.get("code"),
                "name": sector.get("name"),
                "source_count": sector.get("count"),
                "source_position": sector.get("source_position"),
                "height_counts": {
                    str(height): len(members or [])
                    for height, members in tiers.items()
                },
                "fanbao_count": len(sector.get("fanbao") or []),
                "height_mark_count": len(sector.get("height_marks") or []),
            }
        )
    return result


def _market_summary(
    kaipanla: dict[str, Any] | None,
    limit_pool: dict[str, Any] | None,
) -> dict[str, Any]:
    sentiment = (kaipanla or {}).get("sentiment")
    sentiment_info = (
        sentiment.get("info") if isinstance(sentiment, dict) else None
    )
    sentiment_info = sentiment_info if isinstance(sentiment_info, dict) else {}
    expression = (kaipanla or {}).get("expression")
    expression_info = (
        expression.get("info") if isinstance(expression, dict) else None
    )
    rows = list((limit_pool or {}).get("stocks") or [])
    board_values = [
        int(row["boards"])
        for row in rows
        if isinstance(row.get("boards"), int)
        and not isinstance(row.get("boards"), bool)
    ]
    counts = Counter(board_values)
    maximum = max(board_values, default=None)
    return {
        "kaipanla_stock_count": len((kaipanla or {}).get("stocks") or []),
        "ths_limit_up_count": len(rows),
        "first_board_count": counts.get(1, 0),
        "higher_board_count": sum(count for boards, count in counts.items() if boards >= 2),
        "max_boards": maximum,
        "max_board_holders": sorted(
            _code(row.get("code")) for row in rows if row.get("boards") == maximum
        ),
        "board_counts": {
            str(boards): counts[boards] for boards in sorted(counts, reverse=True)
        },
        "market_mood": str(sentiment_info.get("sign") or "").strip() or None,
        "rise_count": _optional_int(sentiment_info.get("SZJS")),
        "fall_count": _optional_int(sentiment_info.get("XDJS")),
        "source_limit_up_count": _optional_int(sentiment_info.get("ZT")),
        "source_natural_limit_up_count": _optional_int(sentiment_info.get("SJZT")),
        "limit_down_count": _optional_int(sentiment_info.get("DT")),
        "natural_limit_down_count": _optional_int(sentiment_info.get("SJDT")),
        "sentiment_info": sentiment_info or None,
        "expression_info": expression_info,
        "plate_info": (kaipanla or {}).get("plate_info"),
    }


def _expanded_day_records(
    all_records: dict[str, dict[str, Any]],
    themes: tuple[str, ...],
    theme_match: str,
    boards: tuple[int, ...],
    min_board: int | None,
    max_board: int | None,
) -> dict[str, dict[str, Any]]:
    def included(record: dict[str, Any]) -> bool:
        if themes and not _record_matches(record, themes, theme_match):
            return False
        value = _limit_boards(record)
        if boards and value not in boards:
            return False
        if min_board is not None and (value is None or value < min_board):
            return False
        if max_board is not None and (value is None or value > max_board):
            return False
        return True

    return {
        code: record
        for code, record in all_records.items()
        if included(record)
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    facts = record.get("limit_facts") or {}
    return (
        -(_limit_boards(record) or 0),
        facts.get("first_limit_ts") is None,
        facts.get("first_limit_ts") or 0,
        record["code"],
    )


def _stock_story_coverage(
    story_payload: dict[str, Any] | None,
    all_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    by_name: dict[str, list[str]] = defaultdict(list)
    for code, record in all_records.items():
        name = str(record.get("name") or "").strip()
        if name:
            by_name[name].append(code)

    covered: set[str] = set()
    incomplete: set[str] = set()
    for member in (story_payload or {}).get("stock_stories") or []:
        if not isinstance(member, dict):
            continue
        raw_code = _code(member.get("code"))
        name = str(member.get("name") or "").strip()
        code = raw_code if raw_code in all_records else ""
        if not code and name and len(by_name.get(name) or []) == 1:
            code = by_name[name][0]
        if not code:
            continue
        story = str(member.get("story") or "").strip()
        if story:
            covered.add(code)
        else:
            incomplete.add(code)
    for group in (story_payload or {}).get("stories") or []:
        if not isinstance(group, dict):
            continue
        for member in group.get("stocks") or []:
            if not isinstance(member, dict):
                continue
            raw_code = _code(member.get("code"))
            name = str(member.get("name") or "").strip()
            code = raw_code if raw_code in all_records else ""
            if not code and name and len(by_name.get(name) or []) == 1:
                code = by_name[name][0]
            if not code:
                continue
            story = str(member.get("story") or "").strip()
            if story:
                covered.add(code)
            else:
                incomplete.add(code)

    required = set(all_records)
    missing = sorted(required - covered)
    incomplete_rows = sorted(incomplete)
    return {
        "stock_story_required_count": len(required),
        "stock_story_complete_count": len(required - set(missing)),
        "stock_story_missing_codes": missing,
        "stock_story_empty_codes": incomplete_rows,
        "stock_story_complete": not missing and not incomplete_rows,
    }


def _build_day(
    day: str,
    themes: tuple[str, ...],
    *,
    theme_match: str = "any",
    boards: tuple[int, ...] = (),
    min_board: int | None = None,
    max_board: int | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    kaipanla, limit_pool, story_payload, issues = _load_sources(day)
    kpl_by_code = {
        _code(row.get("code")): row for row in (kaipanla or {}).get("stocks") or []
    }
    limit_by_code = {
        _code(row.get("code")): row
        for row in (limit_pool or {}).get("stocks") or []
    }
    only_kpl = sorted(set(kpl_by_code) - set(limit_by_code))
    only_ths = sorted(set(limit_by_code) - set(kpl_by_code))
    if only_kpl:
        issues.append({"kind": "stocks_only_in_kaipanla", "codes": only_kpl})
    if only_ths:
        issues.append({"kind": "stocks_only_in_ths_limit_pool", "codes": only_ths})

    all_records = {
        code: _stock_record(
            day,
            code,
            kpl_by_code.get(code),
            limit_by_code.get(code),
            themes,
        )
        for code in sorted(set(kpl_by_code) | set(limit_by_code))
    }
    expanded = _expanded_day_records(
        all_records,
        themes,
        theme_match,
        boards,
        min_board,
        max_board,
    )
    expanded_rows = sorted(expanded.values(), key=_record_sort_key)
    board_index: dict[str, list[str]] = defaultdict(list)
    for row in expanded_rows:
        boards = _limit_boards(row)
        board_index[str(boards) if boards is not None else "missing"].append(
            row["code"]
        )

    all_theme_index = _theme_index(all_records.values())
    requested = set(themes)
    theme_index = (
        [row for row in all_theme_index if row["theme"] in requested]
        if themes
        else all_theme_index
    )
    matching_sector_records = []
    if themes and kaipanla is not None:
        matching_sector_records = [
            sector
            for sector in kaipanla.get("sectors") or []
            if str(sector.get("name") or "").strip() in requested
        ]

    stories = [dict(item) for item in (story_payload or {}).get("stories") or []]
    market_story = (story_payload or {}).get("market_story")
    if isinstance(market_story, dict):
        stories = [
            {
                "source_position": 1,
                "context": "盘面主流看点",
                "story": market_story.get("focus"),
                "headline": market_story.get("headline"),
                "market_narrative": market_story.get("narrative"),
            }
        ]
    stock_story_records = [
        dict(item)
        for item in (story_payload or {}).get("stock_stories") or []
        if isinstance(item, dict)
    ]
    coverage = {
        **_coverage(day),
        **_stock_story_coverage(story_payload, all_records),
    }
    coverage["fact_ready"] = bool(
        coverage["fact_ready"] and coverage["stock_story_complete"]
    )
    story_view = {
        "source": (story_payload or {}).get("source"),
        "source_image": (story_payload or {}).get("source_image"),
        "records": stories,
        "contract": "保留同花顺 story 原始记录，不用于覆盖开盘啦个股属性。",
    }
    if (story_payload or {}).get("schema_version") == 2:
        story_view.update(
            {
                "source_schema_version": 2,
                "source_url": (story_payload or {}).get("source_url"),
                "source_fetched_at": (story_payload or {}).get("source_fetched_at"),
                "source_components": (story_payload or {}).get("source_components"),
                "stock_records": stock_story_records,
                "contract": (
                    "保留同花顺日级市场叙事和逐股故事原文；"
                    "两者均不用于覆盖开盘啦个股属性。"
                ),
            }
        )

    output = {
        "date": day,
        "coverage": coverage,
        "market": _market_summary(kaipanla, limit_pool),
        "stories": story_view,
        "source_sector_index": _sector_index(kaipanla),
        **(
            {"matching_source_sector_records": matching_sector_records}
            if themes
            else {}
        ),
        "source_theme_index": theme_index,
        "expanded_stock_count": len(expanded_rows),
        "stocks_by_board": dict(
            sorted(
                board_index.items(),
                key=lambda item: (
                    item[0] == "missing",
                    -int(item[0]) if item[0] != "missing" else 0,
                ),
            )
        ),
        "stocks": expanded_rows,
        "source_issues": issues,
    }
    return output, all_records, expanded



def _clean_themes(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values or [] if str(value).strip()}))


def _clean_boards(values: Iterable[int] | None) -> tuple[int, ...]:
    result = set()
    for value in values or []:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("board 必须是大于等于 1 的整数")
        result.add(value)
    return tuple(sorted(result))


def _validate_filters(
    themes: tuple[str, ...],
    theme_match: str,
    boards: tuple[int, ...],
    min_board: int | None,
    max_board: int | None,
) -> None:
    if theme_match not in {"any", "all"}:
        raise ValueError("theme_match 只能是 any 或 all")
    if not themes and theme_match != "any":
        raise ValueError("未传 theme 时不能使用 theme_match=all")
    for name, value in (("min_board", min_board), ("max_board", max_board)):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 1
        ):
            raise ValueError(f"{name} 必须是大于等于 1 的整数")
    if boards and (min_board is not None or max_board is not None):
        raise ValueError("board 不能与 min_board/max_board 同时使用")
    if min_board is not None and max_board is not None and min_board > max_board:
        raise ValueError("min_board 不能大于 max_board")


def _summary_record(record: dict[str, Any]) -> dict[str, Any]:
    facts = record.get("limit_facts") or {}
    attributes = record.get("attributes") or {}
    main_theme = attributes.get("source_main_theme")
    themes = list(
        dict.fromkeys(
            [
                theme
                for theme in [
                    main_theme,
                    *(attributes.get("source_candidate_themes") or []),
                ]
                if theme
            ]
        )
    )
    return {
        "code": record["code"],
        "name": record["name"],
        "boards": facts.get("boards"),
        "board_type": facts.get("board_type"),
        "main_theme": main_theme,
        "themes": themes,
        "first_limit_time": facts.get("first_limit_time"),
    }


def _public_theme_stories(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    records = source.get("records") if isinstance(source.get("records"), list) else []
    return {
        **source,
        "records": [
            {key: field for key, field in record.items() if key != "stocks"}
            for record in records
            if isinstance(record, dict)
        ],
        "contract": "默认展示题材故事；逐股故事按需直接读取当日 canonical 故事记录。",
    }


def _public_day(output: dict[str, Any]) -> dict[str, Any]:
    market = output.get("market") or {}
    market_keys = (
        "kaipanla_stock_count",
        "ths_limit_up_count",
        "first_board_count",
        "higher_board_count",
        "max_boards",
        "max_board_holders",
        "board_counts",
        "market_mood",
        "rise_count",
        "fall_count",
        "source_limit_up_count",
        "source_natural_limit_up_count",
        "limit_down_count",
        "natural_limit_down_count",
    )
    return {
        "date": output["date"],
        "market": {key: market[key] for key in market_keys if key in market},
        "source_sector_index": output.get("source_sector_index") or [],
        "source_theme_index": output.get("source_theme_index") or [],
        "theme_stories": _public_theme_stories(output.get("stories")),
        "expanded_stock_count": output.get("expanded_stock_count") or 0,
        "stocks": [_summary_record(record) for record in output.get("stocks") or []],
        "source_issues": output.get("source_issues") or [],
    }


def build_day_component(day_value: str) -> dict[str, Any]:
    """从 canonical 来源构建完整单日组件，包含原始逐股故事记录。"""
    day = _day(day_value)
    output, _, _ = _build_day(day, ())
    return output


def build_day_facts(
    day_value: str,
    *,
    themes: Iterable[str] | None = None,
    theme_match: str = "any",
    boards: Iterable[int] | None = None,
    min_board: int | None = None,
    max_board: int | None = None,
) -> dict[str, Any]:
    """按日期构建一个交易日的公开事实。

    - 未传筛选：展开当日全市场全部来源股票，包括首板。
    - theme 精确匹配开盘啦主/候选属性；board 精确匹配同花顺板数。
    - 默认视图不展开个股故事，需要时直接读取当日 canonical 故事记录。
    """
    day = _day(day_value)
    requested_themes = _clean_themes(themes)
    requested_boards = _clean_boards(boards)
    _validate_filters(
        requested_themes,
        theme_match,
        requested_boards,
        min_board,
        max_board,
    )
    output, _, _ = _build_day(
        day,
        requested_themes,
        theme_match=theme_match,
        boards=requested_boards,
        min_board=min_board,
        max_board=max_board,
    )
    if not output["coverage"].get("fact_ready"):
        raise ValueError(f"{day} 正式来源数据不完整，不能返回")
    public_day = _public_day(output)
    filters_active = bool(
        requested_themes
        or requested_boards
        or min_board is not None
        or max_board is not None
    )
    return {
        "schema_version": 1,
        "view": "single_day_facts",
        "information_cutoff": day,
        "trade_date": day,
        "scope": {
            "mode": "filtered" if filters_active else "market",
            "themes": list(requested_themes),
            "theme_match": theme_match if requested_themes else None,
            "boards": list(requested_boards),
            "min_board": min_board,
            "max_board": max_board,
            "filter_join": "theme_and_board",
            "contract": "同维度多值按查询模式组合，不同维度取交集。",
        },
        "source_contract": {
            "stock_attributes": "kaipanla theme + themes only",
            "market_and_limit_facts": "tonghuashun limit_pool only",
            "stories": "tonghuashun stories; stock stories remain in the canonical day record",
            "judgement_boundary": "facts_only_no_core_score_or_buy_point",
        },
        "coverage": output["coverage"],
        "day": public_day,
        "navigation": {
            "previous_available_date": _neighbor_day(day, direction=-1),
            "next_available_date": _neighbor_day(day, direction=1),
        },
    }
