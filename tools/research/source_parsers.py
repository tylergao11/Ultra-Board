"""Read-only parsers for the Kaipanla research source files.

The public functions in this module yield plain dictionaries so that callers
can stream records into SQLite without retaining records from multiple files.
Each JSON document is loaded and released independently.  The parsers expose
source facts only: rule thresholds and research conclusions belong to callers.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Iterator, Mapping, Sequence


SHANGHAI_TZ = timezone(timedelta(hours=8))
LIMIT_PERFORMANCE_PATTERN = re.compile(r"^limit_performance_(\d+)\.json$")

# Positional schemas retained by the Kaipanla raw responses.
HISTORICAL_ROW = {
    "stock_code": 0,
    "stock_name": 1,
    "event_timestamp": 6,
    "board_description": 9,
    "board_height": 10,
    "topic_tags": 11,
    "topic": 16,
    "description": 17,
}
LIMIT_PERFORMANCE_ROW = {
    "stock_code": 0,
    "stock_name": 1,
    "event_timestamp": 4,
    "topic": 5,
    "topic_tags": 12,
    "board_height": 15,
    "source_state": 16,
    "source_metric": 17,
    "board_description": 18,
    "sector_code": 19,
    "source_pid": 20,
    "price": 21,
    "limit_pct": 22,
}

PathLike = str | Path
Fact = dict[str, Any]


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _as_path(path: PathLike) -> Path:
    return Path(path)


def _source_path(path: Path, source_root: PathLike | None) -> str:
    if source_root is not None:
        try:
            return path.resolve().relative_to(_as_path(source_root).resolve()).as_posix()
        except ValueError:
            pass
    return path.as_posix()


def _source_fields(
    path: Path,
    raw_location: str,
    source_root: PathLike | None,
) -> Fact:
    source_path = _source_path(path, source_root)
    return {
        "source_path": source_path,
        "raw_location": raw_location,
        "source_ref": f"{source_path}#{raw_location}",
    }


def _value(row: Sequence[Any], index: int, default: Any = None) -> Any:
    return row[index] if index < len(row) else default


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _timestamp_fields(value: Any) -> Fact:
    timestamp = _integer(value)
    if timestamp is None or timestamp <= 0:
        return {
            "event_timestamp": timestamp,
            "event_datetime": None,
            "event_time": None,
        }
    moment = datetime.fromtimestamp(timestamp, tz=SHANGHAI_TZ)
    return {
        "event_timestamp": timestamp,
        "event_datetime": moment.isoformat(),
        "event_time": moment.strftime("%H:%M:%S"),
    }


def _document_date(document: Mapping[str, Any], path: Path) -> str | None:
    value = document.get("date")
    if isinstance(value, str) and value:
        return value
    if path.parent.name and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.parent.name):
        return path.parent.name
    return None


def _row_fact(row: Sequence[Any], schema: Mapping[str, int]) -> Fact:
    fact = {name: _value(row, index) for name, index in schema.items()}
    fact["stock_code"] = str(fact.get("stock_code") or "")
    fact["stock_name"] = str(fact.get("stock_name") or "")
    fact["board_height"] = _integer(fact.get("board_height"))
    timestamp = fact.pop("event_timestamp", None)
    fact.update(_timestamp_fields(timestamp))
    return fact


def iter_historical_message_facts(
    path: PathLike,
    *,
    source_root: PathLike | None = None,
) -> Iterator[Fact]:
    """Yield stock message/announcement-source facts from one source file."""

    source = _as_path(path)
    document = _load_json(source)
    source_date = _document_date(document, source)
    sectors = document.get("list") if isinstance(document, Mapping) else None
    if not isinstance(sectors, list):
        return

    for sector_index, sector in enumerate(sectors):
        if not isinstance(sector, Mapping):
            continue
        stocks = sector.get("StockList")
        if not isinstance(stocks, list):
            continue
        for stock_index, row in enumerate(stocks):
            if not isinstance(row, list):
                continue
            location = f"list[{sector_index}].StockList[{stock_index}]"
            fact = _row_fact(row, HISTORICAL_ROW)
            fact.update(
                {
                    "fact_type": "message_source",
                    "source_kind": "kaipanla_historical_messages",
                    "source_date": source_date,
                    "sector_code": str(sector.get("ZSCode") or ""),
                    "sector_name": str(sector.get("ZSName") or ""),
                    "sector_explanation": sector.get("TCExplain"),
                    "sector_group": sector.get("GroupStr"),
                    "raw": row,
                }
            )
            fact.update(_source_fields(source, location, source_root))
            yield fact


def _ladder_member_fields(member: Mapping[str, Any]) -> Fact:
    raw = member.get("raw")
    row_fact: Fact = {}
    if isinstance(raw, list):
        row_fact = _row_fact(raw, HISTORICAL_ROW)
    return {
        "stock_code": str(member.get("code") or row_fact.get("stock_code") or ""),
        "stock_name": str(member.get("name") or row_fact.get("stock_name") or ""),
        "tips": member.get("tips"),
        "board_height": row_fact.get("board_height"),
        "board_description": row_fact.get("board_description") or member.get("tips"),
        "topic": row_fact.get("topic"),
        "topic_tags": row_fact.get("topic_tags"),
        "description": row_fact.get("description"),
        "event_timestamp": row_fact.get("event_timestamp"),
        "event_datetime": row_fact.get("event_datetime"),
        "event_time": row_fact.get("event_time"),
        "raw": raw if isinstance(raw, list) else dict(member),
    }


def iter_sector_ladder_facts(
    path: PathLike,
    *,
    source_root: PathLike | None = None,
) -> Iterator[Fact]:
    """Yield tier and fanbao membership facts from one sector ladder file."""

    source = _as_path(path)
    document = _load_json(source)
    source_date = _document_date(document, source)
    sectors = document.get("sectors") if isinstance(document, Mapping) else None
    if not isinstance(sectors, list):
        return

    for sector_index, sector in enumerate(sectors):
        if not isinstance(sector, Mapping):
            continue
        sector_fields = {
            "sector_code": str(sector.get("code") or ""),
            "sector_name": str(sector.get("name") or ""),
            "sector_count": _integer(sector.get("count")),
            "sector_source_position": sector.get("source_position"),
            "sector_source_meta": sector.get("source_meta"),
        }
        tiers = sector.get("tiers")
        if isinstance(tiers, Mapping):
            for tier_key, members in tiers.items():
                if not isinstance(members, list):
                    continue
                for member_index, member in enumerate(members):
                    if not isinstance(member, Mapping):
                        continue
                    location = f"sectors[{sector_index}].tiers.{tier_key}[{member_index}]"
                    fact = _ladder_member_fields(member)
                    fact.update(
                        {
                            "fact_type": "sector_tier_membership",
                            "source_kind": "kaipanla_sector_ladder",
                            "source_date": source_date,
                            "tier_kind": "height",
                            "tier_key": str(tier_key),
                            "tier_height": _integer(tier_key),
                            **sector_fields,
                        }
                    )
                    if fact.get("board_height") is None:
                        fact["board_height"] = fact["tier_height"]
                    fact.update(_source_fields(source, location, source_root))
                    yield fact

        fanbao = sector.get("fanbao")
        if isinstance(fanbao, list):
            for member_index, member in enumerate(fanbao):
                if not isinstance(member, Mapping):
                    continue
                location = f"sectors[{sector_index}].fanbao[{member_index}]"
                fact = _ladder_member_fields(member)
                fact.update(
                    {
                        "fact_type": "sector_fanbao_membership",
                        "source_kind": "kaipanla_sector_ladder",
                        "source_date": source_date,
                        "tier_kind": "fanbao",
                        "tier_key": "fanbao",
                        "tier_height": None,
                        **sector_fields,
                    }
                )
                fact.update(_source_fields(source, location, source_root))
                yield fact

    fanbao_all = document.get("fanbao_all") if isinstance(document, Mapping) else None
    if isinstance(fanbao_all, list):
        for member_index, member in enumerate(fanbao_all):
            if not isinstance(member, Mapping):
                continue
            location = f"fanbao_all[{member_index}]"
            fact = _ladder_member_fields(member)
            fact.update(
                {
                    "fact_type": "market_fanbao_membership",
                    "source_kind": "kaipanla_sector_ladder",
                    "source_date": source_date,
                    "tier_kind": "fanbao_all",
                    "tier_key": "fanbao_all",
                    "tier_height": None,
                    "sector_code": str(member.get("sector_code") or ""),
                    "sector_name": str(member.get("sector") or ""),
                }
            )
            fact.update(_source_fields(source, location, source_root))
            yield fact


def _performance_group(path: Path) -> int | None:
    match = LIMIT_PERFORMANCE_PATTERN.fullmatch(path.name)
    return int(match.group(1)) if match else None


def iter_limit_performance_facts(
    path: PathLike,
    *,
    source_root: PathLike | None = None,
) -> Iterator[Fact]:
    """Yield source rows from one ``limit_performance_*.json`` document."""

    source = _as_path(path)
    document = _load_json(source)
    if not isinstance(document, Mapping):
        return
    info = document.get("info")
    if not isinstance(info, list) or not info:
        return
    rows = info[0]
    if not isinstance(rows, list):
        return
    source_date = info[1] if len(info) > 1 and isinstance(info[1], str) else None
    source_date = source_date or _document_date(document, source)
    group = _performance_group(source)

    for row_index, row in enumerate(rows):
        if not isinstance(row, list):
            continue
        location = f"info[0][{row_index}]"
        fact = _row_fact(row, LIMIT_PERFORMANCE_ROW)
        fact.update(
            {
                "fact_type": "limit_performance",
                "source_kind": "kaipanla_limit_performance",
                "source_date": source_date,
                "performance_group": group,
                "raw": row,
            }
        )
        fact.update(_source_fields(source, location, source_root))
        yield fact


def iter_limit_performance_files(
    day_directory: PathLike,
    *,
    source_root: PathLike | None = None,
) -> Iterator[Fact]:
    """Yield every performance row for a day, one input file at a time."""

    day_path = _as_path(day_directory)
    for source in sorted(day_path.glob("limit_performance_*.json")):
        yield from iter_limit_performance_facts(source, source_root=source_root)


def iter_absent_continuation_facts(
    prior_performance_paths: Iterable[PathLike],
    current_limit_codes: Iterable[str],
    *,
    current_date: str,
    minimum_prior_height: int,
    source_root: PathLike | None = None,
) -> Iterator[Fact]:
    """Yield prior-height stocks absent from a supplied current limit-up set.

    This is the source fact used to assemble a broken-high pool.  The caller
    supplies both the height threshold and the actual next trading date, so
    this function contains no calendar assumptions or stock-level decisions.
    """

    limit_codes = {str(code) for code in current_limit_codes if str(code)}
    seen: set[str] = set()
    for path in prior_performance_paths:
        for prior in iter_limit_performance_facts(path, source_root=source_root):
            stock_code = prior.get("stock_code")
            height = _integer(prior.get("board_height"))
            if not stock_code or stock_code in seen:
                continue
            if height is None or height < minimum_prior_height or stock_code in limit_codes:
                continue
            seen.add(stock_code)
            fact = dict(prior)
            fact.update(
                {
                    "fact_type": "limit_continuation_absence",
                    "prior_source_date": prior.get("source_date"),
                    "source_date": current_date,
                    "prior_board_height": height,
                    "minimum_prior_height": minimum_prior_height,
                    "present_in_current_limit_pool": False,
                }
            )
            yield fact


def iter_day_source_facts(
    day_directory: PathLike,
    *,
    source_root: PathLike | None = None,
) -> Iterator[Fact]:
    """Yield supported same-day source facts, reading each file independently."""

    day_path = _as_path(day_directory)
    historical = day_path / "historical_messages.json"
    if historical.is_file():
        yield from iter_historical_message_facts(historical, source_root=source_root)
    ladder = day_path / "sector_ladder.json"
    if ladder.is_file():
        yield from iter_sector_ladder_facts(ladder, source_root=source_root)
    yield from iter_limit_performance_files(day_path, source_root=source_root)


def _select_day(raw_root: Path, requested: str | None) -> Path:
    if requested:
        day = raw_root / requested
        if not day.is_dir():
            raise FileNotFoundError(f"sample date directory not found: {day}")
        return day
    days = sorted(
        path
        for path in raw_root.iterdir()
        if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)
    )
    if not days:
        raise FileNotFoundError(f"no dated source directories below: {raw_root}")
    return days[-1]


def _self_check(raw_root: Path, sample_date: str | None, all_dates: bool) -> int:
    days = (
        sorted(
            path
            for path in raw_root.iterdir()
            if path.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.name)
        )
        if all_dates
        else [_select_day(raw_root, sample_date)]
    )
    counts: Counter[str] = Counter()
    file_kinds: Counter[str] = Counter()
    examples: dict[str, Fact] = {}
    required = {"source_date", "source_path", "raw_location", "source_ref"}

    for day in days:
        for fact in iter_day_source_facts(day, source_root=raw_root.parent.parent.parent):
            missing = sorted(required.difference(fact))
            if missing:
                raise ValueError(f"missing fields {missing}: {fact.get('source_ref')}")
            fact_type = str(fact["fact_type"])
            counts[fact_type] += 1
            file_kinds[str(fact["source_kind"])] += 1
            examples.setdefault(
                fact_type,
                {
                    key: fact.get(key)
                    for key in (
                        "source_date",
                        "stock_code",
                        "stock_name",
                        "topic",
                        "event_time",
                        "source_ref",
                    )
                },
            )

    result = {
        "days_checked": len(days),
        "first_day": days[0].name if days else None,
        "last_day": days[-1].name if days else None,
        "facts_by_type": dict(sorted(counts.items())),
        "facts_by_source": dict(sorted(file_kinds.items())),
        "examples": examples,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Kaipanla source parser check")
    parser.add_argument(
        "--raw-root",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "kaipanla" / "raw",
    )
    parser.add_argument("--sample-date", help="dated directory below --raw-root")
    parser.add_argument(
        "--all-dates",
        action="store_true",
        help="check every dated directory instead of one sample date",
    )
    args = parser.parse_args(argv)
    return _self_check(args.raw_root, args.sample_date, args.all_dates)


if __name__ == "__main__":
    raise SystemExit(main())
