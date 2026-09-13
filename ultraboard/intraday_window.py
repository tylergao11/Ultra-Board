# -*- coding: utf-8 -*-
"""按秒级时间窗对齐全体涨停/炸板股票的价格动作。"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from typing import Any

from ultraboard.eastmoney.intraday_ticks import load_day as load_tick_day
from ultraboard.ths.limit_pool import load_day as load_limit_day
from ultraboard.ths.open_limit_pool import load_day as load_open_limit_day
from ultraboard.ths.stock_profiles import load_day as load_profile_day


CN_TZ = timezone(timedelta(hours=8))


def _seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise ValueError("时间必须是 HH:MM:SS")
    hour, minute, second = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError("时间必须是 HH:MM:SS")
    return hour * 3600 + minute * 60 + second


def _hhmmss(seconds: int) -> int:
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    return hour * 10000 + minute * 100 + second


def _time_text(value: int) -> str:
    text = str(value).zfill(6)
    return f"{text[:2]}:{text[2:4]}:{text[4:]}"


def _timestamp_text(value: int | float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, CN_TZ).strftime("%H:%M:%S")


def build_intraday_window(
    day_value: str,
    center_time: str,
    *,
    seconds_before: int = 180,
    seconds_after: int = 180,
    min_move_percentage_points: float = 0.5,
) -> dict[str, Any]:
    day = date.fromisoformat(day_value).isoformat()
    if seconds_before < 0 or seconds_after < 0:
        raise ValueError("时间窗秒数不能为负")
    center = _seconds(center_time)
    start_hhmmss = _hhmmss(max(0, center - seconds_before))
    end_hhmmss = _hhmmss(min(24 * 3600 - 1, center + seconds_after))

    tick_payload = load_tick_day(day)
    profile_payload = load_profile_day(day)
    limit_payload = load_limit_day(day)
    open_payload = load_open_limit_day(day)
    if tick_payload is None or profile_payload is None or limit_payload is None:
        raise FileNotFoundError(f"{day} 缺少布局时间窗所需正式来源")

    profiles = {row["code"]: row for row in profile_payload["stocks"]}
    states = {
        row["code"]: {
            "close_state": "limit_up",
            "boards": row.get("boards"),
            "boards_desc": row.get("boards_desc"),
            "official_first_limit_time": _timestamp_text(row.get("first_limit_ts")),
            "official_final_limit_time": _timestamp_text(row.get("final_limit_ts")),
            "official_open_count": row.get("open_count"),
        }
        for row in limit_payload["stocks"]
    }
    if open_payload is not None:
        states.update(
            {
                row["code"]: {
                    "close_state": "open_limit_failed",
                    "boards": None,
                    "boards_desc": None,
                    "official_first_limit_time": row.get("first_limit_time"),
                    "official_final_limit_time": None,
                    "official_open_count": row.get("open_count"),
                }
                for row in open_payload["stocks"]
            }
        )

    records = []
    for stock in tick_payload["stocks"]:
        samples = stock["samples"]
        times = [row[0] for row in samples]
        left = max(0, bisect_left(times, start_hhmmss) - 1)
        right = bisect_right(times, end_hhmmss)
        window = samples[left:right]
        if not window:
            continue
        previous_close = stock["previous_close_x1000"]
        start_pct = (window[0][1] / previous_close - 1) * 100
        end_pct = (window[-1][1] / previous_close - 1) * 100
        pcts = [(row[1] / previous_close - 1) * 100 for row in window]
        transitions = [
            item
            for item in stock["limit_transitions"]
            if start_hhmmss <= item["time_hhmmss"] <= end_hhmmss
        ]
        move = end_pct - start_pct
        range_pp = max(pcts) - min(pcts)
        if (
            not transitions
            and abs(move) < min_move_percentage_points
            and range_pp < min_move_percentage_points
        ):
            continue
        profile = profiles.get(stock["code"]) or {}
        records.append(
            {
                "code": stock["code"],
                "name": stock["name"],
                **(states.get(stock["code"]) or {}),
                "region": profile.get("region"),
                "concepts": profile.get("concept_names") or [],
                "window_first_sample_time": _time_text(window[0][0]),
                "window_last_sample_time": _time_text(window[-1][0]),
                "start_change_rate": round(start_pct, 4),
                "end_change_rate": round(end_pct, 4),
                "move_percentage_points": round(move, 4),
                "range_percentage_points": round(range_pp, 4),
                "limit_transitions": transitions,
            }
        )
    records.sort(
        key=lambda row: (
            not bool(row["limit_transitions"]),
            row["limit_transitions"][0]["time_hhmmss"]
            if row["limit_transitions"]
            else 999999,
            -row["move_percentage_points"],
            row["code"],
        )
    )
    return {
        "schema_version": 1,
        "date": day,
        "information_cutoff": tick_payload["information_cutoff"],
        "window": {
            "center": center_time,
            "start": _time_text(start_hhmmss),
            "end": _time_text(end_hhmmss),
            "min_move_percentage_points": min_move_percentage_points,
        },
        "contract": (
            "列出时间窗内涨停状态转换或显著价格动作；时间相关不自动等于资金因果"
        ),
        "stock_count": len(records),
        "stocks": records,
    }
