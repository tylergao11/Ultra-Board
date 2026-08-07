# -*- coding: utf-8 -*-
"""五日动态事实包。

默认只在每日明细中展开全市场二板及以上，但动态路径会回带被跟踪股票在
窗口内的全部来源状态，因此一进二的首板起点不会被展示阈值截断。传入题材
后返回该题材在窗口内的全部涨停股票。本模块只整理日期 T 及以前的来源事实，
并将相邻市场日观察与可能跨过个股非交易空档的来源连板链分开。本模块不输出
核心、强弱、接力或买点判断。
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
KPL_REQUIRED = (
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


def _window_days(cutoff_value: str, window_size: int) -> list[str]:
    cutoff = _day(cutoff_value)
    if window_size < 1:
        raise ValueError("window_size 必须大于等于 1")
    days = [day for day in available_days() if day <= cutoff]
    if cutoff not in days:
        raise FileNotFoundError(f"日期没有任何本地来源数据: {cutoff}")
    if len(days) < window_size:
        raise ValueError(
            f"{cutoff} 之前只有 {len(days)} 个本地数据日，"
            f"不足 {window_size} 日窗口"
        )
    return days[-window_size:]


def _neighbor_day(day_value: str, *, direction: int) -> str | None:
    day = _day(day_value)
    days = available_days()
    if day not in days:
        return None
    position = days.index(day) + direction
    return days[position] if 0 <= position < len(days) else None


def _coverage(day: str) -> dict[str, Any]:
    directory = KPL_DIR / day
    kpl_missing = [name for name in KPL_REQUIRED if not (directory / name).exists()]
    kpl_ready = directory.is_dir() and not kpl_missing
    limit_ready = (THS_LIMIT_DIR / f"{day}.json").exists()
    story_ready = (THS_STORY_DIR / f"{day}.json").exists()
    return {
        "date": day,
        "kpl_ready": kpl_ready,
        "kpl_missing_files": kpl_missing,
        "ths_limit_pool_ready": limit_ready,
        "ths_story_ready": story_ready,
        "fact_ready": kpl_ready and limit_ready,
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
                "required_for_fact_view": False,
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
    matched_attributes = [
        {
            "theme": theme,
            "membership_source": "main" if theme == main_theme else "candidate",
        }
        for theme in requested_themes
        if theme in candidate_themes
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


def _record_matches(record: dict[str, Any], themes: tuple[str, ...]) -> bool:
    attributes = record.get("attributes")
    if not isinstance(attributes, dict):
        return False
    candidates = set(attributes.get("source_candidate_themes") or [])
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
        for theme in attributes.get("source_candidate_themes") or []:
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
    day_stock_min_boards: int,
) -> dict[str, dict[str, Any]]:
    if themes:
        return {
            code: record
            for code, record in all_records.items()
            if _record_matches(record, themes)
        }
    return {
        code: record
        for code, record in all_records.items()
        if (_limit_boards(record) or 0) >= day_stock_min_boards
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[Any, ...]:
    facts = record.get("limit_facts") or {}
    return (
        -(_limit_boards(record) or 0),
        facts.get("first_limit_ts") is None,
        facts.get("first_limit_ts") or 0,
        record["code"],
    )


def _build_day(
    day: str,
    themes: tuple[str, ...],
    day_stock_min_boards: int,
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
        all_records, themes, day_stock_min_boards
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
    output = {
        "date": day,
        "coverage": _coverage(day),
        "market": _market_summary(kaipanla, limit_pool),
        "stories": {
            "source": (story_payload or {}).get("source"),
            "source_image": (story_payload or {}).get("source_image"),
            "records": stories,
            "contract": "保留同花顺 story 原始记录，不用于覆盖开盘啦个股属性。",
        },
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


def _path_state(
    record: dict[str, Any], *, in_day_stocks: bool
) -> dict[str, Any]:
    facts = record.get("limit_facts") or {}
    attributes = record.get("attributes") or {}
    return {
        "date": record.get("date"),
        "in_day_stocks": in_day_stocks,
        "boards": facts.get("boards"),
        "board_type": facts.get("board_type"),
        "one_price": facts.get("one_price"),
        "first_limit_time": facts.get("first_limit_time"),
        "final_limit_time": facts.get("final_limit_time"),
        "source_main_theme": attributes.get("source_main_theme"),
        "source_candidate_themes": attributes.get("source_candidate_themes") or [],
    }


def _tracked_code_set(
    expanded_by_day: list[dict[str, dict[str, Any]]],
) -> set[str]:
    return {code for rows in expanded_by_day for code in rows}


def _stock_paths(
    days: list[str],
    all_by_day: list[dict[str, dict[str, Any]]],
    expanded_by_day: list[dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    tracked_codes = sorted(_tracked_code_set(expanded_by_day))
    result = []
    for code in tracked_codes:
        records = [rows.get(code) for rows in all_by_day]
        present = [row for row in records if row is not None]
        maximum = max((_limit_boards(row) or 0 for row in present), default=0)
        names = [str(row.get("name") or "").strip() for row in present]
        names = [name for name in names if name]
        result.append(
            {
                "code": code,
                "name": names[-1] if names else "",
                "expanded_in_day_stocks_on": [
                    day
                    for day, rows in zip(days, expanded_by_day)
                    if code in rows
                ],
                "states_aligned_to_trade_dates": [
                    (
                        _path_state(
                            row,
                            in_day_stocks=code in expanded_by_day[index],
                        )
                        if row is not None
                        else None
                    )
                    for index, row in enumerate(records)
                ],
                "max_boards_in_window": maximum or None,
            }
        )
    result.sort(
        key=lambda row: (-(row["max_boards_in_window"] or 0), row["code"])
    )
    return result


def _board_sequence_facts(
    days: list[str],
    all_by_day: list[dict[str, dict[str, Any]]],
    expanded_by_day: list[dict[str, dict[str, Any]]],
) -> list[dict[str, Any]]:
    """构建个股来源连板链；它与相邻市场日观察链是两套独立事实。"""
    positions = {day: index for index, day in enumerate(days)}
    tracked_codes = _tracked_code_set(expanded_by_day)
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_edge(
        code: str,
        name: str,
        from_date: str,
        to_date: str,
        from_boards: int,
        to_boards: int,
        evidence_basis: str,
        evidence_as_of_date: str,
    ) -> None:
        if from_date not in positions or to_date not in positions:
            return
        from_position = positions[from_date]
        to_position = positions[to_date]
        if from_position >= to_position or to_boards != from_boards + 1:
            raise ValueError(
                "同花顺连板日期链顺序异常: "
                f"{code} {from_date}/{from_boards} -> {to_date}/{to_boards}"
            )
        key = (code, from_date, to_date)
        existing = edges.get(key)
        if existing is None:
            intervening = days[from_position + 1:to_position]
            existing = {
                "code": code,
                "name": name,
                "from_date": from_date,
                "to_date": to_date,
                "from_boards": from_boards,
                "to_boards": to_boards,
                "board_transition": f"{from_boards}_to_{to_boards}",
                "intervening_window_trade_dates": intervening,
                "crosses_window_trade_date_gap": bool(intervening),
                "_evidence_basis": set(),
                "_evidence_as_of_dates": set(),
            }
            edges[key] = existing
        elif (
            existing["from_boards"] != from_boards
            or existing["to_boards"] != to_boards
        ):
            raise ValueError(
                "同一连板边存在冲突: "
                f"{code} {from_date} -> {to_date}"
            )
        existing["_evidence_basis"].add(evidence_basis)
        existing["_evidence_as_of_dates"].add(evidence_as_of_date)

    for code in sorted(tracked_codes):
        records = [rows.get(code) for rows in all_by_day]
        for index in range(1, len(days)):
            before_boards = _limit_boards(records[index - 1])
            after_boards = _limit_boards(records[index])
            if (
                before_boards is not None
                and after_boards == before_boards + 1
            ):
                add_edge(
                    code,
                    str((records[index] or records[index - 1] or {}).get("name") or ""),
                    days[index - 1],
                    days[index],
                    before_boards,
                    after_boards,
                    "adjacent_daily_board_facts",
                    days[index],
                )

        for record in records:
            facts = (record or {}).get("limit_facts")
            trace = (
                facts.get("consecutive_limit_up_dates")
                if isinstance(facts, dict)
                else None
            )
            if not isinstance(trace, list) or len(trace) < 2:
                continue
            for from_boards, (from_date, to_date) in enumerate(
                zip(trace, trace[1:]), start=1
            ):
                if from_date not in positions or to_date not in positions:
                    continue
                to_boards = from_boards + 1
                from_observed = _limit_boards(
                    all_by_day[positions[from_date]].get(code)
                )
                to_observed = _limit_boards(
                    all_by_day[positions[to_date]].get(code)
                )
                if from_observed not in (None, from_boards) or to_observed not in (
                    None,
                    to_boards,
                ):
                    raise ValueError(
                        "同花顺连板日期链与逐日板数冲突: "
                        f"{code} {from_date}/{from_observed} -> "
                        f"{to_date}/{to_observed}, trace={trace!r}"
                    )
                add_edge(
                    code,
                    str((record or {}).get("name") or ""),
                    from_date,
                    to_date,
                    from_boards,
                    to_boards,
                    "ths_consecutive_limit_up_dates",
                    str((record or {}).get("date") or ""),
                )

    basis_order = {
        "ths_consecutive_limit_up_dates": 0,
        "adjacent_daily_board_facts": 1,
    }
    result = []
    for edge in edges.values():
        evidence_basis = sorted(
            edge.pop("_evidence_basis"),
            key=lambda value: basis_order.get(value, 99),
        )
        evidence_as_of_dates = sorted(edge.pop("_evidence_as_of_dates"))
        result.append(
            {
                **edge,
                "evidence_basis": evidence_basis,
                "evidence_as_of_dates": evidence_as_of_dates,
            }
        )
    result.sort(
        key=lambda row: (
            row["to_date"],
            -row["to_boards"],
            row["from_date"],
            row["code"],
        )
    )
    return result


def _day_view_exclusion(
    record: dict[str, Any] | None,
    themes: tuple[str, ...],
    day_stock_min_boards: int,
) -> str | None:
    if record is None:
        return "not_in_daily_source_stock_union"
    if themes:
        return (
            "source_attribute_not_matched"
            if not _record_matches(record, themes)
            else None
        )
    boards = _limit_boards(record)
    if boards is None:
        return "missing_ths_board_facts"
    if boards < day_stock_min_boards:
        return "not_expanded_below_default_day_threshold"
    return None


def _transition_state(
    record: dict[str, Any] | None, *, in_day_stocks: bool
) -> dict[str, Any] | None:
    return (
        _path_state(record, in_day_stocks=in_day_stocks)
        if record is not None
        else None
    )


def _source_attribute_change(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    before_attributes = (before or {}).get("attributes")
    after_attributes = (after or {}).get("attributes")
    missing_sides = []
    if not isinstance(before_attributes, dict):
        missing_sides.append("from")
    if not isinstance(after_attributes, dict):
        missing_sides.append("to")
    if missing_sides:
        return {
            "comparison_status": "not_comparable_missing_source_attributes",
            "missing_sides": missing_sides,
            "added": None,
            "removed": None,
        }
    before_themes = set(
        before_attributes.get("source_candidate_themes") or []
    )
    after_themes = set(
        after_attributes.get("source_candidate_themes") or []
    )
    return {
        "comparison_status": "comparable",
        "missing_sides": [],
        "added": sorted(after_themes - before_themes),
        "removed": sorted(before_themes - after_themes),
    }


def _transitions(
    days: list[str],
    all_by_day: list[dict[str, dict[str, Any]]],
    expanded_by_day: list[dict[str, dict[str, Any]]],
    themes: tuple[str, ...],
    day_stock_min_boards: int,
) -> list[dict[str, Any]]:
    result = []
    tracked_codes = _tracked_code_set(expanded_by_day)
    for index in range(1, len(days)):
        previous_all = all_by_day[index - 1]
        current_all = all_by_day[index]
        previous_expanded = expanded_by_day[index - 1]
        current_expanded = expanded_by_day[index]
        codes = sorted(
            code
            for code in tracked_codes
            if code in previous_all or code in current_all
        )
        facts = []
        for code in codes:
            before_expanded = code in previous_expanded
            after_expanded = code in current_expanded
            before = previous_all.get(code)
            after = current_all.get(code)
            if before_expanded and after_expanded:
                day_view_change = "remained_expanded"
            elif after_expanded:
                day_view_change = "entered_expanded_view"
            elif before_expanded:
                day_view_change = "left_expanded_view"
            else:
                day_view_change = "not_expanded_on_either_day"

            before_boards = _limit_boards(before)
            after_boards = _limit_boards(after)
            facts.append(
                {
                    "code": code,
                    "name": (after or before or {}).get("name"),
                    "day_stock_view": {
                        "change": day_view_change,
                        "from_expanded": before_expanded,
                        "to_expanded": after_expanded,
                        "from_not_expanded_reason": (
                            None
                            if before_expanded
                            else _day_view_exclusion(
                                before, themes, day_stock_min_boards
                            )
                        ),
                        "to_not_expanded_reason": (
                            None
                            if after_expanded
                            else _day_view_exclusion(
                                after, themes, day_stock_min_boards
                            )
                        ),
                    },
                    "from": _transition_state(
                        before, in_day_stocks=before_expanded
                    ),
                    "to": _transition_state(
                        after, in_day_stocks=after_expanded
                    ),
                    "board_transition": (
                        f"{before_boards}_to_{after_boards}"
                        if before_boards is not None
                        and after_boards is not None
                        else None
                    ),
                    "boards_change": (
                        after_boards - before_boards
                        if before_boards is not None and after_boards is not None
                        else None
                    ),
                    "source_attribute_change": _source_attribute_change(
                        before, after
                    ),
                }
            )
        result.append(
            {
                "from_date": days[index - 1],
                "to_date": days[index],
                "facts": facts,
            }
        )
    return result


def _clean_themes(values: Iterable[str] | None) -> tuple[str, ...]:
    return tuple(sorted({str(value).strip() for value in values or [] if str(value).strip()}))


def build_replay(
    cutoff_value: str,
    *,
    themes: Iterable[str] | None = None,
    window_size: int = 5,
    include_all_first_boards: bool = False,
) -> dict[str, Any]:
    """构建截至 T 日的动态事实包。

    - 未传题材：每日明细默认展开全市场二板及以上；动态路径会回带这些
      股票在窗口内的首板状态。
    - 传入题材：精确匹配开盘啦主/候选属性，返回该题材全部板数。
    - ``include_all_first_boards``：显式请求全市场全部涨停时使用。
    """
    cutoff = _day(cutoff_value)
    requested_themes = _clean_themes(themes)
    days = _window_days(cutoff, window_size)
    day_stock_min_boards = (
        1 if requested_themes or include_all_first_boards else 2
    )

    day_outputs = []
    all_by_day = []
    expanded_by_day = []
    for day in days:
        output, all_records, expanded = _build_day(
            day, requested_themes, day_stock_min_boards
        )
        day_outputs.append(output)
        all_by_day.append(all_records)
        expanded_by_day.append(expanded)

    coverage_days = [output["coverage"] for output in day_outputs]
    return {
        "schema_version": 1,
        "view": "five_day_dynamic_facts",
        "information_cutoff": cutoff,
        "trade_dates": days,
        "window_start_boundary": "outside_window_unknown",
        "scope": {
            "mode": (
                "theme"
                if requested_themes
                else (
                    "market_all_boards"
                    if include_all_first_boards
                    else "market_default"
                )
            ),
            "themes": list(requested_themes),
            "theme_match": (
                "exact_any_in_kaipanla_main_or_candidates"
                if requested_themes
                else None
            ),
            "day_stock_min_boards": day_stock_min_boards,
            "first_boards_expanded_in_day_stocks": (
                day_stock_min_boards == 1
            ),
            "path_tracking": (
                "all_available_window_states_for_codes_expanded_in_any_day_stocks"
            ),
            "contract": (
                "传入题材后返回该题材全部板数。"
                if requested_themes
                else (
                    "显式展开全市场全部板数。"
                    if include_all_first_boards
                    else (
                        "每日明细默认只展开全市场二板及以上；动态路径从首板开始，"
                        "并回带被跟踪股票在窗口内的首板事实。"
                    )
                )
            ),
        },
        "source_contract": {
            "stock_attributes": "kaipanla theme + themes only",
            "market_and_limit_facts": "tonghuashun limit_pool only",
            "board_sequence": (
                "tonghuashun boards + consecutive_limit_up_dates; "
                "market-date gaps are not auto-labelled suspension"
            ),
            "daily_absence": (
                "not in daily source union is unknown, not failure or suspension"
            ),
            "stories": "tonghuashun story records, context does not classify stocks",
            "judgement_boundary": "facts_only_no_core_score_or_buy_point",
        },
        "coverage": {
            "status": (
                "complete"
                if all(row["fact_ready"] for row in coverage_days)
                else "partial"
            ),
            "story_status": (
                "complete"
                if all(row["ths_story_ready"] for row in coverage_days)
                else "partial"
            ),
            "days": coverage_days,
        },
        "days": day_outputs,
        "stock_paths": _stock_paths(
            days, all_by_day, expanded_by_day
        ),
        "board_sequence_facts": _board_sequence_facts(
            days, all_by_day, expanded_by_day
        ),
        "transition_facts": _transitions(
            days,
            all_by_day,
            expanded_by_day,
            requested_themes,
            day_stock_min_boards,
        ),
        "continuation": {
            "cursor": cutoff,
            "previous_available_date": _neighbor_day(cutoff, direction=-1),
            "next_available_date": _neighbor_day(cutoff, direction=1),
            "query_scope": {
                "themes": list(requested_themes),
                "include_all_first_boards": include_all_first_boards,
                "window_size": window_size,
            },
        },
    }


def build_next_replay(
    cursor_value: str,
    *,
    themes: Iterable[str] | None = None,
    window_size: int = 5,
    include_all_first_boards: bool = False,
) -> dict[str, Any]:
    """沿相同查询范围推进到下一个本地数据日。"""
    cursor = _day(cursor_value)
    next_day = _neighbor_day(cursor, direction=1)
    if next_day is None:
        raise ValueError(f"{cursor} 之后没有可用的本地数据日")
    payload = build_replay(
        next_day,
        themes=themes,
        window_size=window_size,
        include_all_first_boards=include_all_first_boards,
    )
    payload["advanced_from_information_cutoff"] = cursor
    return payload
