# -*- coding: utf-8 -*-
"""只读输出开盘啦跨日涨停路径、同身位竞争与节点记忆池。"""

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


KPL_DIR = ROOT / "data" / "kaipanla" / "raw"
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
    if not KPL_DIR.exists():
        return days
    for path in KPL_DIR.iterdir():
        candidate = path.name
        if (
            not path.is_dir()
            or not DAY_RE.fullmatch(candidate)
            or candidate > cutoff_day
            or (start_day and candidate < start_day)
            or not (path / "_DONE").exists()
            or (path / "_MISMATCH").exists()
        ):
            continue
        days.append(candidate)
    return sorted(days)


def _time_text(timestamp: int | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, CN_TZ).strftime("%H:%M:%S")


def _clock_seconds_from_text(value: str | None) -> int | None:
    if not value:
        return None
    hour, minute, second = (int(part) for part in value.split(":"))
    return hour * 3600 + minute * 60 + second


def _stock_fact(day: str, row: dict[str, Any]) -> dict[str, Any]:
    first_value = row.get("first_limit_ts")
    first_ts = int(first_value) if first_value not in (None, "") else None
    main_theme = str(row.get("theme") or "").strip() or None
    return {
        "date": day,
        "code": _code(row.get("code")),
        "name": str(row.get("name") or "").strip(),
        "boards": int(row["boards"]),
        "boards_desc": str(row.get("boards_desc") or "").strip(),
        "main_theme": main_theme,
        "themes": [main_theme] if main_theme else [],
        "price": row.get("price"),
        "turnover_rate": row.get("turnover_rate"),
        "amount": row.get("amount"),
        "limit_pct": row.get("limit_pct"),
        "first_limit_time": _time_text(first_ts),
        "is_fanbao": bool(row.get("is_fanbao")),
    }


def _day_map(day: str) -> dict[str, dict[str, Any]]:
    payload = load_kaipanla_day(day)
    return {
        fact["code"]: fact
        for fact in (_stock_fact(day, row) for row in payload["stocks"])
    }


def _ratio(current: Any, previous: Any) -> float | None:
    if (
        isinstance(current, (int, float))
        and isinstance(previous, (int, float))
        and previous > 0
    ):
        return current / previous
    return None


def _relation(
    previous: dict[str, Any],
    current: dict[str, Any],
    trading_day_gap: int,
) -> dict[str, Any]:
    previous_clock = _clock_seconds_from_text(previous.get("first_limit_time"))
    current_clock = _clock_seconds_from_text(current.get("first_limit_time"))
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
            current_clock - previous_clock
            if current_clock is not None and previous_clock is not None
            else None
        ),
        "turnover_multiple": _ratio(
            current.get("turnover_rate"), previous.get("turnover_rate")
        ),
        "amount_multiple": _ratio(current.get("amount"), previous.get("amount")),
        "new_themes_vs_previous": [
            theme for theme in current["themes"] if theme not in previous["themes"]
        ],
    }


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

    days = _available_days(cutoff, start)
    day_index = {day: index for index, day in enumerate(days)}
    appearances = []
    for day in days:
        row = _day_map(day).get(code)
        if row is not None:
            appearances.append(row)
    if not appearances:
        raise ValueError(f"截止 {cutoff} 的开盘啦涨停池中未找到 {code}")

    relations = [
        _relation(
            previous,
            current,
            day_index[current["date"]] - day_index[previous["date"]],
        )
        for previous, current in zip(appearances, appearances[1:])
    ]
    return {
        "view": "stock_path",
        "information_cutoff": cutoff,
        "source_contract": "kaipanla_only_T_and_earlier_main_theme_only",
        "code": code,
        "name": appearances[-1]["name"],
        "data_days_used": [row["date"] for row in appearances],
        "appearances": appearances,
        "relations": relations,
        "judgement_boundary": (
            "只展示跨日变化，不把首封提前、缩量或换手自动命名为加速、分歧或核心。"
        ),
    }


