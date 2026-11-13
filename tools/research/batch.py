"""Prepare and resume a user-selected research scope; static research by default."""

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
        """SELECT sc.observed_date AS value,sc.evidence_file_id FROM stock_concepts sc
           JOIN evidence_files e ON e.id=sc.evidence_file_id WHERE sc.stock_id=? AND e.parse_status='indexed'
           ORDER BY sc.observed_date DESC,e.modified_at DESC,e.id DESC LIMIT 1""",
        (stock_id,),
    ).fetchone()
    if not latest:
        return {"effective_date": None, "tags": [], "sources": [], "snapshot_status": "missing"}
    rows = connection.execute(
        """SELECT c.unified_name,c.source_name,e.path,sc.historical_status,sc.captured_date
           FROM stock_concepts sc JOIN concepts c ON c.id=sc.concept_id
           LEFT JOIN evidence_files e ON e.id=sc.evidence_file_id
           WHERE sc.stock_id=? AND sc.evidence_file_id=?
           ORDER BY c.unified_name,c.source_name""",
        (stock_id, latest["evidence_file_id"]),
    ).fetchall()
    tags = sorted({row["unified_name"] or row["source_name"] for row in rows})
    sources = sorted({row["path"] for row in rows if row["path"]})
    return {
        "effective_date": latest["value"],
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
           ORDER BY CASE d.source_type WHEN 'kaipanla_limit_pool' THEN 0 ELSE 1 END,d.id DESC LIMIT 1""",
        (stock_id, trade_date),
    ).fetchone()
    if not row:
        return None
    raw = json.loads(row["raw_json"])
    context = [dict(item) for item in connection.execute(
        """SELECT DISTINCT m.source_kind,m.topic,m.topic_tags,m.description,m.event_time,e.path AS source
           FROM market_source_facts m LEFT JOIN evidence_files e ON e.id=m.evidence_file_id
           WHERE m.stock_id=? AND m.trade_date=? ORDER BY m.source_kind,m.event_time""",
        (stock_id, trade_date),
    )]
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
        "description": raw.get("reason") or raw.get("description") or raw.get("theme_reason"),
        "context": context,
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
        """SELECT r.main_theme FROM launch_rounds l
           JOIN first_open_events f ON f.launch_round_id=l.id
           JOIN current_static_research r ON r.first_open_event_id=f.id
           WHERE l.stock_id=? AND l.focus_date<=?
           ORDER BY l.focus_date DESC LIMIT 1""",
        (stock_id, trade_date),
    ).fetchone()
    return row["main_theme"] if row else None


def _first_two(connection, stock_id: int, end: str, start: str | None = None) -> list[dict[str, Any]]:
    if start is None:
        row = connection.execute(
            """SELECT MAX(trade_date) AS day FROM daily_market
               WHERE stock_id=? AND source_type='kaipanla_limit_pool' AND board_height=1 AND trade_date<=?""",
            (stock_id, end),
        ).fetchone()
        start = row["day"]
    if not start:
        return []
    days = connection.execute(
        """SELECT DISTINCT trade_date FROM daily_market WHERE stock_id=?
           AND source_type='kaipanla_limit_pool' AND trade_date BETWEEN ? AND ?
           AND board_height IN (1,2) ORDER BY trade_date LIMIT 2""", (stock_id, start, end),
    )
    return [_daily_row(connection, stock_id, row["trade_date"]) for row in days]


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
        item["first_two"] = _first_two(connection, item["stock_id"], pool_date)
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


def _select_records(connection, limit: int | None, year: int | None, record_keys: list[str] | None,
                    from_date: str | None = None, to_date: str | None = None) -> list[Any]:
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
    conditions = ["r.research_status='unresearched'"]
    params: list[Any] = []
    if year is not None:
        conditions.append("l.focus_date LIKE ?")
        params.append(f"{year:04d}-%")
    if from_date:
        conditions.append("l.focus_date>=?")
        params.append(from_date)
    if to_date:
        conditions.append("l.focus_date<=?")
        params.append(to_date)
    query = base + " WHERE " + " AND ".join(conditions) + " ORDER BY l.focus_date,r.legacy_record_key LIMIT ?"
    params.append(limit if limit is not None else -1)
    return connection.execute(query, params).fetchall()


def _record_facts(store, connection, dates: list[str], batch_key: str, row: Any,
                  scope: str = "static", shared: dict | None = None) -> dict[str, Any]:
    shared = shared if shared is not None else {}
    def attributes(stock_id):
        key = ("attributes", stock_id)
        if key not in shared:
            shared[key] = _latest_attributes(connection, stock_id)
        return shared[key]
    stock_id = int(row["stock_id"])
    code = row["code"]
    end_date = row["event_date"] or row["focus_date"]
    first_two = _first_two(connection, stock_id, end_date)
    first_board_date = first_two[0]["date"] if first_two else (row["first_board_date"] or row["focus_date"])
    strict_days = []
    scope_dates = {first_board_date, row["focus_date"]}
    for date in dates:
        if first_board_date <= date <= end_date:
            candidate = _daily_row(connection, stock_id, date)
            if not candidate or not candidate.get("strict_one_word"):
                continue
            scope_dates.add(date)
            higher = []
            for member in _global_pool(connection, "strict_one_word", date, batch_key):
                if (member.get("board_height") or 0) <= (candidate.get("board_height") or 0):
                    continue
                member["attributes"] = attributes(member["stock_id"])
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
    ).fetchone() if scope == "both" else None
    high_key = ("high_pool", first_board_date)
    if high_key not in shared:
        shared[high_key] = _high_pool(connection, dates, first_board_date, batch_key)
    for date in scope_dates:
        if date and ("raw_scope", date) not in shared:
            shared[("raw_scope", date)] = _raw_scope(store.root, date)
    result = {
        "record_key": row["legacy_record_key"],
        "identity": {
            "stock_id": stock_id,
            "code": code,
            "name": _name(connection, stock_id),
            "first_board_date": first_board_date,
            "focus_date": row["focus_date"],
            "first_open_date": row["event_date"],
            "board_sequence": row["board_sequence_text"],
        },
        "current_status": {
            "static": row["research_status"],
            "static_confirmation": row["confirmation_status"],
            "dynamic": dynamic["research_status"] if dynamic else None,
        },
        "attributes": attributes(stock_id),
        "first_two": first_two,
        "high_pool": shared[high_key],
        "strict_one_word_days": strict_days,
        "scope_audit": [shared[("raw_scope", date)] for date in sorted(date for date in scope_dates if date)],
        "announcement_sources": _announcement_sources(store.root, dates, code, first_board_date, end_date),
        "announcement_missing_dates": [date for date in dates
            if (_previous_date(dates, first_board_date) or first_board_date) <= date <= end_date
            and not (store.root / "data/kaipanla/raw" / date / "historical_messages.json").exists()],
        "announcement_facts": [dict(item) for item in connection.execute(
            """SELECT DISTINCT m.trade_date,m.source_kind,m.topic,m.description,e.path AS source
               FROM market_source_facts m LEFT JOIN evidence_files e ON e.id=m.evidence_file_id
               WHERE m.stock_id=? AND m.trade_date BETWEEN ? AND ? ORDER BY m.trade_date,m.source_kind""",
            (stock_id, _previous_date(dates, first_board_date) or first_board_date, end_date),
        )],
        "potential_competitor_candidates": _competitor_candidates(
            connection, dates, stock_id, row["focus_date"], row["event_date"]
        ),
        "current_static_raw": json.loads(row["raw_json"]),
    }
    if scope == "both":
        transaction_path = store.root / "data/price_checks/tdx_transactions" / code / f"{row['event_date']}.json"
        market = _sina_market(store.root, code, row["event_date"])
        market["kaipanla"] = _daily_row(connection, stock_id, row["event_date"]) if row["event_date"] else None
        market["transaction_source"] = transaction_path.relative_to(store.root).as_posix() if transaction_path.exists() else None
        result["first_open_market"] = market
        result["current_dynamic_raw"] = json.loads(dynamic["raw_json"]) if dynamic else None
    return result


def _decision_template(fact: dict[str, Any], hydrate_current: bool, scope: str = "static") -> dict[str, Any]:
    raw = fact["current_static_raw"] if hydrate_current else {}
    dynamic = fact.get("current_dynamic_raw") if hydrate_current and fact.get("current_dynamic_raw") else {}
    result = {
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
    if scope == "static":
        result.pop("dynamic")
    return result


def prepare_batch(
    store,
    output_dir: Path,
    limit: int | None = None,
    year: int | None = None,
    record_keys: list[str] | None = None,
    hydrate_current: bool = False,
    scope: str = "static",
    from_date: str | None = None,
    to_date: str | None = None,
    fetch_missing: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if scope not in {"static", "both"}:
        raise ValueError("scope must be static or both")
    old_facts = _read_json(output_dir / "facts.json") if (output_dir / "facts.json").exists() else None
    if old_facts and not record_keys:
        selection = old_facts.get("selection", {})
        for key, value in (("limit", limit), ("year", year), ("from_date", from_date), ("to_date", to_date)):
            if value is not None and selection.get(key) != value:
                raise ValueError("selection changed; use another output directory")
        record_keys = [row["record_key"] for row in old_facts["records"]]
    if not record_keys and limit is None and not from_date and not to_date:
        raise ValueError("specify --limit, --record-key or a date range; there is no fixed batch size")
    if record_keys and len(record_keys) != len(set(record_keys)):
        raise ValueError("record keys must be unique")
    for value in (from_date, to_date):
        if value:
            datetime.strptime(value, "%Y-%m-%d")
    if from_date and to_date and from_date > to_date:
        raise ValueError("from-date exceeds to-date")
    connection = store.connect()
    store.apply_migrations(connection)
    batch_key = connection.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()["value"]
    dates = _trading_dates(connection)
    selected = _select_records(connection, limit, year, record_keys, from_date, to_date)
    if not selected:
        connection.close()
        raise RuntimeError("no research records matched the batch selector")
    shared = {}
    facts_records = [_record_facts(store, connection, dates, batch_key, row, scope, shared) for row in selected]
    connection.close()
    key_digest = hashlib.sha256("\n".join(fact["record_key"] for fact in facts_records).encode("utf-8")).hexdigest()[:8]
    batch_id = f"research-{facts_records[0]['identity']['focus_date']}-{facts_records[-1]['identity']['focus_date']}-{len(facts_records)}-{key_digest}"
    facts = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "scope": scope,
        "prepared_at": datetime.now(SHANGHAI).isoformat(timespec="seconds"),
        "selection": old_facts["selection"] if old_facts else {"limit": limit, "year": year, "from_date": from_date, "to_date": to_date, "explicit_record_keys": record_keys or []},
        "records": facts_records,
    }
    decisions = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "scope": scope,
        "records": [_decision_template(fact, hydrate_current, scope) for fact in facts_records],
    }
    if old_facts and (old_facts["batch_id"] != batch_id or old_facts.get("scope", "both") != scope):
        raise ValueError("this output directory belongs to another selection or scope; choose another directory")
    if (output_dir / "decisions.json").exists():
        old_decisions = _read_json(output_dir / "decisions.json")
        if old_decisions.get("batch_id") != batch_id or old_decisions.get("scope", "both") != scope:
            raise ValueError("existing decisions belong to another selection or scope")
        decisions = old_decisions
    fetch_result = None
    if fetch_missing:
        from .intake import fetch_attributes
        passing = {row["record_key"] for row in decisions["records"]
                   if row["static"].get("replenishment_result") == "非补涨"
                   and str(row["static"].get("suppression_result") or "").startswith("无")
                   and row["static"].get("announcement_pollution") is False}
        missing_codes = sorted({item["code"] for item in _missing_facts(facts_records)
                                if item["kind"] == "attributes" and
                                (not item.get("required_when") or item["record_key"] in passing)})
        fetch_result = fetch_attributes(store, missing_codes)
        if fetch_result["saved"]:
            connection = store.connect()
            shared = {}
            facts_records = [_record_facts(store, connection, dates, batch_key, row, scope, shared) for row in selected]
            connection.close()
            facts["records"] = facts_records
    facts["missing"] = _missing_facts(facts_records)
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "facts.json", facts)
    _write_json(output_dir / "decisions.json", decisions)
    brief = _brief(facts)
    _write_json(output_dir / "brief.json", brief)
    return {
        "batch_id": batch_id,
        "record_count": len(facts_records),
        "record_keys": [fact["record_key"] for fact in facts_records],
        "facts": str(output_dir / "facts.json"),
        "decisions": str(output_dir / "decisions.json"),
        "brief": str(output_dir / "brief.json"),
        "scope": scope,
        "missing": facts["missing"],
        "fetch": fetch_result,
        "resumed": old_facts is not None,
        "hydrate_current": hydrate_current,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _missing_facts(records: list[dict]) -> list[dict]:
    missing = []
    for fact in records:
        key = fact["record_key"]
        objects = [(fact["identity"], fact["attributes"], "candidate")]
        for day in fact["strict_one_word_days"]:
            objects.extend((item, item["attributes"], f"suppression:{day['date']}") for item in day["higher_members"])
        # Competitor attributes are required only after the static gates pass.
        for member in fact["potential_competitor_candidates"]["members"]:
            if member["attributes"]["snapshot_status"] == "missing":
                missing.append({"record_key": key, "kind": "attributes", "code": member["code"],
                                "purpose": "competitor", "required_when": "static_pass"})
        for identity, attrs, purpose in objects:
            if attrs["snapshot_status"] == "missing":
                missing.append({"record_key": key, "kind": "attributes", "code": identity["code"], "purpose": purpose})
        if len(fact["first_two"]) < 2:
            missing.append({"record_key": key, "kind": "first_two", "code": fact["identity"]["code"]})
        for item in fact["high_pool"]["members"]:
            if not item.get("confirmed_main_theme") and len(item["first_two"]) < 2:
                missing.append({"record_key": key, "kind": "high_first_two", "code": item["code"]})
        for item in fact["scope_audit"]:
            if item["status"] == "source_missing":
                missing.append({"record_key": key, "kind": "daily_pool", "date": item["date"]})
        if not fact["announcement_sources"] or fact.get("announcement_missing_dates"):
            missing.append({"record_key": key, "kind": "announcements", "code": fact["identity"]["code"]})
    return missing


def _brief(facts: dict) -> dict:
    """Share repeated evidence once, omit historic payloads from the AI reading view."""
    shared: dict[str, Any] = {}
    def ref(value):
        key = hashlib.sha256(_json(value).encode("utf-8")).hexdigest()[:12]
        shared[key] = value
        return {"evidence_ref": key}
    records = []
    for fact in facts["records"]:
        item = {key: value for key, value in fact.items()
                if key not in {"current_static_raw", "current_dynamic_raw", "scope_audit"}}
        item["attributes"] = ref(fact["attributes"])
        item["first_two"] = [ref(day) for day in fact["first_two"]]
        item["high_pool"] = ref(dict(fact["high_pool"], members=[
            dict(member, first_two=[ref(day) for day in member["first_two"]])
            for member in fact["high_pool"]["members"]]))
        item["strict_one_word_days"] = [dict(day, higher_members=[
            dict(member, attributes=ref(member["attributes"])) for member in day["higher_members"]
        ]) for day in fact["strict_one_word_days"]]
        item["potential_competitor_candidates"] = ref(dict(fact["potential_competitor_candidates"], members=[
            dict(member, attributes=ref(member["attributes"])) for member in fact["potential_competitor_candidates"]["members"]]))
        records.append(item)
    return {"batch_id": facts["batch_id"], "scope": facts["scope"], "records": records,
            "shared_evidence": shared, "missing": facts["missing"]}


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
    if facts.get("scope", "both") != decisions.get("scope", "both"):
        raise ValueError("facts and decisions scope mismatch")
    fact_keys = [row["record_key"] for row in facts.get("records", [])]
    decision_keys = [row["record_key"] for row in decisions.get("records", [])]
    if not fact_keys or fact_keys != decision_keys or len(set(fact_keys)) != len(fact_keys):
        raise ValueError("facts and decisions must contain the same ordered unique records")
    return facts, decisions


def _validate_decision(fact: dict[str, Any], decision: dict[str, Any], scope: str = "both") -> bool:
    static = decision.get("static") or {}
    required = ["main_theme", "main_theme_basis", "replenishment_result", "mapping_basis", "suppression_result", "suppression_basis", "announcement_basis"]
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
    if passed and scope == "both":
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
        passed = _validate_decision(fact, decision, facts.get("scope", "both"))
        static = decision["static"]
        missing = _missing_facts([fact])
        blocking = [item for item in missing if item["kind"] in {"attributes", "daily_pool"}
                    and (not item.get("required_when") or passed)]
        if blocking:
            raise ValueError(f"{fact['record_key']} missing source facts: {_json(blocking)}; fill them or set defer_reason")
        evidence = sorted(_source_values({key: value for key, value in fact.items() if not key.startswith("current_")}) | set(static.get("additional_evidence") or []))
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
        if facts.get("scope", "both") == "static":
            continue
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
    for request in requests:
        request["request_id"] = _request_id(facts["batch_id"], request["kind"], request["record_key"],
                                             {key: value for key, value in request.items() if key != "request_id"})
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
            passed = _validate_decision(fact, decision, facts.get("scope", "both"))
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
        launch = connection.execute(
            """SELECT l.first_board_date FROM first_open_events f
               JOIN launch_rounds l ON l.id=f.launch_round_id
               WHERE f.id=?""",
            (static["first_open_event_id"],),
        ).fetchone()
        if not launch or launch["first_board_date"] != fact["identity"]["first_board_date"]:
            findings.append(f"{fact['record_key']} actual first-board date mismatch")
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
        if facts.get("scope", "both") == "static":
            records.append({"record_key": fact["record_key"], "static_pass": passed})
            if passed and "首开潜在竞争对手事实清单" not in raw:
                findings.append(f"{fact['record_key']} passing record lacks competitor list")
            continue
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


def _sync_actual_first_board_dates(store, facts: dict[str, Any]) -> int:
    connection = store.connect()
    store.apply_migrations(connection)
    changed = 0
    with store.immediate(connection):
        for fact in facts["records"]:
            actual = fact["identity"]["first_board_date"]
            row = connection.execute(
                """SELECT l.id,l.first_board_date FROM current_static_research r
                   JOIN first_open_events f ON f.id=r.first_open_event_id
                   JOIN launch_rounds l ON l.id=f.launch_round_id
                   WHERE r.legacy_record_key=?""",
                (fact["record_key"],),
            ).fetchone()
            if row and row["first_board_date"] != actual:
                connection.execute("UPDATE launch_rounds SET first_board_date=? WHERE id=?", (actual, row["id"]))
                changed += 1
    connection.close()
    return changed


def commit_batch(
    store,
    facts_path: Path,
    decisions_path: Path,
    publish: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    facts, decisions = _load_pair(facts_path, decisions_path)
    store.sync_rules()
    deferred = [{"record_key": row["record_key"], "reason": row["defer_reason"]}
                for row in decisions["records"] if row.get("defer_reason")]
    deferred_keys = {row["record_key"] for row in deferred}
    facts = dict(facts, records=[row for row in facts["records"] if row["record_key"] not in deferred_keys])
    decisions = dict(decisions, records=[row for row in decisions["records"] if row["record_key"] not in deferred_keys])
    if not facts["records"]:
        return {"batch_id": facts["batch_id"], "write_count": 0, "deferred": deferred}
    synchronized_first_board_dates = _sync_actual_first_board_dates(store, facts)
    requests = _requests_for_batch(facts, decisions)
    write_started = time.perf_counter()
    results = [store.write_research(request) for request in requests]
    write_seconds = round(time.perf_counter() - write_started, 3)
    verification = verify_batch(store, facts, decisions, set_cursor=True)
    if not verification["passed"]:
        raise RuntimeError(f"batch verification failed: {verification['findings']}")
    export_started = time.perf_counter()
    export = store.export_all(publish_root=True, refresh_statistics=facts.get("scope", "both") == "both") if publish and (synchronized_first_board_dates or any(not row.get("deduplicated") for row in results)) else None
    return {
        "batch_id": facts["batch_id"],
        "record_count": len(facts["records"]),
        "write_count": len(results),
        "deferred": deferred,
        "scope": facts.get("scope", "both"),
        "synchronized_first_board_dates": synchronized_first_board_dates,
        "deduplicated": sum(bool(row.get("deduplicated")) for row in results),
        "timing_seconds": {"write": write_seconds, "verify": verification["elapsed_seconds"],
                           "export": round(time.perf_counter() - export_started, 3)},
        "verification": verification,
        "export": export,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def load_and_verify(store, facts_path: Path, decisions_path: Path, set_cursor: bool = False) -> dict[str, Any]:
    facts, decisions = _load_pair(facts_path, decisions_path)
    keys = {row["record_key"] for row in decisions["records"] if row.get("defer_reason")}
    facts = dict(facts, records=[row for row in facts["records"] if row["record_key"] not in keys])
    decisions = dict(decisions, records=[row for row in decisions["records"] if row["record_key"] not in keys])
    if not facts["records"]:
        return {"passed": True, "record_count": 0, "deferred_count": len(keys), "cursor_updated": False}
    return verify_batch(store, facts, decisions, set_cursor=set_cursor)
