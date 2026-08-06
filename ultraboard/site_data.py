# -*- coding: utf-8 -*-
"""站点公开数据适配器。

底层导出全部交易日的客观市场与涨停池数据；上层仅对算法识别出的自然高标
断板节点生成复盘和 09:25 竞价快照。人工训练标签不在本模块的依赖链中。

公开载荷主动剔除模型名、策略版本、公式、权重、阈值和后验收盘结果。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

from ultraboard.kaipanla.ladder_evidence import (
    as_float,
    as_int,
    available_trade_days,
    cached_ohlc,
    code_of,
    daily_stock_context,
    is_one_price,
    limit_reason_ranking,
    market_snapshot,
    next_trade_day,
    ohlc_map,
    seal_time,
)
from ultraboard.limits import limit_down_price, limit_up_price
from ultraboard.review.auction_score import review_days
from ultraboard.review.break_nodes import detect_break_node, list_break_nodes
from ultraboard.review.candidate_initial_score import score_day


ROOT = Path(__file__).resolve().parents[1]
NON_TRADING_PATH = ROOT / "data" / "kaipanla" / "non_trading_days.json"
CN_TZ = timezone(timedelta(hours=8))
COMPONENT_LABELS = {
    "layer_model_height": "梯队结构",
    "market_theme_position": "市场题材",
    "candidate_theme_role": "板块地位",
    "seal_initiative": "上板主动性",
    "post_seal_propagation": "后续助攻",
}
COMPONENT_PUBLIC_KEYS = {
    "layer_model_height": "layer_structure",
    "market_theme_position": "market_theme",
    "candidate_theme_role": "sector_role",
    "seal_initiative": "seal_initiative",
    "post_seal_propagation": "post_seal_support",
}
VOLUME_SHRINK_MAX = 0.75
VOLUME_BURST_MIN = 1.50


def compact_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def number(value: Any) -> float | None:
    parsed = as_float(value)
    return round(parsed, 4) if parsed is not None else None


def integer(value: Any) -> int | None:
    parsed = as_float(value)
    return int(parsed) if parsed is not None else None


def amount_of(stock: dict[str, Any]) -> int | None:
    raw = stock.get("raw")
    if not isinstance(raw, list) or len(raw) <= 11:
        return None
    return integer(raw[11])


def one_price_of(stock: dict[str, Any]) -> bool:
    return is_one_price(stock)


def bar_for(code: str, day: str) -> dict[str, Any]:
    return ohlc_map(day).get(code) or cached_ohlc(code, day)


def china_iso(day: str, clock: str) -> str:
    return f"{day}T{clock}+08:00"


def next_expected_trade_day(day: str) -> str:
    known = next_trade_day(day)
    if known:
        return known
    excluded = set()
    if NON_TRADING_PATH.exists():
        excluded = set(json.loads(NON_TRADING_PATH.read_text(encoding="utf-8-sig")))
    cursor = date.fromisoformat(day) + timedelta(days=1)
    while cursor.weekday() >= 5 or cursor.isoformat() in excluded:
        cursor += timedelta(days=1)
    return cursor.isoformat()


def daily_market_payload(day: str) -> dict[str, Any]:
    context = daily_stock_context(day)
    ranking = limit_reason_ranking(day)
    market = market_snapshot(
        day,
        context["by_day"],
        context["pool"],
        limit_reason_ranking=ranking,
    )
    return {
        "schemaVersion": 1,
        "tradeDate": day,
        "dataCutoff": f"{day} 收盘",
        "limitCount": int(market.get("limit_count") or 0),
        "firstBoardCount": int(market.get("first_board_count") or 0),
        "ge2Count": int(market.get("ge2_count") or 0),
        "maxBoard": int(market.get("max_board") or 0),
        "fanbaoCount": int(context["pool"].get("fanbao_count") or 0),
        "breakRate": number(market.get("main_market_break_pct")),
        "boardCounts": {
            str(key): int(value)
            for key, value in (market.get("board_counts") or {}).items()
        },
        "promotion": {
            "oneToTwoPct": number((market.get("promotion") or {}).get("one_to_two_pct")),
            "twoToThreePct": number((market.get("promotion") or {}).get("two_to_three_pct")),
            "highBoardPct": number((market.get("promotion") or {}).get("high_board_pct")),
        },
        "fermentationRanking": [
            {
                "rank": int(row["rank"]),
                "theme": str(row["theme"]),
                "count": int(row.get("reported_count") or 0),
                "turnoverAmount": int(row.get("turnover_amount") or 0),
                "displayColor": str(row.get("display_color") or "neutral"),
            }
            for row in ranking
        ],
        "topThemes": [
            {
                "theme": str(row["theme"]),
                "firstBoardCount": int(row.get("first_board_count") or 0),
            }
            for row in market.get("top_themes") or []
        ],
    }


def daily_stock_rows(day: str) -> list[dict[str, Any]]:
    context = daily_stock_context(day)
    rows = []
    for stock in context["stocks"]:
        code = code_of(stock.get("code"))
        bar = bar_for(code, day)
        identity = context["identities"][code]
        route = context["routes"][code]
        rows.append({
            "code": code,
            "name": str(stock.get("name") or ""),
            "boards": int(stock.get("boards") or 0),
            "boardsDesc": str(stock.get("boards_desc") or ""),
            "theme": str(stock.get("theme") or ""),
            "effectiveTheme": str(identity.get("effective_theme") or ""),
            "naturalTheme": identity.get("natural_theme"),
            "routeThemes": [str(item) for item in route.get("themes") or []],
            "themePath": [
                {
                    "date": str(step["date"]),
                    "height": int(step["height"]),
                    "theme": str(step.get("theme") or ""),
                }
                for step in route.get("steps") or []
            ],
            "sectorCode": str(stock.get("sector_code") or ""),
            "firstLimitAt": integer(stock.get("first_limit_ts")),
            "firstLimitTime": seal_time(stock.get("first_limit_ts")),
            "turnoverPct": number(stock.get("turnover_rate")),
            "amount": amount_of(stock),
            "closePrice": number(bar.get("close") or stock.get("price")),
            "limitPct": number(stock.get("limit_pct")),
            "openPrice": number(stock.get("open") or bar.get("open")),
            "highPrice": number(stock.get("high") or bar.get("high")),
            "lowPrice": number(stock.get("low") or bar.get("low")),
            "previousClose": number(stock.get("prev_close") or bar.get("prev_close")),
            "openPct": number(
                stock.get("open_pct")
                if stock.get("open_pct") is not None
                else bar.get("open_pct")
            ),
            "volume": number(bar.get("volume")),
            "isFanbao": bool(stock.get("is_fanbao")),
            "isAnnouncement": bool(identity["announcement"]),
            "announcementType": identity.get("announcement_type"),
            "announcementOriginDate": identity.get("announcement_origin_date"),
            "isOnePrice": one_price_of({**stock, **bar}),
        })
    rows.sort(key=lambda row: (-row["boards"], row["firstLimitAt"] or 10**20, row["code"]))
    return rows


def build_daily_bundle(day: str) -> dict[str, Any]:
    market = daily_market_payload(day)
    stocks = daily_stock_rows(day)
    revision = hashlib.sha256(
        compact_json({"market": market, "stocks": stocks}).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "schemaVersion": 1,
        "tradeDate": day,
        "publishedAt": china_iso(day, "18:00:00"),
        "revision": revision,
        "market": market,
        "stocks": stocks,
    }


def volume_state(ratio: float | None) -> str:
    if ratio is None:
        return "量能缺失"
    if ratio <= VOLUME_SHRINK_MAX:
        return "缩量"
    if ratio >= VOLUME_BURST_MIN:
        return "爆量"
    return "平量"


def previous_high_result(
    *,
    day: str,
    previous_day: str,
    leader: dict[str, Any],
) -> dict[str, Any]:
    code = leader["code"]
    current = bar_for(code, day)
    previous = bar_for(code, previous_day)
    prev_close = as_float(current.get("prev_close"))
    high = as_float(current.get("high"))
    close = as_float(current.get("close"))
    open_price = as_float(current.get("open"))
    up = limit_up_price(prev_close, code, leader["name"]) if prev_close else None
    down = limit_down_price(prev_close, code, leader["name"]) if prev_close else None
    touched = bool(up is not None and high is not None and high >= up - 0.005)
    if touched and down is not None and close is not None and close <= down + 0.005:
        outcome = "天地"
    elif touched:
        outcome = "炸板"
    elif high is not None:
        outcome = "未摸板"
    else:
        outcome = "断板"
    current_volume = as_float(current.get("volume"))
    previous_volume = as_float(previous.get("volume"))
    ratio = (
        current_volume / previous_volume
        if current_volume is not None and previous_volume not in (None, 0)
        else None
    )
    previous_context = daily_stock_context(previous_day)
    route = previous_context["routes"].get(code) or {}
    return {
        "code": code,
        "name": leader["name"],
        "height": int(leader["height"]),
        "theme": str(leader.get("theme") or ""),
        "routeThemes": [str(item) for item in route.get("themes") or []],
        "outcome": outcome,
        "volumeState": volume_state(ratio),
        "volumeRatio": round(ratio, 2) if ratio is not None else None,
        "openPct": (
            round((open_price / prev_close - 1) * 100, 2)
            if open_price is not None and prev_close
            else None
        ),
        "closePct": (
            round((close / prev_close - 1) * 100, 2)
            if close is not None and prev_close
            else None
        ),
    }


def build_review_snapshot(day: str) -> dict[str, Any]:
    detector = detect_break_node(day)
    if not detector["is_break_node"]:
        raise ValueError(f"{day} 不是自然最高梯队全部断板节点")
    score = score_day(day)
    target_value = score["stage1"].get("target_height")
    if target_value is None:
        raise ValueError(f"{day} 第一阶段没有自然目标梯队，不发布复盘快照")
    target_height = int(target_value)
    context = daily_stock_context(day)
    market = daily_market_payload(day)
    reason_by_theme = {
        row["theme"]: row for row in market["fermentationRanking"]
    }
    all_layer = [
        stock
        for stock in context["stocks"]
        if int(stock.get("boards") or 0) == target_height
    ]
    scored_by_code = {
        row["code"]: row for row in score.get("candidates") or []
    }
    candidates = []
    for stock in all_layer:
        code = code_of(stock.get("code"))
        identity = context["identities"][code]
        route = context["routes"][code]
        scored = scored_by_code.get(code)
        selected = (scored or {}).get("selected_theme_evidence") or {}
        timeline = selected.get("timeline") or {}
        components = (scored or {}).get("component_scores") or {}
        if identity["announcement"]:
            role = "volume_anchor" if one_price_of(stock) else "announcement_structure"
        else:
            role = "candidate"
        candidates.append({
            "code": code,
            "name": str(stock.get("name") or ""),
            "height": target_height,
            "score": number((scored or {}).get("expected_auction_score")),
            "scoreRank": integer((scored or {}).get("rank")),
            "grade": (scored or {}).get("expectation_grade"),
            "theme": str(stock.get("theme") or ""),
            "effectiveTheme": str(identity.get("effective_theme") or ""),
            "routeThemes": [
                {
                    "name": str(theme),
                    "rank": (reason_by_theme.get(theme) or {}).get("rank"),
                    "count": (reason_by_theme.get(theme) or {}).get("count"),
                }
                for theme in route.get("themes") or []
            ],
            "isAnnouncement": bool(identity["announcement"]),
            "announcementType": identity.get("announcement_type"),
            "onePrice": one_price_of(stock),
            "role": role,
            "metrics": {
                "openPct": number(stock.get("open_pct")),
                "firstSeal": seal_time(stock.get("first_limit_ts")),
                "turnoverPct": number(stock.get("turnover_rate")),
            },
            "components": [
                {
                    "key": COMPONENT_PUBLIC_KEYS[key],
                    "label": COMPONENT_LABELS[key],
                    "score": number(value),
                }
                for key, value in components.items()
                if key in COMPONENT_LABELS
            ],
            "evidence": {
                "marketRank": selected.get("limit_reason_rank"),
                "marketCount": int(selected.get("limit_reason_reported_count") or 0),
                "sectorRole": str(selected.get("candidate_role") or (
                    "公告量能锚，不参与自然票评分"
                    if identity["announcement"]
                    else "自然候选"
                )),
                "beforeCount": int(timeline.get("before_count") or 0),
                "sameSecondCount": int(timeline.get("same_second_count") or 0),
                "afterCount": int(timeline.get("after_count") or 0),
                "teammateCount": int(timeline.get("natural_peer_count") or 0),
                "routePath": [
                    {
                        "date": str(step["date"]),
                        "height": int(step["height"]),
                        "theme": str(step.get("theme") or ""),
                    }
                    for step in route.get("steps") or []
                ],
                "warnings": [str(item) for item in (scored or {}).get("warnings") or []],
            },
        })
    candidates.sort(key=lambda row: (
        row["score"] is None,
        -(row["score"] or 0),
        row["metrics"]["firstSeal"] or "99:99:99",
        row["code"],
    ))

    ladders = []
    heights = sorted(
        {int(stock.get("boards") or 0) for stock in context["stocks"] if int(stock.get("boards") or 0) >= 2},
        reverse=True,
    )
    for height in heights:
        members = [
            stock for stock in context["stocks"]
            if int(stock.get("boards") or 0) == height
        ]
        if not members:
            continue
        identities = [context["identities"][code_of(stock.get("code"))] for stock in members]
        ladders.append({
            "height": height,
            "count": len(members),
            "naturalCount": sum(not item["announcement"] for item in identities),
            "announcementCount": sum(bool(item["announcement"]) for item in identities),
            "onePriceCount": sum(one_price_of(stock) for stock in members),
            "target": height == target_height,
        })

    return {
        "schemaVersion": 1,
        "capability": "break_day",
        "nodeDate": day,
        "actionDate": next_expected_trade_day(day),
        "dataCutoff": f"{day} 收盘",
        "publishedAt": china_iso(day, "18:00:00"),
        "targetHeight": target_height,
        "buyModel": str(score["stage1"].get("model") or "无"),
        "market": {
            "limitCount": market["limitCount"],
            "firstBoardCount": market["firstBoardCount"],
            "ge2Count": market["ge2Count"],
            "maxBoard": market["maxBoard"],
            "breakRate": market["breakRate"],
            "boardCounts": market["boardCounts"],
            "fermentationRanking": market["fermentationRanking"],
        },
        "previousNaturalHighs": [
            previous_high_result(
                day=day,
                previous_day=detector["previous_date"],
                leader=leader,
            )
            for leader in detector["previous_natural_leaders"]
        ],
        "ladders": ladders,
        "candidates": candidates,
    }


def action_status(row: dict[str, Any]) -> tuple[str, str]:
    trading_status = str(
        (row.get("actual_auction") or {}).get("trading_status") or ""
    )
    if trading_status == "not_traded":
        return "停牌/无交易", "行动日经双行情源确认无日K，不属于数据缺失"
    actual = as_float((row.get("actual_auction") or {}).get("score"))
    delta = as_float(row.get("surprise_delta"))
    normalized = as_float((row.get("actual_auction") or {}).get("normalized_open"))
    if actual is None or delta is None:
        return "数据待齐", "冻结梯队内竞价数据尚未完整"
    if normalized is not None and normalized >= 0.995:
        return "观察", "涨停价竞价；历史数据没有委托队列，不能判断是否买得到"
    if delta <= -15:
        return "预期破坏", "实际竞价相对节点日要求大幅走弱"
    if actual >= 80 and delta >= 7:
        return "等待上板确认", "竞价强度与超预期幅度同时成立"
    if actual >= 70 and delta >= -7:
        return "观察", "竞价保持强势，但仍需等价格行为确认"
    return "暂不操作", "竞价强度或相对预期不足"


def build_auction_snapshot(day: str) -> dict[str, Any] | None:
    action_day = next_trade_day(day)
    if not action_day:
        return None
    pack = review_days([day], fetch_missing=True)[0]
    rows = pack.get("candidates") or []
    covered = [
        row for row in rows
        if (row.get("actual_auction") or {}).get("score") is not None
    ]
    rank_by_code = {
        row["code"]: rank
        for rank, row in enumerate(
            sorted(
                covered,
                key=lambda item: -float(item["actual_auction"]["score"]),
            ),
            1,
        )
    }
    candidates = []
    for row in rows:
        auction = row.get("actual_auction") or {}
        status, reason = action_status(row)
        candidates.append({
            "code": row["code"],
            "name": row["name"],
            "theme": row["scoring_theme"],
            "nodeScore": number(row["expected_auction_score"]),
            "auctionScore": number(auction.get("score")),
            "delta": number(row.get("surprise_delta")),
            "surpriseLabel": str(row.get("surprise_label") or "无法计算"),
            "auctionLabel": str(row.get("absolute_auction_label") or "无法计算"),
            "openPct": number(auction.get("open_pct")),
            "limitPct": number(auction.get("limit_pct")),
            "normalizedOpen": number(auction.get("normalized_open")),
            "layerRank": rank_by_code.get(row["code"]),
            "layerSize": len(rows),
            "sectorAssistCount": None,
            "onePriceAssistCount": None,
            "sealedOnePrice": None,
            "actionStatus": status,
            "statusReason": reason,
        })
    candidates.sort(key=lambda row: (
        row["layerRank"] is None,
        row["layerRank"] or 10**6,
        row["code"],
    ))
    return {
        "schemaVersion": 1,
        "capability": "break_day",
        "nodeDate": day,
        "actionDate": action_day,
        "targetHeight": int(pack["stage1"]["target_height"]),
        "snapshotAt": china_iso(action_day, "09:25:00"),
        "dataCutoff": f"{action_day} 09:25",
        "isFinal": True,
        "candidates": candidates,
    }


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def epoch_ms(value: str) -> int:
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def insert_statements(
    table: str,
    columns: list[str],
    rows: Iterable[list[Any]],
    *,
    chunk_size: int = 5,
) -> list[str]:
    statements = []
    chunk: list[list[Any]] = []
    for row in rows:
        chunk.append(row)
        if len(chunk) >= chunk_size:
            statements.append(_insert_statement(table, columns, chunk))
            chunk = []
    if chunk:
        statements.append(_insert_statement(table, columns, chunk))
    return statements


def _insert_statement(table: str, columns: list[str], rows: list[list[Any]]) -> str:
    values = ",\n".join(
        "(" + ",".join(sql_literal(value) for value in row) + ")"
        for row in rows
    )
    return f"INSERT INTO {table} ({','.join(columns)}) VALUES\n{values};"


def build_seed_sql() -> tuple[str, dict[str, int]]:
    days = list(available_trade_days())
    bundles = [build_daily_bundle(day) for day in days]
    nodes = list_break_nodes()
    selected_nodes = [
        row
        for row in nodes
        if score_day(row["date"])["stage1"].get("target_height") is not None
    ]
    reviews = [build_review_snapshot(row["date"]) for row in selected_nodes]
    auctions = [
        snapshot
        for row in selected_nodes
        if (snapshot := build_auction_snapshot(row["date"])) is not None
    ]
    statements = [
        "DELETE FROM auction_snapshots;",
        "DELETE FROM review_snapshots;",
        "DELETE FROM daily_limit_stocks;",
        "DELETE FROM trading_days;",
    ]
    statements += insert_statements(
        "trading_days",
        [
            "trade_date", "revision", "limit_count", "first_board_count",
            "ge2_count", "max_board", "market_payload", "published_at", "updated_at",
        ],
        (
            [
                bundle["tradeDate"], bundle["revision"], bundle["market"]["limitCount"],
                bundle["market"]["firstBoardCount"], bundle["market"]["ge2Count"],
                bundle["market"]["maxBoard"], compact_json(bundle["market"]),
                epoch_ms(bundle["publishedAt"]), epoch_ms(bundle["publishedAt"]),
            ]
            for bundle in bundles
        ),
    )
    stock_columns = [
        "trade_date", "revision", "code", "name", "boards", "boards_desc",
        "theme", "route_themes", "theme_path", "sector_code", "first_limit_at",
        "first_limit_time", "turnover_pct", "amount", "close_price", "limit_pct",
        "open_price", "high_price", "low_price", "previous_close", "open_pct",
        "volume", "is_fanbao", "is_announcement", "announcement_type",
        "announcement_origin_date", "is_one_price",
    ]
    statements += insert_statements(
        "daily_limit_stocks",
        stock_columns,
        (
            [
                bundle["tradeDate"], bundle["revision"], stock["code"], stock["name"],
                stock["boards"], stock["boardsDesc"], stock["theme"],
                compact_json(stock["routeThemes"]), compact_json(stock["themePath"]),
                stock["sectorCode"], stock["firstLimitAt"], stock["firstLimitTime"],
                stock["turnoverPct"], stock["amount"], stock["closePrice"],
                stock["limitPct"], stock["openPrice"], stock["highPrice"],
                stock["lowPrice"], stock["previousClose"], stock["openPct"],
                stock["volume"], stock["isFanbao"], stock["isAnnouncement"],
                stock["announcementType"], stock["announcementOriginDate"],
                stock["isOnePrice"],
            ]
            for bundle in bundles
            for stock in bundle["stocks"]
        ),
    )
    statements += insert_statements(
        "review_snapshots",
        [
            "capability", "node_date", "action_date", "target_height", "published_at",
            "payload", "created_at", "updated_at",
        ],
        (
            [
                snapshot["capability"], snapshot["nodeDate"], snapshot["actionDate"],
                snapshot["targetHeight"], epoch_ms(snapshot["publishedAt"]),
                compact_json(snapshot), epoch_ms(snapshot["publishedAt"]),
                epoch_ms(snapshot["publishedAt"]),
            ]
            for snapshot in reviews
        ),
    )
    statements += insert_statements(
        "auction_snapshots",
        [
            "capability", "node_date", "action_date", "captured_at", "is_final",
            "payload", "created_at",
        ],
        (
            [
                snapshot["capability"], snapshot["nodeDate"], snapshot["actionDate"],
                epoch_ms(snapshot["snapshotAt"]), snapshot["isFinal"],
                compact_json(snapshot), epoch_ms(snapshot["snapshotAt"]),
            ]
            for snapshot in auctions
        ),
    )
    statements.append("PRAGMA optimize;")
    sql = "\n--> statement-breakpoint\n".join(statements) + "\n"
    return sql, {
        "trading_days": len(bundles),
        "limit_stock_rows": sum(len(bundle["stocks"]) for bundle in bundles),
        "break_nodes": len(reviews),
        "auction_snapshots": len(auctions),
    }


def publish(base_url: str, token: str) -> dict[str, int]:
    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {token}"}
    days = list(available_trade_days())
    nodes = list_break_nodes()
    selected_nodes = [
        node
        for node in nodes
        if score_day(node["date"])["stage1"].get("target_height") is not None
    ]
    for day in days:
        response = requests.post(
            f"{base}/api/ingest/daily",
            json=build_daily_bundle(day),
            headers=headers,
            timeout=60,
        )
        response.raise_for_status()
    for node in selected_nodes:
        review = build_review_snapshot(node["date"])
        response = requests.post(
            f"{base}/api/ingest/review",
            json=review,
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        auction = build_auction_snapshot(node["date"])
        if auction:
            response = requests.post(
                f"{base}/api/ingest/auction",
                json=auction,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
    return {
        "trading_days": len(days),
        "break_nodes": len(selected_nodes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("summary", help="统计全量日期与算法节点")
    seed_parser = subparsers.add_parser("seed-sql", help="生成公开数据 D1 迁移")
    seed_parser.add_argument("output", type=Path)
    publish_parser = subparsers.add_parser("publish", help="通过站点写入接口增量发布")
    publish_parser.add_argument("--url", default=os.environ.get("ULTRABOARD_SITE_URL"))
    publish_parser.add_argument("--token", default=os.environ.get("ULTRABOARD_INGEST_TOKEN"))
    args = parser.parse_args(argv)

    if args.command == "summary":
        nodes = list_break_nodes()
        print(compact_json({
            "trading_days": len(available_trade_days()),
            "first_date": available_trade_days()[0],
            "last_date": available_trade_days()[-1],
            "break_nodes": len(nodes),
            "first_node": nodes[0]["date"] if nodes else None,
            "last_node": nodes[-1]["date"] if nodes else None,
        }))
        return 0
    if args.command == "seed-sql":
        sql, counts = build_seed_sql()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(sql, encoding="utf-8")
        print(compact_json({**counts, "output": str(args.output)}))
        return 0
    if not args.url or not args.token:
        parser.error("publish requires --url/ULTRABOARD_SITE_URL and --token/ULTRABOARD_INGEST_TOKEN")
    print(compact_json(publish(args.url, args.token)))
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
