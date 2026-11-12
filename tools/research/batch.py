"""Lightweight ten-record research batch preparation, commit and verification."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
BATCH_SCHEMA_VERSION = 1


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _name(connection, stock_id: int) -> str | None:
    row = connection.execute(
        """SELECT name FROM stock_names WHERE stock_id=?
           ORDER BY CASE WHEN valid_to IS NULL THEN 0 ELSE 1 END, valid_from DESC, id DESC LIMIT 1""",
        (stock_id,),
    ).fetchone()
    return row["name"] if row else None


def _stock_identity(connection, stock_id: int) -> dict[str, Any]:
    row = connection.execute("SELECT code FROM stocks WHERE id=?", (stock_id,)).fetchone()
    return {"stock_id": stock_id, "code": row["code"], "name": _name(connection, stock_id)}


def _latest_attributes(connection, stock_id: int) -> dict[str, Any]:
    latest = connection.execute(
        "SELECT MAX(observed_date) AS value FROM stock_concepts WHERE stock_id=?",
        (stock_id,),
    ).fetchone()["value"]
    if not latest:
        return {"effective_date": None, "tags": [], "sources": [], "snapshot_status": "missing"}
    rows = connection.execute(
        """SELECT c.unified_name,c.source_name,e.path,sc.historical_status,sc.captured_date
           FROM stock_concepts sc JOIN concepts c ON c.id=sc.concept_id
           LEFT JOIN evidence_files e ON e.id=sc.evidence_file_id
           WHERE sc.stock_id=? AND sc.observed_date=?
           ORDER BY c.unified_name,c.source_name""",
        (stock_id, latest),
    ).fetchall()
    tags = sorted({row["unified_name"] or row["source_name"] for row in rows})
    sources = sorted({row["path"] for row in rows if row["path"]})
    return {
        "effective_date": latest,
        "captured_dates": sorted({row["captured_date"] for row in rows if row["captured_date"]}),
        "tags": tags,
        "sources": sources,
        "snapshot_status": "latest_complete_snapshot",
    }


def _daily_row(connection, stock_id: int, trade_date: str) -> dict[str, Any] | None:
    row = connection.execute(
        """SELECT d.*,e.path AS evidence_path FROM daily_market d
           LEFT JOIN evidence_files e ON e.id=d.evidence_file_id
           WHERE d.stock_id=? AND d.trade_date=?
           ORDER BY CASE d.source_type WHEN 'kaipanla_limit_pool' THEN 0 ELSE 1 END,d.id LIMIT 1""",
        (stock_id, trade_date),
    ).fetchone()
    if not row:
        return None
    raw = json.loads(row["raw_json"])
    return {
        "date": trade_date,
        "source_type": row["source_type"],
        "board_height": row["board_height"],
        "strict_one_word": bool(row["strict_one_word"]) if row["strict_one_word"] is not None else None,
        "first_limit_time": row["first_limit_time"],
        "close": row["close_milli"] / 1000 if row["close_milli"] is not None else None,
        "limit_up": row["limit_up_milli"] / 1000 if row["limit_up_milli"] is not None else None,
        "theme": raw.get("theme"),
        "theme_tags": raw.get("theme_tags_text"),
        "raw": raw,
        "source": row["evidence_path"],
    }


def _trading_dates(connection) -> list[str]:
    return [
        row["trade_date"]
        for row in connection.execute(
            "SELECT DISTINCT trade_date FROM daily_market WHERE source_type='kaipanla_limit_pool' ORDER BY trade_date"
        )
    ]


def _previous_date(dates: list[str], value: str | None) -> str | None:
    if not value:
        return None
    earlier = [date for date in dates if date < value]
    return earlier[-1] if earlier else None


def _confirmed_theme(connection, stock_id: int, trade_date: str) -> str | None:
    row = connection.execute(
        """SELECT confirmed_main_theme FROM launch_rounds
           WHERE stock_id=? AND confirmed_main_theme IS NOT NULL AND first_board_date<=?
           ORDER BY first_board_date DESC,focus_date DESC LIMIT 1""",
        (stock_id, trade_date),
    ).fetchone()
    return row["confirmed_main_theme"] if row else None


def _global_pool(connection, pool_type: str, pool_date: str, batch_key: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT pm.stock_id,pm.board_height,pm.member_status,pm.query_direction,e.path AS evidence_path
           FROM stock_pools p JOIN pool_members pm ON pm.pool_id=p.id
           LEFT JOIN evidence_files e ON e.id=pm.evidence_file_id
           WHERE p.pool_type=? AND p.pool_date=? AND p.input_version=? AND p.candidate_event_id IS NULL
           ORDER BY pm.board_height DESC,pm.stock_id""",
        (pool_type, pool_date, batch_key),
    ).fetchall()
    result = []
    for row in rows:
        item = _stock_identity(connection, row["stock_id"])
        item.update({
            "board_height": row["board_height"],
            "status": row["member_status"],
            "query_direction": row["query_direction"],
            "source": row["evidence_path"],
        })
        result.append(item)
    return result


