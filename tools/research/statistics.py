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
import re
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
    """Calculate every plan independently, with formal and comparison groups separated."""

    plans = _rows(
        connection,
        "SELECT id,plan_code,version,status FROM research_plans ORDER BY plan_code,version",
    )
    formal: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] = []
    for plan in plans:
        result = calculate_plan_statistics(connection, int(plan["id"]))
        years = sorted({
            str(key).partition("|")[2][:4]
            for key in result["scope"]["dynamic_record_keys"]
            if re.fullmatch(r"\d{4}", str(key).partition("|")[2][:4])
        })
        result["year_scopes"] = {
            year: calculate_plan_statistics(connection, int(plan["id"]), year)
            for year in years
        }
        target = formal if plan["status"] == "current" and plan["plan_code"] == "formal" else comparisons
        target.append(result)
    return {
        "formal_plans": formal,
        "comparison_plans": comparisons,
        "separation_policy": "Each metric is grouped by research_plans.id; archived or hypothetical rows never enter formal-plan SQL results.",
    }


def load_archived_statistics(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    """Load old statistics/comparison material as read-only comparison evidence."""

    rows = _rows(
        connection,
        """
        SELECT source_file,section,archive_kind,raw_sha256,raw_json
          FROM archived_sections
         WHERE archive_kind IN ('statistics','comparison_study')
         ORDER BY source_file,section
        """,
    )
    for row in rows:
        try:
            row["value"] = json.loads(row.pop("raw_json"))
        except (TypeError, ValueError):
            row["value"] = None
            row.pop("raw_json", None)
    return rows


def _scalar_paths(value: Any, path: str = "") -> dict[str, Any]:
    result: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            result.update(_scalar_paths(child, child_path))
    elif not isinstance(value, list):
        result[path] = value
    return result


ARCHIVED_METRIC_ALIASES = {
    "buy_day_seal_rate": ("buyDaySealRatePct", "买入日封板率", "买入日封板率百分比", "封板率"),
    "next_day_board_rate": ("nextDayBoardRatePct", "次日连板率", "次日连板率百分比"),
    "low_open_board_rate": ("lowOpenNextBoardRatePct", "低开连板率", "低开连板率百分比"),
    "low_open_close_red_rate": ("lowOpenCloseRedRatePct", "低开后收盘红概率", "低开收红率百分比"),
    "low_open_final_limit_down_rate": ("lowOpenFinalLimitDownRatePct", "低开后跌停概率", "低开最终跌停率百分比"),
}


def _archived_sample_keys(value: Any) -> list[str]:
    candidates: list[list[str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, list) and "买入样本" in str(key):
                sample = [item for item in child if isinstance(item, str) and "|" in item]
                if sample:
                    candidates.append(sample)
            candidates.extend([_archived_sample_keys(child)])
    elif isinstance(value, list):
        for child in value:
            candidates.extend([_archived_sample_keys(child)])
    candidates = [item for item in candidates if item]
    return max(candidates, key=len) if candidates else []


def compare_with_archived(
    current_plan_result: dict[str, Any],
    archived_sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare equivalent scalar rates and state a concrete difference category."""

    archived_values: list[tuple[dict[str, Any], str, Any]] = []
    for section in archived_sections:
        for path, value in _scalar_paths(section.get("value")).items():
            archived_values.append((section, path, value))
    comparisons: list[dict[str, Any]] = []
    for metric_key, aliases in ARCHIVED_METRIC_ALIASES.items():
        all_history = current_plan_result.get("metrics", {}).get(metric_key, {})
        matches = [
            (section, path, value)
            for section, path, value in archived_values
            if any(path == alias or path.endswith(f".{alias}") for alias in aliases)
        ]
        if not matches:
            comparisons.append({
                "metric": metric_key,
                "current_percent": all_history.get("percent"),
                "archive_status": "no_equivalent_scalar_found",
                "difference_attribution": "The archive has no scalar under a recognized metric name; retain the archive value and formula for manual review.",
            })
            continue
        for section, path, value in matches:
            year_match = re.search(r"(?<!\d)(20\d{2})(?!\d)", f"{section.get('section', '')}.{path}")
            archive_year = year_match.group(1) if year_match else None
            scoped_result = current_plan_result.get("year_scopes", {}).get(archive_year, current_plan_result)
            current = scoped_result.get("metrics", {}).get(metric_key, {})
            current_value = current.get("percent")
            try:
                archived_value = float(value) if value is not None else None
            except (TypeError, ValueError):
                archived_value = None
            equal = (
                current_value is not None
                and archived_value is not None
                and abs(float(current_value) - archived_value) < 0.005
            )
            archived_keys = _archived_sample_keys(section.get("value"))
            current_keys = current.get("denominator_record_keys", [])
            current_only = sorted(set(current_keys) - set(archived_keys)) if archived_keys else []
            archived_only = sorted(set(archived_keys) - set(current_keys)) if archived_keys else []
            if equal:
                attribution = "same_formula_result" if archive_year is None else f"same_formula_result_for_{archive_year}_record_scope"
            elif archived_keys:
                if not current_only and not archived_only and archived_value is not None:
                    archived_numerator = round(archived_value * len(archived_keys) / 100)
                    attribution = (
                        f"same_sample_outcome_revision: both use {len(current_keys)} sample keys; "
                        f"current numerator={current.get('numerator')}, archived numerator inferred from its scalar={archived_numerator}; "
                        f"the archived path is retained as an earlier outcome/statistics revision"
                    )
                else:
                    attribution = (
                        f"sample_scope_difference: current denominator {len(current_keys)}, archived sample {len(archived_keys)}; "
                        f"current_only={current_only}; archived_only={archived_only}"
                    )
            else:
                attribution = (
                    f"formula_or_coverage_difference: current numerator={current.get('numerator')}, "
                    f"denominator={current.get('denominator')}, percent={current_value}; "
                    f"archive scalar={archived_value} and no equivalent archived sample-key list is present"
                )
            comparisons.append({
                "metric": metric_key,
                "current_percent": current_value,
                "all_history_percent": all_history.get("percent"),
                "comparison_record_key_year": archive_year,
                "current_numerator": current.get("numerator"),
                "current_denominator": current.get("denominator"),
                "archived_percent": archived_value,
                "archived_source_file": section.get("source_file"),
                "archived_section": section.get("section"),
                "archived_path": path,
                "same_value": equal,
                "difference_attribution": attribution,
            })
    return comparisons


def build_statistics_report(connection: sqlite3.Connection) -> dict[str, Any]:
    """Return formal results, separate comparison results, and archive differences."""

    plans = calculate_all_plan_statistics(connection)
    archived = load_archived_statistics(connection)
    formal_archived = [section for section in archived if section.get("archive_kind") == "statistics"]
    formal_comparisons = [
        {
            "plan": result["plan"],
            "archive_comparison": compare_with_archived(result, formal_archived),
        }
        for result in plans["formal_plans"]
    ]
    return {
        **plans,
        "archived_sections": archived,
        "formal_archive_comparisons": formal_comparisons,
        "archive_policy": "Archived values remain evidence. Differences are reported and never overwrite current plan statistics.",
    }
