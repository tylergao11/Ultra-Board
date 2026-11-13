"""Pure read-side statistics for versioned research plans.

This module never changes research records.  Every denominator, numerator and
sample key is returned with the metric so callers can audit the calculation.
Archived statistics are comparison material only and never feed a current
plan result.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal
import json
import sqlite3
from typing import Any, Iterable


def _rows(connection: sqlite3.Connection, sql: str, parameters: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cursor = connection.execute(sql, tuple(parameters))
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _rate(numerator: int, denominator: int) -> float | None:
    return round(100 * numerator / denominator, 4) if denominator else None


def _metric(
    *,
    numerator_keys: list[str],
    denominator_keys: list[str],
    formula: str,
    missing_keys: list[str] | None = None,
) -> dict[str, Any]:
    numerator = len(numerator_keys)
    denominator = len(denominator_keys)
    return {
        "numerator": numerator,
        "denominator": denominator,
        "percent": _rate(numerator, denominator),
        "formula": formula,
        "numerator_record_keys": sorted(numerator_keys),
        "denominator_record_keys": sorted(denominator_keys),
        "missing_record_keys": sorted(missing_keys or []),
    }


def _bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None


def _raw_flag(raw: dict[str, Any], *keys: str) -> bool | None:
    for key in keys:
        if key in raw:
            value = _bool_value(raw[key])
            if value is not None:
                return value
    return None


def _raw_decimal(raw: dict[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = raw.get(key)
        if value is None or value == "":
            continue
        try:
            return Decimal(str(value))
        except Exception:
            continue
    return None


def _close_red(raw: dict[str, Any]) -> bool | None:
    explicit = _raw_flag(raw, "次日收盘红", "次日收红", "次日收盘上涨")
    if explicit is not None:
        return explicit
    buy_close = _raw_decimal(raw, "买入日收盘价", "买入日收盘")
    next_close = _raw_decimal(raw, "次日收盘价", "次日收盘")
    if buy_close is None or next_close is None:
        return None
    return next_close > buy_close


def _plan_rows(connection: sqlite3.Connection, plan_id: int) -> list[dict[str, Any]]:
    rows = _rows(
        connection,
        """
        SELECT d.legacy_record_key,
               d.research_status,
               d.confirmation_status,
               d.buy_result,
               o.bought,
               o.buy_day_sealed,
               o.next_day_board,
               o.next_day_low_open,
               o.next_day_limit_down,
               o.consecutive_boards,
               o.sell_date,
               o.return_pct_micros,
               o.raw_json AS outcome_raw_json
          FROM current_dynamic_research AS d
          LEFT JOIN trade_outcomes AS o ON o.dynamic_research_id = d.id
         WHERE d.plan_id = ?
         ORDER BY d.legacy_record_key
        """,
        (plan_id,),
    )
    for row in rows:
        raw = row.pop("outcome_raw_json", None)
        try:
            row["outcome_raw"] = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            row["outcome_raw"] = {}
    return rows


def calculate_plan_statistics(
    connection: sqlite3.Connection,
    plan_id: int,
    record_key_year: str | None = None,
) -> dict[str, Any]:
    """Calculate one plan without mixing records from any other plan."""

    plan_rows = _rows(
        connection,
        """SELECT id,plan_code,version,name,status,definition_json
             FROM research_plans WHERE id=?""",
        (plan_id,),
    )
    if not plan_rows:
        raise KeyError(f"research plan not found: {plan_id}")
    plan = plan_rows[0]
    rows = _plan_rows(connection, plan_id)
    if record_key_year is not None:
        rows = [
            row for row in rows
            if str(row["legacy_record_key"]).partition("|")[2].startswith(f"{record_key_year}-")
        ]
    all_keys = [row["legacy_record_key"] for row in rows]
    bought_rows = [row for row in rows if _bool_value(row["bought"]) is True]
    bought_keys = [row["legacy_record_key"] for row in bought_rows]
    explicit_not_bought_keys = [
        row["legacy_record_key"] for row in rows if _bool_value(row["bought"]) is False
    ]
    missing_bought_keys = [
        row["legacy_record_key"] for row in rows if _bool_value(row["bought"]) is None
    ]

    sealed_keys = [
        row["legacy_record_key"] for row in bought_rows if _bool_value(row["buy_day_sealed"]) is True
    ]
    sealed_missing = [
        row["legacy_record_key"] for row in bought_rows if _bool_value(row["buy_day_sealed"]) is None
    ]
    next_board_keys = [
        row["legacy_record_key"]
        for row in bought_rows
        if _bool_value(row["buy_day_sealed"]) is True
        and _bool_value(row["next_day_board"]) is True
    ]
    next_board_missing = [
        row["legacy_record_key"] for row in bought_rows if _bool_value(row["next_day_board"]) is None
    ]
    low_open_rows = [
        row for row in bought_rows if _bool_value(row["next_day_low_open"]) is True
    ]
    low_open_keys = [row["legacy_record_key"] for row in low_open_rows]
    low_open_missing = [
        row["legacy_record_key"] for row in bought_rows if _bool_value(row["next_day_low_open"]) is None
    ]
    low_open_board_keys = [
        row["legacy_record_key"]
        for row in low_open_rows
        if _bool_value(row["buy_day_sealed"]) is True
        and _bool_value(row["next_day_board"]) is True
    ]
    low_open_limit_down_keys = [
        row["legacy_record_key"]
        for row in low_open_rows
        if _bool_value(row["next_day_limit_down"]) is True
    ]
    low_open_limit_down_missing = [
        row["legacy_record_key"]
        for row in low_open_rows
        if _bool_value(row["next_day_limit_down"]) is None
    ]

    close_red_by_key = {
        row["legacy_record_key"]: _close_red(row["outcome_raw"])
        for row in low_open_rows
    }
    low_open_close_red_keys = [key for key, value in close_red_by_key.items() if value is True]
    low_open_close_red_missing = [key for key, value in close_red_by_key.items() if value is None]

    return_rows = [row for row in bought_rows if row["return_pct_micros"] is not None]
    returns = [Decimal(row["return_pct_micros"]) / Decimal(1_000_000) for row in return_rows]
    win_keys = [
        row["legacy_record_key"]
        for row in return_rows
        if Decimal(row["return_pct_micros"]) > 0
    ]
    return_keys = [row["legacy_record_key"] for row in return_rows]
    return_missing = [
        row["legacy_record_key"] for row in bought_rows if row["return_pct_micros"] is None
    ]
    consecutive_distribution = Counter(
        str(row["consecutive_boards"])
        for row in bought_rows
        if row["consecutive_boards"] is not None
    )

    return {
        "plan": {
            "id": plan["id"],
            "code": plan["plan_code"],
            "version": plan["version"],
            "name": plan["name"],
            "status": plan["status"],
        },
        "scope": {
            "dynamic_record_count": len(rows),
            "dynamic_record_keys": sorted(all_keys),
            "bought_sample_count": len(bought_rows),
            "bought_record_keys": sorted(bought_keys),
            "explicit_not_bought_record_keys": sorted(explicit_not_bought_keys),
            "missing_bought_status_record_keys": sorted(missing_bought_keys),
            "denominator_policy": "Only records with trade_outcomes.bought=1 enter buy-sample metrics; NULL stays a recorded data gap.",
            "record_key_year": record_key_year,
        },
        "metrics": {
            "buy_day_seal_rate": _metric(
                numerator_keys=sealed_keys,
                denominator_keys=bought_keys,
                formula="bought samples whose buy day finally closed at limit / all bought samples",
                missing_keys=sealed_missing,
            ),
            "next_day_board_rate": _metric(
                numerator_keys=next_board_keys,
                denominator_keys=bought_keys,
                formula="bought samples sealed on buy day and finally sealed again next trading day / all bought samples",
                missing_keys=next_board_missing,
            ),
            "low_open_board_rate": _metric(
                numerator_keys=low_open_board_keys,
                denominator_keys=low_open_keys,
                formula="low-open bought samples sealed on buy day and finally sealed next trading day / all low-open bought samples",
                missing_keys=low_open_missing,
            ),
            "low_open_close_red_rate": _metric(
                numerator_keys=low_open_close_red_keys,
                denominator_keys=low_open_keys,
                formula="low-open bought samples with next-day close strictly above buy-day close / all low-open bought samples",
                missing_keys=low_open_close_red_missing,
            ),
            "low_open_final_limit_down_rate": _metric(
                numerator_keys=low_open_limit_down_keys,
                denominator_keys=low_open_keys,
                formula="low-open bought samples whose next-day final close equals limit-down / all low-open bought samples",
                missing_keys=low_open_limit_down_missing,
            ),
            "tail_sell_return": {
                "samples": len(return_rows),
                "sample_record_keys": sorted(return_keys),
                "missing_record_keys": sorted(return_missing),
                "average_percent": (
                    round(float(sum(returns) / Decimal(len(returns))), 4) if returns else None
                ),
                "win_rate": _metric(
                    numerator_keys=win_keys,
                    denominator_keys=return_keys,
                    formula="tail-sell samples with return above zero / bought samples with a recorded tail-sell return",
                    missing_keys=return_missing,
                ),
                "formula": "Arithmetic mean of stored per-trade return percentages; fees, tax and slippage follow the plan definition.",
            },
            "consecutive_next_board_distribution": dict(sorted(consecutive_distribution.items())),
        },
    }


def calculate_all_plan_statistics(connection: sqlite3.Connection) -> dict[str, Any]:
    plans = _rows(connection, "SELECT id FROM research_plans WHERE status='current' AND plan_code='formal'")
    formal = []
    for plan in plans:
        result = calculate_plan_statistics(connection, int(plan["id"]))
        years = sorted({key.partition("|")[2][:4] for key in result["scope"]["dynamic_record_keys"]})
        result["year_scopes"] = {
            year: calculate_plan_statistics(connection, int(plan["id"]), year) for year in years
        }
        formal.append(result)
    return {"formal_plans": formal}


def build_statistics_report(connection: sqlite3.Connection) -> dict[str, Any]:
    return calculate_all_plan_statistics(connection)