def _high_pool(connection, dates: list[str], pool_date: str, batch_key: str) -> dict[str, Any]:
    advanced = _global_pool(connection, "high_standard", pool_date, batch_key)
    previous = _previous_date(dates, pool_date)
    previous_high = _global_pool(connection, "high_standard", previous, batch_key) if previous else []
    current_codes = {item["code"] for item in advanced}
    broken = []
    for item in previous_high:
        if item["code"] in current_codes or (item.get("board_height") or 0) < 4:
            continue
        broken_item = dict(item)
        broken_item["status"] = f"{item['board_height']}板断板"
        broken_item["source"] = [item.get("source"), f"data/kaipanla/raw/{pool_date}/zt_pool.json"]
        broken.append(broken_item)
    members = advanced + broken
    for item in members:
        daily = _daily_row(connection, item["stock_id"], pool_date) or (
            _daily_row(connection, item["stock_id"], previous) if previous else None
        )
        item["theme_hint"] = daily.get("theme") if daily else None
        item["theme_tags_hint"] = daily.get("theme_tags") if daily else None
        item["confirmed_main_theme"] = _confirmed_theme(connection, item["stock_id"], pool_date)
    return {"date": pool_date, "members": members, "previous_trade_date": previous}


def _raw_scope(root: Path, date: str) -> dict[str, Any]:
    path = root / "data/kaipanla/raw" / date / "zt_pool.json"
    if not path.exists():
        return {"date": date, "source": None, "excluded_bse": [], "st_rows": [], "status": "source_missing"}
    raw = _read_json(path)
    excluded = raw.get("source_reconciliation", {}).get("excluded_bse", [])
    st_rows = [
        row for row in raw.get("stocks", [])
        if "ST" in str(row.get("name", "")).upper() or "ST板块" in str(row.get("theme_tags_text", ""))
    ]
    compact = lambda row: {
        "code": row.get("code"), "name": row.get("name"), "board_height": row.get("boards"),
        "strict_one_word": bool(len(row.get("raw", [])) > 17 and row["raw"][16] == 0 and row["raw"][17] == 0),
        "theme": row.get("theme"), "theme_tags": row.get("theme_tags_text"),
    }
    return {
        "date": date,
        "source": path.relative_to(root).as_posix(),
        "excluded_bse": [compact(row) for row in excluded],
        "st_rows": [compact(row) for row in st_rows],
        "status": "checked",
    }


def _sina_market(root: Path, code: str, event_date: str | None) -> dict[str, Any]:
    if not event_date:
        return {"event_date": None, "source": None, "previous": None, "event": None}
    path = root / "data/price_checks/sina_history" / f"{code}.json"
    if not path.exists():
        return {"event_date": event_date, "source": None, "previous": None, "event": None}
    records = _read_json(path).get("records", [])
    index = next((i for i, row in enumerate(records) if row.get("day") == event_date), None)
    return {
        "event_date": event_date,
        "source": path.relative_to(root).as_posix(),
        "previous": records[index - 1] if index is not None and index > 0 else None,
        "event": records[index] if index is not None else None,
    }


