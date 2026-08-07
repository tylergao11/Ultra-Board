# -*- coding: utf-8 -*-
"""只读的跨日板上路径、身位竞争与节点记忆池证据。

这个工具不识别核心、不评分、不输出买点。所有入口都必须显式提供
``information_cutoff``，并且只读取截止日及以前的数据。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ultraboard.kaipanla import load_day as load_kaipanla_day  # noqa: E402
from ultraboard.ths.limit_pool import load_day as load_limit_day  # noqa: E402
from ultraboard.ths.stories import load_day as load_story_day  # noqa: E402


LIMIT_DIR = ROOT / "data" / "ths" / "limit_pool"
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CN_TZ = timezone(timedelta(hours=8))


def _day(value: str) -> str:
    return date.fromisoformat(value).isoformat()


def _code(value: Any) -> str:
    text = str(value or "").strip()
    return text.zfill(6) if text.isdigit() and len(text) <= 6 else text


def _available_days(cutoff: str, start: str | None = None) -> list[str]:
    cutoff_day = _day(cutoff)
    start_day = _day(start) if start else None
    days = []
    for path in LIMIT_DIR.glob("*.json"):
        candidate = path.stem
        if not DAY_RE.fullmatch(candidate) or candidate > cutoff_day:
            continue
        if start_day and candidate < start_day:
            continue
        days.append(candidate)
    return sorted(days)


def _limit_payload(day: str) -> dict[str, Any]:
    payload = load_limit_day(day)
    if payload is None:
        raise FileNotFoundError(LIMIT_DIR / f"{day}.json")
    return payload


def _limit_map(day: str) -> dict[str, dict[str, Any]]:
    return {_code(row["code"]): row for row in _limit_payload(day)["stocks"]}


def _classification_map(day: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    try:
        payload = load_kaipanla_day(day)
    except FileNotFoundError:
        return {}, [f"{day} 缺少开盘啦分类，未补造题材"]
    result: dict[str, dict[str, Any]] = {}
    for row in payload["stocks"]:
        code = _code(row.get("code"))
        result[code] = {
            "main_theme": str(row.get("theme") or "").strip() or None,
            "themes": list(row.get("themes") or []),
        }
    return result, []


def _story_records(day: str) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        payload = load_story_day(day)
    except FileNotFoundError:
        return [], [f"{day} 同花顺标题后半句尚未人工录入"]
    stories = [
        {
            "source_position": row["source_position"],
            "story": row["story"],
            "headline": row["headline"],
        }
        for row in payload["stories"]
    ]
    return stories, []


def _time_text(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, CN_TZ).strftime("%H:%M:%S")


def _clock_seconds(timestamp: int) -> int:
    current = datetime.fromtimestamp(timestamp, CN_TZ)
    return current.hour * 3600 + current.minute * 60 + current.second


def _stock_fact(
    day: str,
    row: dict[str, Any],
    classification: dict[str, Any] | None,
) -> dict[str, Any]:
    first_ts = int(row["first_limit_ts"])
    final_ts = int(row["final_limit_ts"])
    return {
        "date": day,
        "code": _code(row["code"]),
        "name": row["name"],
        "boards": row["boards"],
        "boards_desc": row["boards_desc"],
        "main_theme": classification.get("main_theme") if classification else None,
        "themes": list(classification.get("themes") or []) if classification else [],
        "price": row.get("price"),
        "circulating_market_cap": row.get("circulating_market_cap"),
        "turnover_rate": row.get("turnover_rate"),
        "seal_order_ratio": row.get("seal_order_ratio"),
        "first_limit_time": _time_text(first_ts),
        "final_limit_time": _time_text(final_ts),
        "seal_span_seconds": final_ts - first_ts,
        "open_count": row["open_count"],
        "board_type": row["board_type"],
        "one_price": row["one_price"],
    }


def _relation(
    previous: dict[str, Any],
    current: dict[str, Any],
    trading_day_gap: int,
) -> dict[str, Any]:
    previous_turnover = previous.get("turnover_rate")
    current_turnover = current.get("turnover_rate")
    turnover_multiple = None
    if (
        isinstance(previous_turnover, (int, float))
        and previous_turnover > 0
        and isinstance(current_turnover, (int, float))
    ):
        turnover_multiple = current_turnover / previous_turnover
    return {
        "from_date": previous["date"],
        "to_date": current["date"],
        "trading_day_gap": trading_day_gap,
        "absence_trading_days_before": max(0, trading_day_gap - 1),
        "appearance_kind": (
            "continuous_limit_path" if trading_day_gap == 1 else "reactivation"
        ),
        "boards_change": current["boards"] - previous["boards"],
        "first_limit_shift_seconds": (
            _clock_seconds_from_text(current["first_limit_time"])
            - _clock_seconds_from_text(previous["first_limit_time"])
        ),
        "final_limit_shift_seconds": (
            _clock_seconds_from_text(current["final_limit_time"])
            - _clock_seconds_from_text(previous["final_limit_time"])
        ),
        "turnover_multiple": turnover_multiple,
        "one_price_transition": (
            f"{str(previous['one_price']).lower()}->"
            f"{str(current['one_price']).lower()}"
        ),
        "new_themes_vs_previous": [
            theme for theme in current["themes"] if theme not in previous["themes"]
        ],
    }


def _clock_seconds_from_text(value: str) -> int:
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60 + second


def build_stock_path(
    code_value: str,
    cutoff_value: str,
    start_value: str | None = None,
) -> dict[str, Any]:
    code = _code(code_value)
    cutoff = _day(cutoff_value)
    start = _day(start_value) if start_value else None
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("股票代码必须是六位数字")
    if start and start > cutoff:
        raise ValueError("--start 不能晚于 information_cutoff")

    market_days = _available_days(cutoff, start)
    day_index = {day: index for index, day in enumerate(market_days)}
    appearances: list[dict[str, Any]] = []
    warnings: list[str] = []
    for day in market_days:
        row = _limit_map(day).get(code)
        if row is None:
            continue
        classes, day_warnings = _classification_map(day)
        warnings.extend(day_warnings)
        appearances.append(_stock_fact(day, row, classes.get(code)))

    if not appearances:
        raise ValueError(f"截止 {cutoff} 的同花顺涨停池中未找到 {code}")

    relations = []
    for previous, current in zip(appearances, appearances[1:]):
        relations.append(
            _relation(
                previous,
                current,
                day_index[current["date"]] - day_index[previous["date"]],
            )
        )
    return {
        "view": "stock_path",
        "information_cutoff": cutoff,
        "source_contract": {
            "classification": "kaipanla T and earlier",
            "market_and_board_facts": "tonghuashun limit_pool T and earlier",
        },
        "code": code,
        "name": appearances[-1]["name"],
        "data_days_used": [row["date"] for row in appearances],
        "appearances": appearances,
        "relations": relations,
        "judgement_boundary": (
            "只展示跨日变化，不把首封提前、缩量或换手自动命名为加速、分歧或核心。"
        ),
        "warnings": sorted(set(warnings)),
    }


def _shared_themes(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    right_themes = set(right.get("themes") or [])
    return [theme for theme in left.get("themes") or [] if theme in right_themes]


def _decorated_day(day: str) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows = _limit_map(day)
    classes, warnings = _classification_map(day)
    return {
        code: _stock_fact(day, row, classes.get(code))
        for code, row in rows.items()
    }, warnings


def _position_peers(
    research: list[dict[str, Any]],
    guide: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    shared_attribute_peers = []
    story_attribution_peers = []
    for peer in research:
        if peer["code"] == guide["code"] or peer["one_price"]:
            continue
        if peer["boards"] != guide["boards"]:
            continue
        shared = _shared_themes(guide, peer)
        record = {"stock": peer, "shared_themes": shared}
        if shared:
            shared_attribute_peers.append(record)
        else:
            record["relation_status"] = (
                "source_attributes_do_not_overlap; visible_story_may_still_link_them"
            )
            story_attribution_peers.append(record)
    return shared_attribute_peers, story_attribution_peers


def build_position_competition(day_value: str) -> dict[str, Any]:
    day = _day(day_value)
    days = _available_days(day)
    if day not in days:
        raise FileNotFoundError(LIMIT_DIR / f"{day}.json")
    position = days.index(day)
    previous_day = days[position - 1] if position > 0 else None
    current, warnings = _decorated_day(day)
    previous: dict[str, dict[str, Any]] = {}
    if previous_day:
        previous, previous_warnings = _decorated_day(previous_day)
        warnings.extend(previous_warnings)

    research = [row for row in current.values() if row["boards"] >= 2]
    research.sort(
        key=lambda row: (-row["boards"], row["first_limit_time"], row["code"])
    )

    locked_guides = []
    for guide in (row for row in research if row["one_price"]):
        shared_peers, story_peers = _position_peers(research, guide)
        locked_guides.append(
            {
                "guide": guide,
                "same_position_shared_attribute_peers": shared_peers,
                "same_position_story_attribution_peers": story_peers,
            }
        )

    opened_guides = []
    failed_guides = []
    if previous_day:
        for previous_guide in previous.values():
            if previous_guide["boards"] < 2 or not previous_guide["one_price"]:
                continue
            current_guide = current.get(previous_guide["code"])
            if current_guide is None:
                failed_guides.append(previous_guide)
                continue
            if current_guide["one_price"]:
                continue
            shared_peers, story_peers = _position_peers(research, current_guide)
            opened_guides.append(
                {
                    "previous_locked_state": previous_guide,
                    "current_turnover_state": current_guide,
                    "same_position_shared_attribute_peers": shared_peers,
                    "same_position_story_attribution_peers": story_peers,
                }
            )

    return {
        "view": "position_competition",
        "information_cutoff": day,
        "previous_trading_day": previous_day,
        "decision_contract": {
            "locked_guide": "核心仍买不到时，同身位换手票只进入候选，不自动产生买点。",
            "opened_guide": "前一日一字票今日开门时，优先重新评估其自身换手，不把竞争者自动置顶。",
            "failed_guide": "一字票确认失败后，竞争者必须证明独立分离与带动。",
            "dynamic_story": (
                "源属性不重合的同身位票仍保留展示；是否被当日故事临时连接由人工依据可见标题判断，脚本不做关键词映射。"
            ),
            "auction_gap": "历史封单增减与竞价成交路径当前缺失，不在本视图中推断。",
        },
        "current_locked_guides": locked_guides,
        "previous_guides_opened_today": opened_guides,
        "previous_guides_failed_to_limit_today": failed_guides,
        "warnings": sorted(set(warnings)),
    }


def build_day_brief(day_value: str, min_boards: int = 1) -> dict[str, Any]:
    day = _day(day_value)
    if min_boards < 1:
        raise ValueError("min_boards 必须大于等于 1")
    days = _available_days(day)
    if day not in days:
        raise FileNotFoundError(LIMIT_DIR / f"{day}.json")
    position = days.index(day)
    previous_day = days[position - 1] if position > 0 else None
    current, warnings = _decorated_day(day)
    previous: dict[str, dict[str, Any]] = {}
    if previous_day:
        previous, previous_warnings = _decorated_day(previous_day)
        warnings.extend(previous_warnings)
    stories, story_warnings = _story_records(day)
    warnings.extend(story_warnings)

    research = [row for row in current.values() if row["boards"] >= min_boards]
    research.sort(
        key=lambda row: (-row["boards"], row["first_limit_time"], row["code"])
    )
    ladder_transition = []
    for row in sorted(
        (item for item in previous.values() if item["boards"] >= min_boards),
        key=lambda item: (-item["boards"], item["first_limit_time"], item["code"]),
    ):
        today = current.get(row["code"])
        ladder_transition.append(
            {
                "previous": row,
                "current_status": (
                    "not_in_current_limit_pool"
                    if today is None
                    else "advanced"
                    if today["boards"] > row["boards"]
                    else "still_limit_up"
                ),
                "current": today,
            }
        )
    return {
        "view": "day_brief",
        "information_cutoff": day,
        "previous_trading_day": previous_day,
        "stories": stories,
        "previous_ladder_transition": ladder_transition,
        "current_research_pool": research,
        "display_filter": {
            "min_boards": min_boards,
            "contract": "仅缩小输出范围；板数不是交易排除条件。",
        },
        "position_competition": build_position_competition(day),
        "omitted_from_brief": [
            "综合评分",
            "进攻防守模型",
            "风口排名",
            "同花顺 reason_type",
            "自动核心或买点结论",
        ],
        "warnings": sorted(set(warnings)),
    }


def build_node_pool(
    seed_value: str,
    cutoff_value: str,
    themes: list[str],
    min_boards: int,
) -> dict[str, Any]:
    seed = _day(seed_value)
    cutoff = _day(cutoff_value)
    if seed > cutoff:
        raise ValueError("节点日期不能晚于 information_cutoff")
    if min_boards < 1:
        raise ValueError("--min-boards 必须大于等于 1")
    days = _available_days(cutoff, seed)
    if seed not in days:
        raise FileNotFoundError(LIMIT_DIR / f"{seed}.json")
    day_index = {day: index for index, day in enumerate(days)}

    limit_by_day: dict[str, dict[str, dict[str, Any]]] = {}
    classes_by_day: dict[str, dict[str, dict[str, Any]]] = {}
    warnings: list[str] = []
    for day in days:
        limit_by_day[day] = _limit_map(day)
        classes_by_day[day], day_warnings = _classification_map(day)
        warnings.extend(day_warnings)

    requested = {theme.strip() for theme in themes if theme.strip()}
    members = []
    for code, seed_row in limit_by_day[seed].items():
        seed_class = classes_by_day[seed].get(code)
        seed_fact = _stock_fact(seed, seed_row, seed_class)
        if seed_fact["boards"] < min_boards:
            continue
        if requested and not requested.intersection(seed_fact["themes"]):
            continue

        appearances = [seed_fact]
        for day in days[1:]:
            row = limit_by_day[day].get(code)
            if row is not None:
                appearances.append(
                    _stock_fact(day, row, classes_by_day[day].get(code))
                )
        relations = []
        for previous, current in zip(appearances, appearances[1:]):
            relations.append(
                _relation(
                    previous,
                    current,
                    day_index[current["date"]] - day_index[previous["date"]],
                )
            )
        reactivations = [
            relation
            for relation in relations
            if relation["appearance_kind"] == "reactivation"
        ]
        members.append(
            {
                "seed": seed_fact,
                "later_appearances": appearances[1:],
                "relations": relations,
                "reactivation_count": len(reactivations),
                "new_themes_vs_seed": sorted(
                    {
                        theme
                        for appearance in appearances[1:]
                        for theme in appearance["themes"]
                        if theme not in seed_fact["themes"]
                    }
                ),
            }
        )
    members.sort(
        key=lambda item: (
            -item["seed"]["boards"],
            item["seed"]["first_limit_time"],
            item["seed"]["code"],
        )
    )
    returning = [member for member in members if member["later_appearances"]]
    reactivated = [member for member in members if member["reactivation_count"] > 0]
    return {
        "view": "node_memory_pool",
        "seed_date": seed,
        "information_cutoff": cutoff,
        "seed_scope": {
            "manual_node_date": True,
            "themes": sorted(requested),
            "min_boards": min_boards,
            "membership": "节点日同花顺涨停池与开盘啦源分类的客观交集",
        },
        "data_days_used": days,
        "member_count": len(members),
        "returning_member_count": len(returning),
        "reactivated_member_count": len(reactivated),
        "members": members,
        "judgement_boundary": (
            "节点由人工指定；本视图只追踪旧成员再次出现及属性变化，不设置记忆期限、权重或选股分数。"
        ),
        "warnings": sorted(set(warnings)),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读输出跨日板上路径、身位竞争和节点记忆池。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    brief = subparsers.add_parser("brief", help="输出单日紧凑研究视图")
    brief.add_argument("day", help="交易日，同时也是 information_cutoff")
    brief.add_argument(
        "--min-boards",
        type=int,
        default=1,
        help="仅缩小展示范围；默认1，不构成交易排除条件",
    )
    brief.add_argument("--output", help="可选 UTF-8 JSON 输出路径")

    path = subparsers.add_parser("path", help="输出个股截至指定日的涨停路径")
    path.add_argument("code", help="六位股票代码")
    path.add_argument("cutoff", help="information_cutoff")
    path.add_argument("--start", help="可选起始日期")
    path.add_argument("--output", help="可选 UTF-8 JSON 输出路径")

    competition = subparsers.add_parser(
        "competition", help="输出一字核心与同身位换手竞争证据"
    )
    competition.add_argument("day", help="交易日，同时也是 information_cutoff")
    competition.add_argument("--output", help="可选 UTF-8 JSON 输出路径")

    pool = subparsers.add_parser("pool", help="追踪人工指定节点日的股票记忆池")
    pool.add_argument("seed_date", help="人工确认的节点日期")
    pool.add_argument("cutoff", help="information_cutoff")
    pool.add_argument("--theme", action="append", default=[], help="可重复的源题材过滤")
    pool.add_argument("--min-boards", type=int, default=1, help="仅过滤展示范围")
    pool.add_argument("--output", help="可选 UTF-8 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "brief":
        payload = build_day_brief(args.day, args.min_boards)
    elif args.command == "path":
        payload = build_stock_path(args.code, args.cutoff, args.start)
    elif args.command == "competition":
        payload = build_position_competition(args.day)
    elif args.command == "pool":
        payload = build_node_pool(
            args.seed_date,
            args.cutoff,
            args.theme,
            args.min_boards,
        )
    else:  # pragma: no cover - argparse 已封闭命令集合
        raise AssertionError(args.command)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8", newline="\n")
        print(
            json.dumps(
                {
                    "view": payload["view"],
                    "information_cutoff": payload["information_cutoff"],
                    "output": str(output),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