def _shared_themes(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    right_themes = set(right.get("themes") or [])
    return [theme for theme in left.get("themes") or [] if theme in right_themes]


def build_position_competition(day_value: str) -> dict[str, Any]:
    day = _day(day_value)
    days = _available_days(day)
    if day not in days:
        raise FileNotFoundError(KPL_DIR / day)
    current = _day_map(day)
    research = sorted(
        (row for row in current.values() if row["boards"] >= 2),
        key=lambda row: (-row["boards"], row["first_limit_time"] or "99:99:99", row["code"]),
    )
    positions = []
    for boards in sorted({row["boards"] for row in research}, reverse=True):
        members = [row for row in research if row["boards"] == boards]
        shared_pairs = []
        for index, left in enumerate(members):
            for right in members[index + 1 :]:
                shared = _shared_themes(left, right)
                if shared:
                    shared_pairs.append(
                        {
                            "left_code": left["code"],
                            "right_code": right["code"],
                            "shared_themes": shared,
                        }
                    )
        positions.append(
            {
                "boards": boards,
                "members": members,
                "shared_attribute_pairs": shared_pairs,
            }
        )
    return {
        "view": "position_competition",
        "information_cutoff": day,
        "source_contract": "kaipanla_only_main_theme_only",
        "positions": positions,
        "unavailable_fields": [
            "最终封板时间",
            "开板次数",
            "板型",
            "真一字",
            "封单",
        ],
        "judgement_boundary": "只陈列同身位成员与共享属性，不自动判断谁带动谁。",
    }


def build_day_brief(day_value: str, min_boards: int = 1) -> dict[str, Any]:
    day = _day(day_value)
    if min_boards < 1:
        raise ValueError("min_boards 必须大于等于 1")
    days = _available_days(day)
    if day not in days:
        raise FileNotFoundError(KPL_DIR / day)
    position = days.index(day)
    previous_day = days[position - 1] if position > 0 else None
    current = _day_map(day)
    previous = _day_map(previous_day) if previous_day else {}
    research = sorted(
        (row for row in current.values() if row["boards"] >= min_boards),
        key=lambda row: (-row["boards"], row["first_limit_time"] or "99:99:99", row["code"]),
    )
    ladder_transition = []
    for row in sorted(
        (item for item in previous.values() if item["boards"] >= min_boards),
        key=lambda item: (-item["boards"], item["first_limit_time"] or "99:99:99", item["code"]),
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
        "source_contract": "kaipanla_only_main_theme_only",
        "previous_trading_day": previous_day,
        "previous_ladder_transition": ladder_transition,
        "current_research_pool": research,
        "display_filter": {
            "min_boards": min_boards,
            "contract": "仅缩小输出范围；板数不是交易排除条件。",
        },
        "position_competition": build_position_competition(day),
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
        raise FileNotFoundError(KPL_DIR / seed)
    day_index = {day: index for index, day in enumerate(days)}
    by_day = {day: _day_map(day) for day in days}
    requested = {theme.strip() for theme in themes if theme.strip()}

    members = []
    for code, seed_fact in by_day[seed].items():
        if seed_fact["boards"] < min_boards:
            continue
        if requested and not requested.intersection(seed_fact["themes"]):
            continue
        appearances = [seed_fact]
        for day in days[1:]:
            row = by_day[day].get(code)
            if row is not None:
                appearances.append(row)
        relations = [
            _relation(
                previous,
                current,
                day_index[current["date"]] - day_index[previous["date"]],
            )
            for previous, current in zip(appearances, appearances[1:])
        ]
        members.append(
            {
                "seed": seed_fact,
                "later_appearances": appearances[1:],
                "relations": relations,
                "reactivation_count": sum(
                    relation["appearance_kind"] == "reactivation"
                    for relation in relations
                ),
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
            item["seed"]["first_limit_time"] or "99:99:99",
            item["seed"]["code"],
        )
    )
    return {
        "view": "node_memory_pool",
        "seed_date": seed,
        "information_cutoff": cutoff,
        "source_contract": "kaipanla_only_main_theme_only",
        "seed_scope": {
            "manual_node_date": True,
            "themes": sorted(requested),
            "min_boards": min_boards,
            "membership": "节点日开盘啦涨停池与源分类的客观交集",
        },
        "data_days_used": days,
        "member_count": len(members),
        "returning_member_count": sum(bool(item["later_appearances"]) for item in members),
        "reactivated_member_count": sum(item["reactivation_count"] > 0 for item in members),
        "members": members,
        "judgement_boundary": (
            "节点由人工指定；只追踪旧成员再次出现及属性变化，不设置权重或选股分数。"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="只读输出开盘啦跨日路径、同身位竞争和节点记忆池。"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    brief = subparsers.add_parser("brief", help="输出单日紧凑研究视图")
    brief.add_argument("day", help="交易日，同时也是 information_cutoff")
    brief.add_argument("--min-boards", type=int, default=1)
    brief.add_argument("--output", help="可选 UTF-8 JSON 输出路径")

    path = subparsers.add_parser("path", help="输出个股截至指定日的涨停路径")
    path.add_argument("code", help="六位股票代码")
    path.add_argument("cutoff", help="information_cutoff")
    path.add_argument("--start", help="可选起始日期")
    path.add_argument("--output", help="可选 UTF-8 JSON 输出路径")

    competition = subparsers.add_parser("competition", help="输出同身位竞争事实")
    competition.add_argument("day", help="交易日，同时也是 information_cutoff")
    competition.add_argument("--output", help="可选 UTF-8 JSON 输出路径")

    pool = subparsers.add_parser("pool", help="追踪人工指定节点日的股票记忆池")
    pool.add_argument("seed_date", help="人工确认的节点日期")
    pool.add_argument("cutoff", help="information_cutoff")
    pool.add_argument("--theme", action="append", default=[])
    pool.add_argument("--min-boards", type=int, default=1)
    pool.add_argument("--output", help="可选 UTF-8 JSON 输出路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
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
    else:
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