def _announcement_sources(root: Path, dates: list[str], code: str, start: str | None, end: str) -> list[str]:
    begin = _previous_date(dates, start) or start or end
    sources = []
    for date in dates:
        if begin <= date <= end:
            path = root / "data/kaipanla/raw" / date / "historical_messages.json"
            if path.exists():
                sources.append(path.relative_to(root).as_posix())
    checks = root / "data/research/announcement_checks_2025"
    sources.extend(path.relative_to(root).as_posix() for path in sorted(checks.glob(f"{code}_*.json")))
    return sorted(set(sources))


def _competitor_candidates(connection, dates: list[str], stock_id: int, focus_date: str, event_date: str | None) -> dict[str, Any]:
    previous = _previous_date(dates, event_date)
    candidate_daily = _daily_row(connection, stock_id, focus_date)
    height = candidate_daily.get("board_height") if candidate_daily else None
    if not previous or height is None:
        return {"date": previous, "candidate_height": height, "members": []}
    rows = connection.execute(
        """SELECT d.stock_id,d.board_height,e.path AS evidence_path,d.raw_json
           FROM daily_market d LEFT JOIN evidence_files e ON e.id=d.evidence_file_id
           WHERE d.trade_date=? AND d.source_type='kaipanla_limit_pool' AND d.board_height>=? AND d.stock_id<>?
           ORDER BY d.board_height DESC,d.stock_id""",
        (previous, height, stock_id),
    ).fetchall()
    members = []
    for row in rows:
        item = _stock_identity(connection, row["stock_id"])
        raw = json.loads(row["raw_json"])
        item.update({
            "board_height": row["board_height"],
            "theme_hint": raw.get("theme"),
            "theme_tags_hint": raw.get("theme_tags_text"),
            "attributes": _latest_attributes(connection, row["stock_id"]),
            "source": row["evidence_path"],
        })
        members.append(item)
    return {"date": previous, "candidate_height": height, "members": members}


def _select_records(connection, limit: int, year: int | None, record_keys: list[str] | None) -> list[Any]:
    base = """SELECT r.*,f.event_date,f.event_status,l.stock_id,l.first_board_date,l.focus_date,l.board_sequence_text,
                     s.code,l.id AS launch_round_id,f.id AS event_id
              FROM current_static_research r JOIN first_open_events f ON f.id=r.first_open_event_id
              JOIN launch_rounds l ON l.id=f.launch_round_id JOIN stocks s ON s.id=l.stock_id"""
    if record_keys:
        rows = []
        for key in record_keys:
            row = connection.execute(base + " WHERE r.legacy_record_key=?", (key,)).fetchone()
            if not row:
                raise KeyError(key)
            rows.append(row)
        return rows
    cursor_row = connection.execute("SELECT value FROM store_meta WHERE key='research_cursor'").fetchone()
    cursor = json.loads(cursor_row["value"]) if cursor_row else None
    conditions = ["r.research_status='unresearched'"]
    params: list[Any] = []
    if year is not None:
        conditions.append("l.focus_date LIKE ?")
        params.append(f"{year:04d}-%")
    if cursor and (year is None or int(cursor.get("year", 0)) == year):
        conditions.append("(l.focus_date>? OR (l.focus_date=? AND r.legacy_record_key>?))")
        params.extend([cursor["focus_date"], cursor["focus_date"], cursor["record_key"]])
    query = base + " WHERE " + " AND ".join(conditions) + " ORDER BY l.focus_date,r.legacy_record_key LIMIT ?"
    params.append(limit)
    return connection.execute(query, params).fetchall()


