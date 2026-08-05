# -*- coding: utf-8 -*-
"""主升梯队人工判断的轻量证据接口。

只取证，不选梯队、不选股票：

  # 第一阶段：只看节点日收盘证据，不加载 T+1
  python -m ultraboard.kaipanla.ladder_evidence node 2025-12-12 2025-12-16

  # 第二阶段：梯队冻结后，才查看该层的 T+1 个股 PK
  python -m ultraboard.kaipanla.ladder_evidence pk 2025-12-12:2 2025-12-16:4

两种命令都支持 ``--format json``。默认输出适合直接阅读的 Markdown。

真相源边界：
- 梯队、公告属性、题材发酵：ladder_daily/by_day/{date}.json
- 开盘、首封、换手、日内 OHLC：raw/{date}/zt_pool.json + ohlc.json
- 市场破板率：raw/{date}/expression.json 的 info[7]

明确不读取人工判断、自动选层、最终高度、未来收益等裁判字段，也不替人工宣布
“应有竞价”或“资金已迁移”。当前原始池没有末封时间和地域字段，接口会如实
保留缺口，绝不拿首封冒充末封，也不硬编码地域或名称关联。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import ohlc


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data" / "kaipanla" / "ladder_daily"
RAW_DIR = ROOT / "data" / "kaipanla" / "raw"
BY_DAY_DIR = DATA_DIR / "by_day"
CN_TZ = timezone(timedelta(hours=8))


@lru_cache(maxsize=None)
def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return int(number) if number is not None else None


def as_bool(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes"}


def code_of(value: Any) -> str:
    return str(value or "").zfill(6)


def is_chinext(code: str) -> bool:
    return code.startswith("30")


def seal_time(ts: Any) -> str | None:
    seconds = as_int(ts)
    if not seconds:
        return None
    return datetime.fromtimestamp(seconds, timezone.utc).astimezone(CN_TZ).strftime(
        "%H:%M:%S"
    )


def pct(value: float | None) -> str:
    return "—" if value is None else f"{value:+.2f}%"


def number(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def rate(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}%"


def nominal_limit_pct(code: str, name: str | None) -> float:
    """用于相对涨停幅度展示的交易所名义涨停幅度。"""
    if "ST" in str(name or "").upper():
        return 5.0
    if code.startswith(("300", "301", "688", "689")):
        return 20.0
    return 10.0


def near_equal(a: Any, b: Any) -> bool:
    left, right = as_float(a), as_float(b)
    if left is None or right is None:
        return False
    return abs(left - right) <= max(1e-6, abs(right) * 1e-6)


def is_one_price(stock: dict[str, Any]) -> bool:
    return near_equal(stock.get("open"), stock.get("high")) and near_equal(
        stock.get("high"), stock.get("low")
    )


def raw_pool(day: str) -> dict[str, Any]:
    return load_json(RAW_DIR / day / "zt_pool.json")


def ohlc_map(day: str) -> dict[str, dict[str, Any]]:
    path = RAW_DIR / day / "ohlc.json"
    if not path.exists():
        return {}
    return {
        code_of(code): row
        for code, row in (load_json(path).get("stocks") or {}).items()
    }


def cached_ohlc(code: str, day: str) -> dict[str, Any]:
    """读取已验证的统一未复权缓存；缺失时不联网、不猜值。"""
    path = ohlc.CACHE_DIR / f"{code}.json"
    if not path.exists():
        return {}
    payload = load_json(path)
    if payload.get("price_mode") != ohlc.CACHE_PRICE_MODE:
        return {}
    return (payload.get("bars") or {}).get(day) or {}


@lru_cache(maxsize=1)
def available_trade_days() -> tuple[str, ...]:
    return tuple(sorted(
        path.name
        for path in RAW_DIR.iterdir()
        if path.is_dir() and (path / "zt_pool.json").exists()
    ))


def next_trade_day(day: str) -> str | None:
    return next((item for item in available_trade_days() if item > day), None)


def theme_rank_map(theme_counts: dict[str, Any]) -> dict[str, int]:
    ranks: dict[str, int] = {}
    previous_count: int | None = None
    previous_rank = 0
    for index, (theme, count) in enumerate(
        sorted(theme_counts.items(), key=lambda item: (-item[1], item[0])), 1
    ):
        current = as_int(count) or 0
        if current != previous_count:
            previous_rank = index
            previous_count = current
        ranks[theme] = previous_rank
    return ranks


def theme_history(day: str, theme: str, history_days: int) -> list[dict[str, Any]]:
    if history_days == 0:
        return []
    prior_days = [item for item in available_trade_days() if item < day][-history_days:]
    history = []
    for prior_day in prior_days:
        path = BY_DAY_DIR / f"{prior_day}.json"
        if not path.exists():
            continue
        counts = (
            (load_json(path).get("market") or {}).get("theme_first_board_counts")
            or {}
        )
        history.append(
            {"date": prior_day, "first_board_count": as_int(counts.get(theme)) or 0}
        )
    return history


def by_day_stock_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for members in (payload.get("ladder") or {}).values():
        for row in members:
            rows[code_of(row.get("code"))] = row
    return rows


def theme_first_boards(
    stocks: list[dict[str, Any]], theme: str
) -> list[dict[str, Any]]:
    return sorted(
        [
            row
            for row in stocks
            if as_int(row.get("boards")) == 1 and row.get("theme") == theme
        ],
        key=lambda row: as_int(row.get("first_limit_ts")) or 10**20,
    )


def theme_timing(
    all_stocks: list[dict[str, Any]], theme: str, candidate_ts: Any
) -> dict[str, Any]:
    firsts = theme_first_boards(all_stocks, theme)
    cutoff = as_int(candidate_ts)
    before = (
        sum((as_int(row.get("first_limit_ts")) or 10**20) <= cutoff for row in firsts)
        if cutoff
        else None
    )
    return {
        "before_candidate_first_seal": before,
        "close_count": len(firsts),
        "first_times": [seal_time(row.get("first_limit_ts")) for row in firsts],
    }


def market_snapshot(day: str, by_day: dict[str, Any], pool: dict[str, Any]) -> dict[str, Any]:
    expression = load_json(RAW_DIR / day / "expression.json").get("info") or []
    market = by_day.get("market") or {}
    themes = market.get("theme_first_board_counts") or {}
    return {
        "limit_count": as_int(pool.get("count")),
        "max_board": as_int(pool.get("max_board")),
        "board_counts": pool.get("board_counts") or {},
        "first_board_count": as_int(market.get("first_board_count")),
        "ge2_count": as_int(market.get("ge2_count")),
        "promotion": {
            "one_to_two_pct": as_float(expression[4]) if len(expression) > 4 else None,
            "two_to_three_pct": as_float(expression[5]) if len(expression) > 5 else None,
            "high_board_pct": as_float(expression[6]) if len(expression) > 6 else None,
        },
        "main_market_break_pct": (
            as_float(expression[7]) if len(expression) > 7 else None
        ),
        "top_themes": [
            {"theme": theme, "first_board_count": as_int(count)}
            for theme, count in sorted(themes.items(), key=lambda item: (-item[1], item[0]))
        ],
    }


def node_evidence(day: str, history_days: int = 3) -> dict[str, Any]:
    by_day = load_json(BY_DAY_DIR / f"{day}.json")
    pool = raw_pool(day)
    all_stocks = pool.get("stocks") or []
    raw_map = {code_of(row.get("code")): row for row in all_stocks}
    meta_map = by_day_stock_map(by_day)
    ladder_rows = [
        row
        for row in all_stocks
        if (as_int(row.get("boards")) or 0) >= 2
        and not is_chinext(code_of(row.get("code")))
    ]
    theme_counts = (by_day.get("market") or {}).get("theme_first_board_counts") or {}
    theme_ranks = theme_rank_map(theme_counts)
    distinct_themes = {str(row.get("theme") or "") for row in ladder_rows}
    histories = {
        theme: theme_history(day, theme, history_days) for theme in distinct_themes
    }
    height_counts: dict[int, int] = {}
    for row in ladder_rows:
        height = as_int(row.get("boards")) or 0
        height_counts[height] = height_counts.get(height, 0) + 1

    broken_rows = by_day.get("change", {}).get("broken") or []
    broken = [
        {
            "code": code_of(row.get("code")),
            "name": row.get("name"),
            "height": as_int(row.get("boards_before_break") or row.get("boards")),
            "theme": row.get("theme"),
            "announcement": bool(row.get("is_gonggao")),
        }
        for row in broken_rows
        if not is_chinext(code_of(row.get("code")))
    ]
    broken.sort(key=lambda row: (-(row["height"] or 0), row["code"]))

    candidates = []
    for raw in ladder_rows:
        code = code_of(raw.get("code"))
        meta = meta_map.get(code) or {}
        theme = str(raw.get("theme") or meta.get("theme") or "")
        height = as_int(raw.get("boards")) or 0
        peers = [row for row in ladder_rows if row.get("theme") == theme]
        peer_heights = [as_int(row.get("boards")) or 0 for row in peers]
        candidate_ts = raw.get("first_limit_ts")
        same_height_theme_count = sum(item == height for item in peer_heights)
        history = histories.get(theme) or []
        candidates.append(
            {
                "height": height,
                "code": code,
                "name": raw.get("name"),
                "theme": theme,
                "announcement": bool(meta.get("is_gonggao")),
                "open_pct": as_float(raw.get("open_pct")),
                "first_seal": seal_time(candidate_ts),
                "final_seal": None,
                "turnover_pct": as_float(raw.get("turnover_rate")),
                "limit_open": near_equal(raw.get("open"), raw.get("price")),
                "one_price": is_one_price(raw),
                "theme_first_board_count": as_int(theme_counts.get(theme)) or 0,
                "theme_ferment_rank": theme_ranks.get(theme, len(theme_ranks) + 1),
                "theme_ferment_history": history,
                "theme_ferment_history_supported_days": sum(
                    row["first_board_count"] > 0 for row in history
                ),
                "theme_ferment_history_count_sum": sum(
                    row["first_board_count"] for row in history
                ),
                "theme_timing": theme_timing(all_stocks, theme, candidate_ts),
                "theme_height_core": height == max(peer_heights, default=height),
                "same_theme_same_height_count": same_height_theme_count,
                "same_theme_height_share": (
                    same_height_theme_count / height_counts[height]
                    if height_counts.get(height)
                    else 0.0
                ),
                "same_theme_lower_ladder_count": sum(item < height for item in peer_heights),
                "boards_desc": raw.get("boards_desc") or "",
            }
        )
    candidates.sort(
        key=lambda row: (-(row["height"] or 0), row["first_seal"] or "99:99:99", row["code"])
    )

    layout_candidates = []
    for donor in broken:
        for recipient in candidates:
            if (
                donor["theme"]
                and donor["theme"] == recipient["theme"]
                and (recipient["height"] or 0) < (donor["height"] or 0)
            ):
                layout_candidates.append(
                    {
                        "evidence_level": "association_hypothesis",
                        "donor": donor,
                        "recipient": {
                            key: recipient[key]
                            for key in ("code", "name", "height", "theme")
                        },
                    }
                )

    return {
        "stage": "node_close_only",
        "date": day,
        "market": market_snapshot(day, by_day, pool),
        "broken_previous_ladder": broken,
        "same_attribute_layout_candidates": layout_candidates,
        "ferment_history_days": history_days,
        "candidates": candidates,
        "source_gap": "原始涨停池只有首封时间，没有末封时间",
    }


def parse_node_spec(spec: str) -> tuple[str, int]:
    try:
        day, height_text = spec.rsplit(":", 1)
        datetime.strptime(day, "%Y-%m-%d")
        height = int(height_text)
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError(
            f"节点格式应为 YYYY-MM-DD:HEIGHT，收到 {spec!r}"
        ) from exc
    if height < 2:
        raise argparse.ArgumentTypeError("主升梯队高度必须 >= 2")
    return day, height


def low_pct(ohlc: dict[str, Any]) -> float | None:
    low, prev = as_float(ohlc.get("low")), as_float(ohlc.get("prev_close"))
    if low is None or not prev:
        return None
    return (low / prev - 1.0) * 100.0


def high_pct(bar: dict[str, Any]) -> float | None:
    high, prev = as_float(bar.get("high")), as_float(bar.get("prev_close"))
    if high is None or not prev:
        return None
    return (high / prev - 1.0) * 100.0


def pk_evidence(
    specs: list[tuple[str, int]], history_days: int = 3
) -> list[dict[str, Any]]:
    packs = []
    for day, height in specs:
        node = node_evidence(day, history_days=history_days)
        candidates = [row for row in node["candidates"] if row["height"] == height]
        if not candidates:
            raise ValueError(f"{day} 不存在排除创业板后的 {height} 板候选")
        action_day = next_trade_day(day)
        if not action_day:
            raise ValueError(f"{day} 没有可用的下一交易日")

        action_pool = raw_pool(action_day)
        action_stocks = action_pool.get("stocks") or []
        action_raw = {code_of(row.get("code")): row for row in action_stocks}
        action_ohlc = ohlc_map(action_day)
        action_by_day = load_json(BY_DAY_DIR / f"{action_day}.json")
        action_meta_map = by_day_stock_map(action_by_day)
        action_theme_counts = (
            (action_by_day.get("market") or {}).get("theme_first_board_counts") or {}
        )

        rows = []
        for candidate in candidates:
            code = candidate["code"]
            action = action_raw.get(code) or {}
            action_meta = action_meta_map.get(code) or {}
            bar = action_ohlc.get(code) or cached_ohlc(code, action_day) or action
            action_theme = str(
                action.get("theme") or action_meta.get("theme") or candidate["theme"]
            )
            action_announcement = bool(action_meta.get("is_gonggao"))
            limit_pct = nominal_limit_pct(code, candidate["name"])
            action_first_ts = action.get("first_limit_ts")
            visible_ferment = theme_timing(
                action_stocks, action_theme, action_first_ts
            )
            actual_pct = as_float(bar.get("open_pct"))
            actual_norm = (
                actual_pct / limit_pct
                if actual_pct is not None and limit_pct
                else None
            )
            near_limit = bool(
                actual_pct is not None and actual_pct >= limit_pct * 0.9
            )
            touched = bool(
                action
                or (
                    (intraday_high := high_pct(bar)) is not None
                    and intraday_high >= limit_pct * 0.98
                )
            )
            rows.append(
                {
                    "code": code,
                    "name": candidate["name"],
                    "height": height,
                    "theme": candidate["theme"],
                    "action_theme": action_theme,
                    "node_close": {
                        "announcement": candidate["announcement"],
                        "open_pct": candidate["open_pct"],
                        "first_seal": candidate["first_seal"],
                        "final_seal": None,
                        "turnover_pct": candidate["turnover_pct"],
                        "one_price": candidate["one_price"],
                        "theme_first_board_count": candidate[
                            "theme_first_board_count"
                        ],
                        "theme_ferment_rank": candidate["theme_ferment_rank"],
                        "theme_ferment_history": candidate[
                            "theme_ferment_history"
                        ],
                        "theme_first_boards_before_seal": candidate["theme_timing"][
                            "before_candidate_first_seal"
                        ],
                    },
                    "available_at_09_25": {
                        "expected_open_pct": None,
                        "expected_source": "manual_judgment_required",
                        "actual_open_pct": actual_pct,
                        "actual_open_norm": actual_norm,
                        "actual_minus_expected_pp": None,
                        "near_limit": near_limit,
                        "action_announcement": action_announcement,
                        "zero_ferment_near_limit_risk": (
                            candidate["theme_first_board_count"] == 0
                            and near_limit
                        ),
                    },
                    "available_intraday_when_first_seal_observed": {
                        "first_seal": seal_time(action_first_ts),
                        "final_seal": None,
                        "opened_at_limit": bool(
                            actual_pct is not None
                            and actual_pct >= limit_pct * 0.98
                        ),
                        "low_pct": low_pct(bar),
                        "theme_first_boards_already_sealed": visible_ferment[
                            "before_candidate_first_seal"
                        ],
                    },
                    "available_after_close_only": {
                        "touched_limit": touched,
                        "continued": bool(action),
                        "one_price": bool(touched and is_one_price(bar or action)),
                        "turnover_pct": as_float(action.get("turnover_rate")),
                        "theme_first_board_count": as_int(
                            action_theme_counts.get(action_theme)
                        )
                        or 0,
                    },
                }
            )
        rows.sort(key=lambda row: row["code"])
        packs.append(
            {
                "stage": "frozen_ladder_t1_pk",
                "node_date": day,
                "frozen_height": height,
                "action_date": action_day,
                "candidates": rows,
                "source_gap": (
                    "末封时间、盘中分时换手快照和地域字段缺失；"
                    "应有竞价与关系类型须由人工判断，收盘结果不得倒灌到盘中买点"
                ),
            }
        )
    return packs


def markdown_node(pack: dict[str, Any]) -> str:
    market = pack["market"]
    lines = [
        f"## {pack['date']}｜节点日证据（不含T+1）",
        "",
        (
            f"市场：涨停{market['limit_count']}，最高{market['max_board']}板，"
            f"2板以上{market['ge2_count']}；主市场破板率"
            f"{number(market['main_market_break_pct'])}%｜一进二"
            f"{number(market['promotion']['one_to_two_pct'])}%｜二进三"
            f"{number(market['promotion']['two_to_three_pct'])}%｜高位晋级"
            f"{number(market['promotion']['high_board_pct'])}%"
        ),
        "",
    ]
    broken = pack["broken_previous_ladder"]
    max_broken_height = max((row["height"] or 0 for row in broken), default=0)
    top_broken = [row for row in broken if (row["height"] or 0) == max_broken_height]
    lines.append(
        "断板旧梯队："
        + (
            "、".join(
                f"{row['name']}{row['height']}板/{row['theme']}"
                + ("[公告]" if row["announcement"] else "")
                for row in top_broken
            )
            if top_broken
            else "无"
        )
    )
    links = pack["same_attribute_layout_candidates"]
    lines.append(
        "同属性布局候选（未确认迁移）："
        + (
            "；".join(
                f"{row['donor']['name']}{row['donor']['height']}板→"
                f"{row['recipient']['name']}{row['recipient']['height']}板"
                for row in links
            )
            if links
            else "无精确同属性高低位映射；补涨、让位或跨属性切换均留给人工判断"
        )
    )
    lines.extend(["", "题材首板前排：" + "、".join(
        f"{row['theme']}{row['first_board_count']}" for row in market["top_themes"][:10]
    ), ""])
    lines.append("|板|股票|题材|公告|开盘|首封|换手|一字|发酵 封前/收盘(排名)/历史|题材地位|")
    lines.append("|---:|---|---|:---:|---:|---:|---:|:---:|---:|---|")
    for row in pack["candidates"]:
        timing = row["theme_timing"]
        history_text = "/".join(
            str(item["first_board_count"])
            for item in row["theme_ferment_history"]
        ) or "—"
        position = "高度核心" if row["theme_height_core"] else "非高度核心"
        position += (
            f"；同高{row['same_theme_same_height_count']}"
            f"/{row['same_theme_height_share']:.0%}，低位{row['same_theme_lower_ladder_count']}"
        )
        lines.append(
            f"|{row['height']}|{row['name']} `{row['code']}`|{row['theme']}|"
            f"{'是' if row['announcement'] else '否'}|{pct(row['open_pct'])}|"
            f"{row['first_seal'] or '—'}|{rate(row['turnover_pct'])}|"
            f"{'是' if row['one_price'] else '否'}|"
            f"{timing['before_candidate_first_seal'] if timing['before_candidate_first_seal'] is not None else '—'}"
            f"/{row['theme_first_board_count']}({row['theme_ferment_rank']})/{history_text}|{position}|"
        )
    lines.extend(["", f"数据缺口：{pack['source_gap']}。"])
    return "\n".join(lines)


def markdown_pk(pack: dict[str, Any]) -> str:
    lines = [
        f"## {pack['node_date']}｜冻结{pack['frozen_height']}板 → {pack['action_date']}个股PK",
        "",
        "|股票|题材|实际竞价|相对涨停|09:25风险|盘中首封|最低涨幅|首封前可见首板|收盘换手*|连板*|",
        "|---|---|---:|---:|---|---:|---:|---:|---:|:---:|",
    ]
    for row in pack["candidates"]:
        auction = row["available_at_09_25"]
        intraday = row["available_intraday_when_first_seal_observed"]
        close = row["available_after_close_only"]
        risks = []
        if row["node_close"]["announcement"] or auction["action_announcement"]:
            risks.append("公告")
        if auction["zero_ferment_near_limit_risk"]:
            risks.append("0发酵近板")
        if intraday["opened_at_limit"]:
            risks.append("涨停开勿排队")
        theme_text = row["theme"]
        if row["action_theme"] != row["theme"]:
            theme_text += f"→{row['action_theme']}"
        lines.append(
            f"|{row['name']} `{row['code']}`|{theme_text}|"
            f"{pct(auction['actual_open_pct'])}|{number(auction['actual_open_norm'])}|"
            f"{'、'.join(risks) or '—'}|"
            f"{intraday['first_seal'] or '—'}|{pct(intraday['low_pct'])}|"
            f"{intraday['theme_first_boards_already_sealed'] if intraday['theme_first_boards_already_sealed'] is not None else '—'}|"
            f"{rate(close['turnover_pct'])}|{'是' if close['continued'] else '否'}|"
        )
    lines.extend(
        [
            "",
            "判断边界：应有竞价、补涨/切换/让位、布局线索是否兑现以及 buy/abstain 均由人工基于本包判断；脚本不自动评分。",
            "说明：收盘换手、最终发酵数和是否连板只可用于复盘或下一交易日，不能倒灌到盘中买点。",
            f"数据缺口：{pack['source_gap']}。",
        ]
    )
    return "\n".join(lines)


def emit(payload: Any, output_format: str, renderer) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    packs = payload if isinstance(payload, list) else [payload]
    print("\n\n".join(renderer(pack) for pack in packs))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    node_parser = subparsers.add_parser(
        "node", help="节点日收盘证据；此阶段不会加载T+1"
    )
    node_parser.add_argument("dates", nargs="+", help="节点日 YYYY-MM-DD")
    node_parser.add_argument(
        "--history-days", type=int, default=3, help="展示此前几个交易日的题材发酵，默认3"
    )
    node_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")

    pk_parser = subparsers.add_parser(
        "pk", help="梯队冻结后的T+1个股PK；参数为 YYYY-MM-DD:HEIGHT"
    )
    pk_parser.add_argument("nodes", nargs="+", type=parse_node_spec)
    pk_parser.add_argument(
        "--history-days", type=int, default=3, help="节点日发酵历史窗口，默认3"
    )
    pk_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")

    args = parser.parse_args()
    if args.history_days < 0:
        parser.error("--history-days 不能小于0")
    if args.command == "node":
        payload = [
            node_evidence(day, history_days=args.history_days) for day in args.dates
        ]
        emit(payload, args.format, markdown_node)
    else:
        payload = pk_evidence(args.nodes, history_days=args.history_days)
        emit(payload, args.format, markdown_pk)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