def _record_facts(store, connection, dates: list[str], batch_key: str, row: Any) -> dict[str, Any]:
    stock_id = int(row["stock_id"])
    code = row["code"]
    first_two = []
    for date in dates:
        if row["first_board_date"] and row["first_board_date"] <= date <= row["focus_date"]:
            daily = _daily_row(connection, stock_id, date)
            if daily and daily.get("board_height") in {1, 2}:
                first_two.append(daily)
        if len(first_two) == 2:
            break
    strict_days = []
    scope_dates = {row["first_board_date"], row["focus_date"]}
    for date in dates:
        if row["first_board_date"] and row["first_board_date"] <= date <= row["focus_date"]:
            candidate = _daily_row(connection, stock_id, date)
            if not candidate or not candidate.get("strict_one_word"):
                continue
            scope_dates.add(date)
            higher = []
            for member in _global_pool(connection, "strict_one_word", date, batch_key):
                if (member.get("board_height") or 0) <= (candidate.get("board_height") or 0):
                    continue
                member["attributes"] = _latest_attributes(connection, member["stock_id"])
                higher.append(member)
            strict_days.append({
                "date": date,
                "candidate_height": candidate.get("board_height"),
                "source": candidate.get("source"),
                "higher_members": higher,
            })
    dynamic = connection.execute(
        """SELECT d.* FROM current_dynamic_research d JOIN research_plans p ON p.id=d.plan_id
           WHERE d.legacy_record_key=? AND p.plan_code='formal'""",
        (row["legacy_record_key"],),
    ).fetchone()
    transaction_path = store.root / "data/price_checks/tdx_transactions" / code / f"{row['event_date']}.json"
    market = _sina_market(store.root, code, row["event_date"])
    market["kaipanla"] = _daily_row(connection, stock_id, row["event_date"]) if row["event_date"] else None
    market["transaction_source"] = transaction_path.relative_to(store.root).as_posix() if transaction_path.exists() else None
    return {
        "record_key": row["legacy_record_key"],
        "identity": {
            "stock_id": stock_id,
            "code": code,
            "name": _name(connection, stock_id),
            "first_board_date": row["first_board_date"],
            "focus_date": row["focus_date"],
            "first_open_date": row["event_date"],
            "board_sequence": row["board_sequence_text"],
        },
        "current_status": {
            "static": row["research_status"],
            "static_confirmation": row["confirmation_status"],
            "dynamic": dynamic["research_status"] if dynamic else None,
        },
        "attributes": _latest_attributes(connection, stock_id),
        "first_two": first_two,
        "high_pool": _high_pool(connection, dates, row["first_board_date"], batch_key),
        "strict_one_word_days": strict_days,
        "scope_audit": [_raw_scope(store.root, date) for date in sorted(date for date in scope_dates if date)],
        "announcement_sources": _announcement_sources(store.root, dates, code, row["first_board_date"], row["focus_date"]),
        "first_open_market": market,
        "potential_competitor_candidates": _competitor_candidates(
            connection, dates, stock_id, row["focus_date"], row["event_date"]
        ),
        "current_static_raw": json.loads(row["raw_json"]),
        "current_dynamic_raw": json.loads(dynamic["raw_json"]) if dynamic else None,
    }


def _decision_template(fact: dict[str, Any], hydrate_current: bool) -> dict[str, Any]:
    raw = fact["current_static_raw"] if hydrate_current else {}
    dynamic = fact["current_dynamic_raw"] if hydrate_current and fact["current_dynamic_raw"] else {}
    return {
        "record_key": fact["record_key"],
        "static": {
            "main_theme": raw.get("唯一主炒作属性"),
            "main_theme_basis": raw.get("唯一主炒依据"),
            "replenishment_result": raw.get("补涨判断"),
            "mapping_basis": raw.get("映射依据"),
            "suppression_result": raw.get("压制判断"),
            "suppression_basis": raw.get("压制依据"),
            "suppression_details": raw.get("一字压制核验明细"),
            "announcement_pollution": raw.get("公告污染"),
            "announcement_basis": raw.get("公告污染依据"),
            "competitors": raw.get("首开潜在竞争对手事实清单"),
            "additional_evidence": [],
        },
        "dynamic": {
            "auction": dynamic.get("竞价筛选"),
            "pk_checks": dynamic.get("同题材PK核验明细"),
            "pk_result": dynamic.get("同题材PK结果"),
            "buy_point": dynamic.get("首开买点"),
            "market": dynamic.get("首开行情"),
            "outcome": dynamic.get("买入后结果"),
            "additional_evidence": [],
        },
    }


def prepare_batch(
    store,
    output_dir: Path,
    limit: int = 10,
    year: int | None = None,
    record_keys: list[str] | None = None,
    hydrate_current: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    if limit < 1 or limit > 10:
        raise ValueError("batch limit must be between 1 and 10")
    if record_keys and len(record_keys) > 10:
        raise ValueError("an explicit batch may contain at most 10 record keys")
    connection = store.connect()
    store.apply_migrations(connection)
    batch_key = connection.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()["value"]
    dates = _trading_dates(connection)
    selected = _select_records(connection, limit, year, record_keys)
    if not selected:
        connection.close()
        raise RuntimeError("no research records matched the batch selector")
    facts_records = [_record_facts(store, connection, dates, batch_key, row) for row in selected]
    connection.close()
    key_digest = hashlib.sha256("\n".join(fact["record_key"] for fact in facts_records).encode("utf-8")).hexdigest()[:8]
    batch_id = f"research-{facts_records[0]['identity']['focus_date']}-{facts_records[-1]['identity']['focus_date']}-{len(facts_records)}-{key_digest}"
    facts = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "prepared_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "selection": {"limit": limit, "year": year, "explicit_record_keys": record_keys or []},
        "records": facts_records,
    }
    decisions = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "records": [_decision_template(fact, hydrate_current) for fact in facts_records],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "facts.json", facts)
    _write_json(output_dir / "decisions.json", decisions)
    return {
        "batch_id": batch_id,
        "record_count": len(facts_records),
        "record_keys": [fact["record_key"] for fact in facts_records],
        "facts": str(output_dir / "facts.json"),
        "decisions": str(output_dir / "decisions.json"),
        "hydrate_current": hydrate_current,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _source_values(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            result.update(_source_values(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_source_values(item))
    elif isinstance(value, str) and (value.startswith("data/") or value.startswith("https://")):
        result.add(value)
    return result


def _load_pair(facts_path: Path, decisions_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    facts = _read_json(facts_path)
    decisions = _read_json(decisions_path)
    if facts.get("schema_version") != BATCH_SCHEMA_VERSION or decisions.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError("unsupported batch schema version")
    if facts.get("batch_id") != decisions.get("batch_id"):
        raise ValueError("facts and decisions batch_id mismatch")
    fact_keys = [row["record_key"] for row in facts.get("records", [])]
    decision_keys = [row["record_key"] for row in decisions.get("records", [])]
    if not fact_keys or fact_keys != decision_keys or len(set(fact_keys)) != len(fact_keys):
        raise ValueError("facts and decisions must contain the same ordered unique records")
    return facts, decisions


def _validate_decision(fact: dict[str, Any], decision: dict[str, Any]) -> bool:
    static = decision.get("static") or {}
    required = ["main_theme", "main_theme_basis", "replenishment_result", "mapping_basis", "suppression_result", "suppression_basis"]
    missing = [key for key in required if not static.get(key)]
    if missing or not isinstance(static.get("announcement_pollution"), bool):
        raise ValueError(f"{fact['record_key']} static decision incomplete: {missing or ['announcement_pollution']}")
    if static["replenishment_result"] not in {"补涨", "非补涨"}:
        raise ValueError(f"{fact['record_key']} invalid replenishment_result")
    if not (str(static["suppression_result"]).startswith("有") or str(static["suppression_result"]).startswith("无")):
        raise ValueError(f"{fact['record_key']} suppression_result must start with 有 or 无")
    passed = (
        static["replenishment_result"] == "非补涨"
        and str(static["suppression_result"]).startswith("无")
        and static["announcement_pollution"] is False
    )
    if passed and not isinstance(static.get("competitors"), list):
        raise ValueError(f"{fact['record_key']} passing record requires competitors array")
    if passed:
        dynamic = decision.get("dynamic") or {}
        missing_dynamic = [key for key in ["auction", "pk_checks", "pk_result", "buy_point", "outcome"] if dynamic.get(key) is None]
        if missing_dynamic:
            raise ValueError(f"{fact['record_key']} dynamic decision incomplete: {missing_dynamic}")
    return passed


def _request_id(batch_id: str, kind: str, key: str, updates: dict[str, Any]) -> str:
    digest = hashlib.sha256(_json(updates).encode("utf-8")).hexdigest()[:12]
    return f"{batch_id}-{kind}-{key.replace('|', '-')}-{digest}"


def _dynamic_updates(passed: bool, static: dict[str, Any], dynamic: dict[str, Any]) -> dict[str, Any]:
    if passed:
        updates = {
            "买入筛选": {"非补涨": True, "无一字压制": True, "无公告污染": True, "结果": "通过"},
            "竞价筛选": dynamic["auction"],
            "同题材PK核验明细": dynamic["pk_checks"],
            "同题材PK结果": dynamic["pk_result"],
            "首开买点": dynamic["buy_point"],
            "买入后结果": dynamic["outcome"],
        }
        if dynamic.get("market") is not None:
            updates["首开行情"] = dynamic["market"]
        return updates
    reasons = []
    if static["replenishment_result"] != "非补涨":
        reasons.append("补涨")
    if not str(static["suppression_result"]).startswith("无"):
        reasons.append("有一字压制")
    if static["announcement_pollution"]:
        reasons.append("公告污染")
    reason = "、".join(reasons)
    return {
        "买入筛选": {
            "非补涨": static["replenishment_result"] == "非补涨",
            "无一字压制": str(static["suppression_result"]).startswith("无"),
            "无公告污染": not static["announcement_pollution"],
            "结果": "淘汰",
            "依据": reason,
        },
        "竞价筛选": {"结果": "未进入", "依据": "三项筛选已淘汰"},
        "同题材PK核验明细": [],
        "同题材PK结果": "未进入：三项筛选已淘汰",
        "首开买点": {"结果": "未进入", "买点类型": None, "买点时间": None, "事实": "三项筛选已淘汰", "来源": []},
        "买入后结果": {"是否买入": False, "统计处理": "不进入买入样本"},
    }


def _requests_for_batch(facts: dict[str, Any], decisions: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for fact, decision in zip(facts["records"], decisions["records"]):
        passed = _validate_decision(fact, decision)
        static = decision["static"]
        evidence = sorted(_source_values(fact) | set(static.get("additional_evidence") or []))
        scope_summary = {
            "dates": [item["date"] for item in fact["scope_audit"]],
            "excluded_bse_count": sum(len(item["excluded_bse"]) for item in fact["scope_audit"]),
            "st_row_count": sum(len(item["st_rows"]) for item in fact["scope_audit"]),
            "status": "checked",
        }
        updates = {
            "开盘啦完整属性集": fact["attributes"]["tags"],
            "开盘啦完整属性来源": fact["attributes"]["sources"],
            "属性时点说明": f"使用{fact['attributes']['effective_date']}最晚完整属性快照；历史当日直接证据优先，特殊归并由判断依据单列。",
            "首二原始证据": fact["first_two"],
            "高标事实池": fact["high_pool"]["members"],
            "高标与一字范围核验": scope_summary,
            "唯一主炒作属性": static["main_theme"],
            "唯一主炒依据": static["main_theme_basis"],
            "补涨判断": static["replenishment_result"],
            "映射依据": static["mapping_basis"],
            "一字压制核验明细": static.get("suppression_details") or fact["strict_one_word_days"],
            "压制判断": static["suppression_result"],
            "压制依据": static["suppression_basis"],
            "公告污染": static["announcement_pollution"],
            "公告污染依据": static["announcement_basis"],
            "公告污染来源": fact["announcement_sources"],
            "静态三项结论": "通过" if passed else "不通过",
        }
        if passed:
            updates["首开潜在竞争对手事实清单"] = static["competitors"]
            updates["首开潜在竞争对手候选全集"] = fact["potential_competitor_candidates"]
        checks = [
            {"check_type":"高标事实池","outcome":"完整","basis":"高标、北交所和ST范围已自动准备并人工裁决。","sources":sorted(_source_values(fact["high_pool"]) | _source_values(fact["scope_audit"])),"raw":fact["high_pool"]["members"]},
            {"check_type":"唯一主炒","outcome":static["main_theme"],"basis":static["main_theme_basis"],"sources":sorted(_source_values(fact["first_two"]))},
            {"check_type":"补涨判断","outcome":static["replenishment_result"],"basis":static["mapping_basis"],"sources":fact["attributes"]["sources"]},
            {"check_type":"一字压制核验明细","outcome":static["suppression_result"],"basis":static["suppression_basis"],"sources":sorted(_source_values(fact["strict_one_word_days"])),"raw":updates["一字压制核验明细"]},
            {"check_type":"公告污染","outcome":str(static["announcement_pollution"]).lower(),"basis":static["announcement_basis"],"sources":fact["announcement_sources"]},
        ]
        if passed:
            checks.append({"check_type":"首开潜在竞争对手事实清单","outcome":"完整","basis":"按前日同身位及更高身位全集逐只裁决。","sources":sorted(_source_values(fact["potential_competitor_candidates"])),"raw":static["competitors"]})
        requests.append({
            "request_id": _request_id(facts["batch_id"], "static", fact["record_key"], updates),
            "record_key": fact["record_key"], "kind": "static", "research_status": "formal_source_record",
            "confirmation_status": "pending_user_confirmation", "evidence": evidence, "updates": updates, "checks": checks,
        })
        if passed:
            dynamic = decision["dynamic"]
            dynamic_updates = _dynamic_updates(True, static, dynamic)
            dynamic_checks = [
                {"check_type":"买入筛选","outcome":"通过","basis":"非补涨、无一字压制、无公告污染。","sources":[]},
                {"check_type":"竞价筛选","outcome":dynamic["auction"].get("结果"),"basis":dynamic["auction"].get("依据"),"sources":sorted(_source_values(fact["first_open_market"]))},
                {"check_type":"theme_pk","outcome":dynamic["pk_result"],"basis":"按静态竞争清单执行。","sources":sorted(_source_values(fact["potential_competitor_candidates"])),"raw":dynamic["pk_checks"]},
                {"check_type":"买点","outcome":dynamic["buy_point"].get("结果"),"basis":dynamic["buy_point"].get("事实"),"sources":dynamic["buy_point"].get("来源",[])},
            ]
        else:
            dynamic_updates = _dynamic_updates(False, static, {})
            reason = dynamic_updates["买入筛选"]["依据"]
            dynamic_checks = [{"check_type":"买入筛选","outcome":"淘汰","basis":reason,"sources":[]}]
        dynamic_evidence = sorted(set(evidence) | set((decision.get("dynamic") or {}).get("additional_evidence") or []))
        requests.append({
            "request_id": _request_id(facts["batch_id"], "dynamic", fact["record_key"], dynamic_updates),
            "record_key": fact["record_key"], "kind": "dynamic", "research_status": "source_record",
            "confirmation_status": "pending_user_confirmation", "evidence": dynamic_evidence,
            "updates": dynamic_updates, "checks": dynamic_checks,
        })
    return requests


def verify_batch(
    store,
    facts: dict[str, Any],
    decisions: dict[str, Any],
    set_cursor: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    connection = store.connect()
    store.apply_migrations(connection)
    findings: list[str] = []
    records = []
    for fact, decision in zip(facts["records"], decisions["records"]):
        try:
            passed = _validate_decision(fact, decision)
        except ValueError as exc:
            findings.append(str(exc))
            passed = False
        static = connection.execute(
            "SELECT * FROM current_static_research WHERE legacy_record_key=?", (fact["record_key"],)
        ).fetchone()
        dynamic = connection.execute(
            """SELECT d.* FROM current_dynamic_research d JOIN research_plans p ON p.id=d.plan_id
               WHERE d.legacy_record_key=? AND p.plan_code='formal'""", (fact["record_key"],)
        ).fetchone()
        if not static or static["research_status"] == "unresearched":
            findings.append(f"{fact['record_key']} static research missing")
            continue
        raw = json.loads(static["raw_json"])
        expected_static = {
            "唯一主炒作属性": decision["static"].get("main_theme"),
            "唯一主炒依据": decision["static"].get("main_theme_basis"),
            "补涨判断": decision["static"].get("replenishment_result"),
            "映射依据": decision["static"].get("mapping_basis"),
            "压制判断": decision["static"].get("suppression_result"),
            "压制依据": decision["static"].get("suppression_basis"),
            "公告污染": decision["static"].get("announcement_pollution"),
            "公告污染依据": decision["static"].get("announcement_basis"),
        }
        for key, value in expected_static.items():
            if raw.get(key) != value:
                findings.append(f"{fact['record_key']} static value mismatch: {key}")
        for key in ["开盘啦完整属性集","高标事实池","唯一主炒作属性","补涨判断","压制判断","公告污染","公告污染来源"]:
            if key not in raw:
                findings.append(f"{fact['record_key']} missing static field: {key}")
        check_types = {
            row["check_type"] for row in connection.execute(
                "SELECT check_type FROM research_checks WHERE static_research_id=?", (static["id"],)
            )
        }
        required_checks = {"高标事实池","唯一主炒","补涨判断","一字压制核验明细","公告污染"}
        if not required_checks.issubset(check_types):
            findings.append(f"{fact['record_key']} static checks incomplete")
        if not dynamic:
            findings.append(f"{fact['record_key']} dynamic research missing")
        else:
            dynamic_raw = json.loads(dynamic["raw_json"])
            expected_dynamic = _dynamic_updates(passed, decision["static"], decision.get("dynamic") or {})
            for key, value in expected_dynamic.items():
                actual = dynamic_raw.get(key)
                if key == "买入筛选" and isinstance(actual, dict) and isinstance(value, dict):
                    conclusion_keys = ("非补涨", "无一字压制", "无公告污染", "结果")
                    matches = all(actual.get(item) == value.get(item) for item in conclusion_keys)
                    if value.get("结果") == "淘汰" and not actual.get("依据"):
                        matches = False
                else:
                    matches = actual == value
                if not matches:
                    findings.append(f"{fact['record_key']} dynamic value mismatch: {key}")
            for key in ["买入筛选","竞价筛选","同题材PK结果","首开买点","买入后结果"]:
                if key not in dynamic_raw:
                    findings.append(f"{fact['record_key']} missing dynamic field: {key}")
            outcome = dynamic_raw.get("买入后结果") or {}
            if outcome.get("是否买入") is True and (dynamic["buy_price_milli"] is None or dynamic["sell_time"] is None):
                findings.append(f"{fact['record_key']} bought outcome lacks price or sell date")
        if passed and "首开潜在竞争对手事实清单" not in raw:
            findings.append(f"{fact['record_key']} passing record lacks competitor list")
        records.append({
            "record_key": fact["record_key"],
            "static_pass": passed,
        })
    if not findings and set_cursor:
        last = max(facts["records"], key=lambda row: (row["identity"]["focus_date"], row["record_key"]))
        cursor = {"year":int(last["identity"]["focus_date"][:4]),"focus_date":last["identity"]["focus_date"],"record_key":last["record_key"],"batch_id":facts["batch_id"]}
        connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('research_cursor',?)", (_json(cursor),))
        connection.commit()
    connection.close()
    return {
        "passed": not findings,
        "batch_id": facts["batch_id"],
        "record_count": len(records),
        "records": records,
        "findings": findings,
        "cursor_updated": bool(set_cursor and not findings),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def commit_batch(
    store,
    facts_path: Path,
    decisions_path: Path,
    publish: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    facts, decisions = _load_pair(facts_path, decisions_path)
    requests = _requests_for_batch(facts, decisions)
    results = [store.write_research(request) for request in requests]
    verification = verify_batch(store, facts, decisions, set_cursor=True)
    if not verification["passed"]:
        raise RuntimeError(f"batch verification failed: {verification['findings']}")
    export = store.export_all(publish_root=True) if publish else None
    return {
        "batch_id": facts["batch_id"],
        "record_count": len(facts["records"]),
        "write_count": len(results),
        "verification": verification,
        "export": export,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def load_and_verify(store, facts_path: Path, decisions_path: Path, set_cursor: bool = False) -> dict[str, Any]:
    facts, decisions = _load_pair(facts_path, decisions_path)
    return verify_batch(store, facts, decisions, set_cursor=set_cursor)
