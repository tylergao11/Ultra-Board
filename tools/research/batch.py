"""Prepare and resume a user-selected research scope; static research by default."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Any
from .system import SHANGHAI
from .scratch import MARKER


BATCH_SCHEMA_VERSION = 1


def _batch_directory(store, directory):
    directory = directory.resolve()
    research = (store.root / "data/research").resolve()
    if directory.is_relative_to(research):
        return directory
    base = (store.root / "data/store/tmp").resolve()
    relative = directory.relative_to(base)
    if not relative.parts:
        raise ValueError("请选择已登记的临时批次目录")
    workspace = base / relative.parts[0]
    marker = json.loads((workspace / MARKER).read_text(encoding="utf-8"))
    required = {(directory/name).relative_to(workspace).as_posix() for name in ("batch.json","facts.json","brief.json","decisions.json")}
    if marker.get("owner")!="Ultra-Board" or marker.get("id")!=workspace.name or not required.issubset(marker["files"]):
        raise ValueError("批次临时材料须先登记归属及文件清单")
    return directory


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


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
           WHERE d.stock_id=? AND d.trade_date=? AND d.source_type='kaipanla_limit_pool'
           ORDER BY d.id DESC LIMIT 1""",
        (stock_id, trade_date),
    ).fetchone()
    context = [dict(item) for item in connection.execute(
        """SELECT DISTINCT m.source_kind,m.topic,m.topic_tags,m.description,m.event_time,e.path AS source
           FROM market_source_facts m LEFT JOIN evidence_files e ON e.id=m.evidence_file_id
           WHERE m.stock_id=? AND m.trade_date=? ORDER BY m.source_kind,m.event_time""",
        (stock_id, trade_date),
    )]
    if not row:
        fallback = connection.execute(
            """SELECT m.*,e.path AS evidence_path FROM market_source_facts m
               LEFT JOIN evidence_files e ON e.id=m.evidence_file_id
               WHERE m.stock_id=? AND m.trade_date=?
                 AND m.source_kind='kaipanla_historical_messages' AND m.board_height IS NOT NULL
               ORDER BY m.id LIMIT 1""",
            (stock_id, trade_date),
        ).fetchone()
        if not fallback:
            return None
        event_time = fallback["event_time"]
        return {
            "date": trade_date,
            "source_type": "kaipanla_historical_messages",
            "board_height": fallback["board_height"],
            "strict_one_word": bool(event_time and event_time <= "09:25:59"),
            "first_limit_time": event_time,
            "close": None,
            "limit_up": None,
            "theme": fallback["topic"],
            "theme_tags": fallback["topic_tags"],
            "description": fallback["description"],
            "context": context,
            "source": fallback["evidence_path"],
        }
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
    start = _actual_first_board_date(connection, stock_id, trade_date)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name='research_theme_inputs'").fetchone():
        saved = connection.execute("SELECT main_theme FROM research_theme_inputs WHERE stock_id=? AND first_board_date=?",
                                   (stock_id,start)).fetchone()
        if saved:
            return saved[0]
    row = connection.execute(
        """SELECT r.main_theme FROM launch_rounds l
           JOIN first_open_events f ON f.launch_round_id=l.id
           JOIN current_static_research r ON r.first_open_event_id=f.id
           WHERE l.stock_id=? AND l.first_board_date=?
           ORDER BY l.focus_date DESC LIMIT 1""",
        (stock_id, start),
    ).fetchone()
    return row["main_theme"] if row else None


def _actual_board_sequence(connection, stock_id: int, start: str, end: str) -> list[tuple[str, int]]:
    rows = connection.execute(
        """SELECT trade_date,board_height,priority FROM (
             SELECT trade_date,board_height,0 AS priority FROM daily_market
              WHERE stock_id=? AND source_type='kaipanla_limit_pool' AND trade_date BETWEEN ? AND ?
                AND board_height IS NOT NULL
             UNION ALL
             SELECT trade_date,board_height,1 AS priority FROM market_source_facts
              WHERE stock_id=? AND source_kind='kaipanla_historical_messages' AND trade_date BETWEEN ? AND ?
                AND board_height IS NOT NULL
           ) ORDER BY trade_date,priority""",
        (stock_id, start, end, stock_id, start, end),
    ).fetchall()
    result = []
    seen = set()
    for row in rows:
        if row["trade_date"] in seen:
            continue
        seen.add(row["trade_date"])
        result.append((row["trade_date"], row["board_height"]))
    return result


def _actual_first_board_date(connection, stock_id: int, end: str) -> str | None:
    row = connection.execute(
        """SELECT MAX(trade_date) FROM (
             SELECT trade_date FROM daily_market WHERE stock_id=? AND source_type='kaipanla_limit_pool'
              AND board_height=1 AND trade_date<=?
             UNION ALL
             SELECT trade_date FROM market_source_facts WHERE stock_id=?
              AND source_kind='kaipanla_historical_messages' AND board_height=1 AND trade_date<=?
           )""",
        (stock_id, end, stock_id, end),
    ).fetchone()
    return row[0]


def _actual_next_first_board_date(connection, stock_id: int, start: str) -> str | None:
    row = connection.execute(
        """SELECT MIN(trade_date) FROM (
             SELECT trade_date FROM daily_market WHERE stock_id=? AND source_type='kaipanla_limit_pool'
              AND board_height=1 AND trade_date>?
             UNION ALL
             SELECT trade_date FROM market_source_facts WHERE stock_id=?
              AND source_kind='kaipanla_historical_messages' AND board_height=1 AND trade_date>?
           )""",
        (stock_id, start, stock_id, start),
    ).fetchone()
    return row[0]


def _first_two(connection, stock_id: int, end: str, start: str | None = None) -> list[dict[str, Any]]:
    if start is None:
        start = _actual_first_board_date(connection, stock_id, end)
    if not start:
        return []
    days = [day for day,height in _actual_board_sequence(connection, stock_id, start, end) if height in (1,2)][:2]
    return [_daily_row(connection, stock_id, day) for day in days]


def _global_pool(connection, pool_type: str, pool_date: str, batch_key: str, minimum: int = 4) -> list[dict[str, Any]]:
    condition = "d.strict_one_word=1" if pool_type == "strict_one_word" else "d.board_height>=?"
    params = [pool_date] if pool_type == "strict_one_word" else [pool_date,minimum]
    rows = connection.execute(
        """SELECT d.stock_id,d.board_height,e.path AS evidence_path FROM daily_market d
           LEFT JOIN evidence_files e ON e.id=d.evidence_file_id
           WHERE d.trade_date=? AND d.source_type='kaipanla_limit_pool' AND """ + condition +
        " ORDER BY d.board_height DESC,d.stock_id", params,
    ).fetchall()
    result = []
    for row in rows:
        item = _stock_identity(connection, row["stock_id"])
        item.update({
            "board_height": row["board_height"],
            "status": f"{row['board_height']}板晋级",
            "query_direction": "全部更高一字" if pool_type == "strict_one_word" else "高标主炒向候选完整属性",
            "source": row["evidence_path"],
        })
        result.append(item)
    return result


def _high_pool(connection, dates: list[str], pool_date: str, batch_key: str, parameters=None) -> dict[str, Any]:
    parameters = parameters or {}
    advanced = _global_pool(connection, "high_standard", pool_date, batch_key, parameters.get("前序最低连续板数",4))
    previous = _previous_date(dates, pool_date)
    previous_high = _global_pool(connection, "high_standard", previous, batch_key, parameters.get("当日断板前最低连续板数",4)) if previous else []
    current_ids = {r[0] for r in connection.execute("SELECT stock_id FROM daily_market WHERE trade_date=? AND source_type='kaipanla_limit_pool'", (pool_date,))}
    broken = []
    for item in previous_high:
        if item["stock_id"] in current_ids:
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


def _trade_market(connection, stock_id: int, event_date: str | None, days: int = 20) -> dict[str, Any]:
    """Reusable observed prices and events; never store a strategy decision here."""
    if not event_date:
        return {"event_date": None, "previous": None, "event": None, "following": [], "missing": ["首开日期"]}
    rows = connection.execute(
        """SELECT d.*,e.path AS source FROM daily_market d
        LEFT JOIN evidence_files e ON e.id=d.evidence_file_id
        WHERE d.stock_id=? AND d.price_mode='unadjusted'
          AND d.trade_date>=COALESCE((SELECT MAX(trade_date) FROM daily_market
              WHERE stock_id=? AND trade_date<? AND price_mode='unadjusted'
              AND open_milli IS NOT NULL AND high_milli IS NOT NULL AND low_milli IS NOT NULL AND close_milli IS NOT NULL),?)
        ORDER BY d.trade_date,CASE d.source_type WHEN 'ths_kline' THEN 0
            WHEN 'sina_history' THEN 1 WHEN 'price_check_json' THEN 2 ELSE 3 END,d.id DESC""",
        (stock_id, stock_id, event_date, event_date),
    ).fetchall()
    grouped = {}
    fields = ['open','high','low','close','previous_close','limit_up','limit_down']
    for row in rows:
        day = row['trade_date']
        if day not in grouped and len(grouped) >= days + 2:
            break
        item = grouped.setdefault(day, {"day": day, "sources": [], "field_sources": {}, "conflicts": []})
        if row['source'] not in item['sources']:
            item['sources'].append(row['source'])
        for field in fields:
            value = row[field + '_milli']
            if value is None:
                continue
            value = value / 1000
            if field not in item:
                item[field] = value
                item['field_sources'][field] = row['source']
            elif item[field] != value:
                item['conflicts'].append({"field": field, "value": value, "source": row['source']})
    for day,item in grouped.items():
        item['events'] = [dict(r) for r in connection.execute(
            """SELECT i.event_type,i.event_time,i.time_precision,i.value_json,e.path AS source
            FROM intraday_events i LEFT JOIN evidence_files e ON e.id=i.evidence_file_id
            WHERE i.stock_id=? AND i.trade_date=? ORDER BY i.event_time""", (stock_id,day))]
        for event in item['events']:
            value=json.loads(event.pop('value_json'))
            event['value']={'points':len(value.get('trend',[]))} if event['event_type']=='minute_trend' else value
        item['missing'] = [field for field in ['open','high','low','close'] if field not in item]
    previous = [v for k,v in grouped.items() if k < event_date]
    event = grouped.get(event_date)
    following = [v for k,v in grouped.items() if k > event_date][:days]
    missing = [f"event:{field}" for field in event['missing']] if event else ['首开日日K']
    if not previous:
        missing.append('前一交易日日K')
    missing.extend(f"following:{item['day']}:{field}" for item in following for field in item['missing'])
    return {"event_date": event_date, "previous": previous[-1] if previous else None,
            "event": event, "following": following, "missing": missing,
            "following_requested": days, "following_available": len(following),
            "event_coverage": {"available_types": sorted({e['event_type'] for item in grouped.values() for e in item['events']}),
                               "unavailable_types": sorted({'first_break','first_reseal'}-{e['event_type'] for item in grouped.values() for e in item['events']})}}


def trade_facts(store, record_keys, days=20):
    if days < 1:
        raise ValueError("days must be positive")
    from .market import ensure_research_prices
    from .events import ensure_trade_events
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as executor:
        daily_job=executor.submit(ensure_research_prices,store,record_keys,following_days=days)
        event_job=executor.submit(ensure_trade_events,store,record_keys)
        ensured=daily_job.result();events=event_job.result()
    if not ensured['complete']:raise RuntimeError(json.dumps(ensured,ensure_ascii=False))
    connection = store.connect()
    try:
        records = []
        for key in record_keys:
            row = connection.execute("""SELECT l.stock_id,f.event_date,r.raw_json FROM legacy_key_map m
                JOIN launch_rounds l ON l.id=m.launch_round_id
                JOIN current_static_research r ON r.legacy_record_key=m.legacy_record_key
                JOIN first_open_events f ON f.id=m.first_open_event_id WHERE m.legacy_record_key=?""", (key,)).fetchone()
            if not row:
                raise KeyError(key)
            records.append({"record_key": key, **_trade_market(connection,row['stock_id'],row['event_date'],days),
                            "competitors":_peer_market(connection,json.loads(row['raw_json']),row['event_date'])})
        return {"records": records, "market": ensured, "events": events}
    finally:
        connection.close()


def _peer_market(connection, raw, day):
    from .market import _codes
    peers=[]
    for code in sorted(_codes(raw.get('首开潜在竞争对手事实清单',[]))):
        row=connection.execute('SELECT id FROM stocks WHERE code=?',(code,)).fetchone()
        if row:peers.append({'code':code,**_trade_market(connection,row[0],day,0)})
    return peers


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
                    from_date: str | None = None, to_date: str | None = None, scope='static') -> list[Any]:
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
    conditions = ["r.research_status IN ('unresearched','needs_input')"]
    if scope=='dynamic':
        conditions=["r.main_theme IS NOT NULL", "r.research_status<>'needs_input'",
                    "NOT EXISTS (SELECT 1 FROM current_dynamic_research d WHERE d.legacy_record_key=r.legacy_record_key)"]
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
    if scope == 'dynamic':
        raw=json.loads(row['raw_json'])
        dynamic=connection.execute('SELECT raw_json FROM current_dynamic_research WHERE legacy_record_key=?',(row['legacy_record_key'],)).fetchone()
        return {'record_key':row['legacy_record_key'],'scope':'dynamic',
                'identity':{'code':row['code'],'stock_id':row['stock_id'],'name':_name(connection,row['stock_id']),
                            'focus_date':row['focus_date'],'first_board_date':row['first_board_date'],'first_open_date':row['event_date']},
                'current_static_raw':raw,'current_dynamic_raw':json.loads(dynamic[0]) if dynamic else None,
                'potential_competitor_candidates':raw.get('首开潜在竞争对手候选全集',{}),
                'competitor_market':_peer_market(connection,raw,row['event_date']),
                'first_open_market':_trade_market(connection,row['stock_id'],row['event_date'])}
    shared = shared if shared is not None else {}
    def attributes(stock_id):
        key = ("attributes", stock_id)
        if key not in shared:
            shared[key] = _latest_attributes(connection, stock_id)
        return shared[key]
    stock_id = int(row["stock_id"])
    code = row["code"]
    end_date = row["event_date"] or row["focus_date"]
    first_two = _first_two(connection, stock_id, row["focus_date"])
    if first_two:
        first_two = _first_two(connection, stock_id, end_date, first_two[0]["date"])
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
    high_key = ("high_pool", first_board_date)
    if high_key not in shared:
        if "parameters" not in shared:
            shared["parameters"] = _read_json(store.root / "data/store/rules/static_rules.json")["rules"]["补涨时间参数"]
        shared[high_key] = _high_pool(connection, dates, first_board_date, batch_key, shared["parameters"])
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
    return result


def _decision_template(fact: dict[str, Any], scope: str = "static") -> dict[str, Any]:
    result = {"record_key":fact["record_key"],"static":{
        "main_theme":None,"main_theme_basis":None,
        "announcement_pollution":None,"announcement_basis":None,"additional_evidence":[]}}
    if scope == "dynamic":
        result.pop("static")
        result["dynamic"] = {"auction":None,"pk_checks":None,"pk_result":None,
                             "buy_point":None,"outcome":None,"additional_evidence":[]}
    return result


def prepare_batch(
    store,
    output_dir: Path,
    limit: int | None = None,
    year: int | None = None,
    record_keys: list[str] | None = None,
    scope: str = "static",
    from_date: str | None = None,
    to_date: str | None = None,
    fetch_missing: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    _batch_directory(store,output_dir)
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if scope not in {"static", "dynamic"}:
        raise ValueError("scope must be static or dynamic")
    old_decisions = _read_json(output_dir / "decisions.json") if (output_dir / "decisions.json").exists() else None
    if old_decisions and not record_keys:
        record_keys = [row["record_key"] for row in old_decisions["records"]]
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
    selected = _select_records(connection, limit, year, record_keys, from_date, to_date, scope)
    if not selected:
        connection.close()
        raise RuntimeError("no research records matched the batch selector")
    market_result = None
    if scope == "dynamic" and fetch_missing:
        market_result = trade_facts(store, [r['legacy_record_key'] for r in selected])
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
        "selection": {"limit": limit, "year": year, "from_date": from_date, "to_date": to_date, "explicit_record_keys": record_keys or []},
        "records": facts_records,
    }
    decisions = {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": batch_id,
        "scope": scope,
        "records": [_decision_template(fact, scope) for fact in facts_records],
    }
    if old_decisions:
        if old_decisions.get("batch_id") != batch_id or old_decisions.get("scope", "dynamic") != scope:
            raise ValueError("existing decisions belong to another selection or scope")
        decisions = old_decisions
    fetch_result = None
    if fetch_missing and scope == "static":
        from .intake import fetch_attributes
        passing = {row["record_key"] for row in decisions["records"]
                   if row["static"].get("replenishment_result") == "非补涨"
                   and str(row["static"].get("suppression_result") or "").startswith("无")}
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
    from .derive import judgement_slots
    if scope == "static":
        decisions["high_themes"] = judgement_slots(store, facts_records, decisions.get("high_themes", []))
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "facts.json", facts)
    _write_json(output_dir / "decisions.json", decisions)
    brief = _brief(facts)
    _write_json(output_dir / "brief.json", brief)
    if not old_decisions or not (output_dir / "batch.json").exists():
        _write_json(output_dir / "batch.json", {"scope":scope,"record_keys":[f["record_key"] for f in facts_records]})
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
        "market": market_result,
        "resumed": old_decisions is not None,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _missing_facts(records: list[dict]) -> list[dict]:
    missing = []
    for fact in records:
        key = fact["record_key"]
        if fact.get('scope')=='dynamic':
            missing.extend({'record_key':key,'kind':'market','field':field} for field in fact['first_open_market']['missing'])
            continue
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
    if facts['scope']=='dynamic':
        return {'batch_id':facts['batch_id'],'scope':'dynamic','missing':facts['missing'],
                'records':[{'record_key':f['record_key'],'identity':f['identity'],
                            'static_readonly':_current_static_decision(f['current_static_raw']),
                            'market':f['first_open_market'],'competitor_market':f['competitor_market']} for f in facts['records']]}
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


def _load_pending(store, decisions_path):
    decisions = _read_json(decisions_path)
    if decisions.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise ValueError("unsupported batch schema version")
    keys = [row["record_key"] for row in decisions["records"]]
    manifest = _read_json(decisions_path.parent / "batch.json")
    if not keys or len(set(keys)) != len(keys) or not set(keys).issubset(manifest["record_keys"]):
        raise ValueError("待办记录须为当前批次中的唯一记录键")
    connection = store.connect()
    try:
        dates = _trading_dates(connection)
        batch_key = connection.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()[0]
        shared = {}
        records = [_record_facts(store,connection,dates,batch_key,row,decisions["scope"],shared)
                   for row in _select_records(connection,None,None,keys)]
    finally:
        connection.close()
    facts = {"schema_version":BATCH_SCHEMA_VERSION,"scope":decisions["scope"],"batch_id":decisions["batch_id"],
             "records":records,"missing":_missing_facts(records)}
    return facts, decisions


def _validate_decision(fact: dict[str, Any], decision: dict[str, Any], scope: str = "dynamic") -> bool:
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
    )
    if passed and not isinstance(static.get("competitors"), list):
        raise ValueError(f"{fact['record_key']} passing record requires competitors array")
    if passed and scope == "dynamic":
        dynamic = decision.get("dynamic") or {}
        missing_dynamic = [key for key in ["auction", "pk_checks", "pk_result", "buy_point", "outcome"] if dynamic.get(key) is None]
        if missing_dynamic:
            raise ValueError(f"{fact['record_key']} dynamic decision incomplete: {missing_dynamic}")
    return passed


def _request_id(batch_id: str, kind: str, key: str, updates: dict[str, Any]) -> str:
    digest = hashlib.sha256(_json(updates).encode("utf-8")).hexdigest()[:12]
    return f"{batch_id}-{kind}-{key.replace('|', '-')}-{digest}"


def _dynamic_updates(passed: bool, static: dict[str, Any], dynamic: dict[str, Any], market: dict[str, Any]) -> dict[str, Any]:
    if passed:
        updates = {
            "买入筛选": {"非补涨": True, "无一字压制": True, "公告污染": static["announcement_pollution"], "公告处理": "独立记录", "结果": "通过"},
            "竞价筛选": dynamic["auction"],
            "同题材PK核验明细": dynamic["pk_checks"],
            "同题材PK结果": dynamic["pk_result"],
            "首开买点": dynamic["buy_point"],
            "买入后结果": dynamic["outcome"],
        }
        updates["首开行情"] = market
        return updates
    reasons = []
    if static["replenishment_result"] != "非补涨":
        reasons.append("补涨")
    if not str(static["suppression_result"]).startswith("无"):
        reasons.append("有一字压制")
    reason = "、".join(reasons)
    return {
        "买入筛选": {
            "非补涨": static["replenishment_result"] == "非补涨",
            "无一字压制": str(static["suppression_result"]).startswith("无"),
            "公告污染": static["announcement_pollution"],
            "公告处理": "独立记录",
            "结果": "淘汰",
            "依据": reason,
        },
        "竞价筛选": {"结果": "未进入", "依据": "补涨或一字压制筛选已淘汰"},
        "同题材PK核验明细": [],
        "同题材PK结果": "未进入：补涨或一字压制筛选已淘汰",
        "首开买点": {"结果": "未进入", "买点类型": None, "买点时间": None, "事实": "补涨或一字压制筛选已淘汰", "来源": []},
        "买入后结果": {"是否买入": False, "统计处理": "不进入买入样本"},
    }


def static_request(fact, static):
    passed = _validate_decision(fact,{"static":static},"static")
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
        "静态筛选结论": "通过" if passed else "不通过",
        "静态筛选口径": "非补涨 + 无一字压制；公告污染独立记录",
    }
    if static["announcement_pollution"]:
        updates["公告真实属性"] = static["main_theme"]
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
    remove_fields = []
    if not passed:
        remove_fields.extend(["首开潜在竞争对手事实清单", "首开潜在竞争对手候选全集"])
    if not static["announcement_pollution"]:
        remove_fields.append("公告真实属性")
    request = {
        "request_id": "derived-static",
        "record_key": fact["record_key"], "kind": "static", "research_status": "formal_source_record",
        "confirmation_status": "pending_user_confirmation", "evidence": evidence, "updates": updates,
        "remove_fields": remove_fields, "checks": checks,
    }
    return request


def dynamic_request(fact, decision, batch_id):
    static = decision["static"]
    passed = _validate_decision(fact,decision,"dynamic")
    evidence = sorted(_source_values(fact))
    if passed:
        dynamic = decision["dynamic"]
        dynamic_updates = _dynamic_updates(True, static, dynamic, fact["first_open_market"])
        dynamic_checks = [
            {"check_type":"买入筛选","outcome":"通过","basis":"非补涨、无一字压制；公告污染独立记录。","sources":[]},
            {"check_type":"竞价筛选","outcome":dynamic["auction"].get("结果"),"basis":dynamic["auction"].get("依据"),"sources":sorted(_source_values(fact["first_open_market"]))},
            {"check_type":"theme_pk","outcome":dynamic["pk_result"],"basis":"按静态竞争清单执行。","sources":sorted(_source_values(fact["potential_competitor_candidates"])),"raw":dynamic["pk_checks"]},
            {"check_type":"买点","outcome":dynamic["buy_point"].get("结果"),"basis":dynamic["buy_point"].get("事实"),"sources":dynamic["buy_point"].get("来源",[])},
        ]
    else:
        dynamic_updates = _dynamic_updates(False, static, {}, fact["first_open_market"])
        reason = dynamic_updates["买入筛选"]["依据"]
        dynamic_checks = [{"check_type":"买入筛选","outcome":"淘汰","basis":reason,"sources":[]}]
    dynamic_evidence = sorted(set(evidence) | set((decision.get("dynamic") or {}).get("additional_evidence") or []))
    request = {
        "request_id": _request_id(batch_id, "dynamic", fact["record_key"], dynamic_updates),
        "record_key": fact["record_key"], "kind": "dynamic", "research_status": "source_record",
        "confirmation_status": "pending_user_confirmation", "evidence": dynamic_evidence,
        "updates": dynamic_updates, "checks": dynamic_checks,
    }
    request["request_id"] = _request_id(batch_id,"dynamic",fact["record_key"],request)
    return request


def verify_dynamic(store, facts, decisions, connection=None):
    started = time.perf_counter()
    owned = connection is None
    connection = connection or store.connect()
    findings = []
    try:
        for fact,decision in zip(facts["records"],decisions["records"]):
            try:
                passed = _validate_decision(fact,decision,"dynamic")
                expected = _dynamic_updates(passed,decision["static"],decision.get("dynamic") or {},fact["first_open_market"])
            except ValueError as exc:
                findings.append(str(exc))
                continue
            row = connection.execute("""SELECT d.* FROM current_dynamic_research d
                JOIN research_plans p ON p.id=d.plan_id WHERE d.legacy_record_key=? AND p.plan_code='formal'""",
                (fact["record_key"],)).fetchone()
            if not row:
                findings.append(fact["record_key"]+" 缺少交易记录")
                continue
            raw = json.loads(row["raw_json"])
            for name,value in expected.items():
                if raw.get(name) != value:
                    findings.append(fact["record_key"]+" 交易字段不一致："+name)
            if (raw.get("买入后结果") or {}).get("是否买入") is True and (row["buy_price_milli"] is None or row["sell_time"] is None):
                findings.append(fact["record_key"]+" 买入结果缺少价格或卖出日期")
    finally:
        if owned:
            connection.close()
    return {"passed":not findings,"record_count":len(facts["records"]),"findings":findings,
            "elapsed_seconds":round(time.perf_counter()-started,4)}




def clear_submitted_inputs(store, directory, facts, decisions, completed):
    directory = _batch_directory(store,directory)
    if not (directory / "batch.json").exists():
        _write_json(directory / "batch.json", {"scope":facts["scope"],"record_keys":[f["record_key"] for f in facts["records"]]})
    pending = [r for r in decisions["records"] if r["record_key"] not in completed]
    if not pending:
        for name in ("decisions.json","facts.json","brief.json"):
            (directory / name).unlink(missing_ok=True)
        _forget_submission(store,directory)
        return
    connection = store.connect()
    current = {}
    try:
        for item in pending:
            raw = json.loads(connection.execute("SELECT raw_json FROM current_static_research WHERE legacy_record_key=?",(item["record_key"],)).fetchone()[0])
            current[item["record_key"]] = raw
            if facts["scope"] == "static" and not item.get("defer_reason"):
                for key,field in {"main_theme":"唯一主炒作属性","main_theme_basis":"唯一主炒依据",
                                  "announcement_pollution":"公告污染","announcement_basis":"公告污染依据"}.items():
                    if item["static"].get(key) == raw.get(field):
                        item["static"][key] = None
    finally:
        connection.close()
    if facts["scope"] == "dynamic":
        for item in pending:item.pop("static",None)
    pending_keys = {r["record_key"] for r in pending}
    facts = dict(facts,records=[f for f in facts["records"] if f["record_key"] in pending_keys])
    for fact in facts["records"]:
        fact["current_static_raw"] = current[fact["record_key"]]
    digest = hashlib.sha256("\n".join(f["record_key"] for f in facts["records"]).encode()).hexdigest()[:8]
    identity = f"research-{facts['records'][0]['identity']['focus_date']}-{facts['records'][-1]['identity']['focus_date']}-{len(pending)}-{digest}"
    facts["batch_id"] = identity
    decisions = dict(decisions,batch_id=identity,records=pending,
                     high_themes=[h for h in decisions.get("high_themes",[]) if not h.get("main_theme")])
    _write_json(directory / "decisions.json",decisions)
    _write_json(directory / "facts.json",facts)
    _write_json(directory / "brief.json",_brief(facts))
    _forget_submission(store,directory)


def submission_key(store, path, kind="batch"):
    path = path.resolve()
    identity = path.relative_to(store.root).as_posix() if path.is_relative_to(store.root) else str(path)
    return "submitted_"+kind+":"+hashlib.sha256(identity.encode()).hexdigest()


def _forget_submission(store,directory):
    connection = store.connect()
    try:
        connection.execute("DELETE FROM store_meta WHERE key=?",(submission_key(store,directory),))
        connection.commit()
    finally:
        connection.close()


def commit_batch(
    store,
    facts_path: Path,
    decisions_path: Path,
    publish: bool = True,
) -> dict[str, Any]:
    started = time.perf_counter()
    _batch_directory(store,facts_path.parent)
    receipt = None
    if decisions_path.exists():
        digest = hashlib.sha256(decisions_path.read_bytes()).hexdigest()
        receipt = {"key":submission_key(store,decisions_path.parent),"sha256":digest}
        connection = store.connect()
        saved = connection.execute("SELECT value FROM store_meta WHERE key=?",(receipt["key"],)).fetchone()
        connection.close()
        saved = json.loads(saved[0]) if saved else None
        if saved and saved["sha256"]==digest:
            facts, decisions = _load_pending(store,decisions_path)
            if saved["phase"]=="complete":
                clear_submitted_inputs(store,facts_path.parent,facts,decisions,set(saved["record_keys"]))
            else:
                for item in decisions["records"]:
                    if item["record_key"] in saved["record_keys"]:
                        item["static"] = _decision_template({"record_key":item["record_key"]})["static"]
                decisions["high_themes"] = []
                _write_json(decisions_path,decisions)
                _forget_submission(store,facts_path.parent)
            if decisions_path.exists():
                receipt["sha256"] = hashlib.sha256(decisions_path.read_bytes()).hexdigest()
    if not decisions_path.exists():
        from .derive import recompute
        manifest = _read_json(facts_path.parent / "batch.json")
        result = recompute(store,manifest["record_keys"],publish=False) if manifest["scope"]=="static" else {"record_count":len(manifest["record_keys"])}
        if publish:
            result["export"] = store.publish_pending()
        clear_submitted_inputs(store,facts_path.parent,{"scope":manifest["scope"],"records":[]},{"records":[]},set())
        result["already_submitted"] = True
        return result
    facts, decisions = _load_pending(store, decisions_path)
    batch_facts, batch_decisions = facts, decisions
    from .derive import commit_judgements
    if facts.get("scope") == "static":
        result = commit_judgements(store, facts, decisions, publish=publish,receipt=receipt)
        clear_submitted_inputs(store,facts_path.parent,facts,decisions,{r["record_key"] for r in result.get("records",[])})
        return result
    # Trade submissions read the saved static result; they never derive or write it.
    static_result = None
    connection = store.connect()
    shared = {}
    dates = _trading_dates(connection)
    batch_key = connection.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()[0]
    fresh = []
    for decision in decisions["records"]:
        row = _select_records(connection,None,None,[decision["record_key"]])[0]
        fact = _record_facts(store,connection,dates,batch_key,row,"dynamic",shared)
        raw = fact["current_static_raw"]
        decision["static"] = _current_static_decision(raw)
        fresh.append(fact)
    connection.close()
    facts = dict(facts,records=fresh)
    store.sync_rules()
    deferred = [{"record_key": row["record_key"], "reason": row["defer_reason"]}
                for row in decisions["records"] if row.get("defer_reason")]
    deferred_keys = {row["record_key"] for row in deferred}
    facts = dict(facts, records=[row for row in facts["records"] if row["record_key"] not in deferred_keys])
    decisions = dict(decisions, records=[row for row in decisions["records"] if row["record_key"] not in deferred_keys])
    if not facts["records"]:
        export = store.publish_pending() if publish else None
        return {"batch_id": facts["batch_id"], "write_count": 0, "deferred": deferred,"static":static_result,"export":export}
    requests = [dynamic_request(f,d,facts["batch_id"]) for f,d in zip(facts["records"],decisions["records"])]
    write_started = time.perf_counter()
    connection = store.connect()
    try:
        with store.immediate(connection):
            results = [store.write_research(request,connection) for request in requests]
            verification = verify_dynamic(store,facts,decisions,connection)
            if not verification["passed"]:
                raise RuntimeError(f"batch verification failed: {verification['findings']}")
            if any(not row.get("deduplicated") for row in results):
                connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('statistics_export_pending','1')")
            receipt = {"key":submission_key(store,decisions_path.parent),"sha256":hashlib.sha256(decisions_path.read_bytes()).hexdigest(),
                       "phase":"complete","record_keys":[r["record_key"] for r in results]}
            connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES(?,?)",(receipt["key"],_json(receipt)))
    finally:
        connection.close()
    write_seconds = round(time.perf_counter() - write_started, 3)
    clear_submitted_inputs(store,facts_path.parent,batch_facts,batch_decisions,{r["record_key"] for r in results})
    export_started = time.perf_counter()
    export = store.publish_pending() if publish else None
    return {
        "batch_id": facts["batch_id"],
        "record_count": len(facts["records"]),
        "write_count": len(results),
        "deferred": deferred,
        "static": static_result,
        "scope": facts.get("scope", "dynamic"),
        "deduplicated": sum(bool(row.get("deduplicated")) for row in results),
        "timing_seconds": {"write": write_seconds, "verify": verification["elapsed_seconds"],
                           "export": round(time.perf_counter() - export_started, 3)},
        "verification": verification,
        "export": export,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
    }


def _current_static_decision(raw):
    fields = {"main_theme":"唯一主炒作属性","main_theme_basis":"唯一主炒依据",
              "replenishment_result":"补涨判断","mapping_basis":"映射依据",
              "suppression_result":"压制判断","suppression_basis":"压制依据",
              "suppression_details":"一字压制核验明细","competitors":"首开潜在竞争对手事实清单",
              "announcement_pollution":"公告污染","announcement_basis":"公告污染依据"}
    return {key:raw.get(field) for key,field in fields.items()}


def verify_batch_current(store, directory):
    manifest = _read_json(directory / "batch.json")
    keys = manifest["record_keys"]
    if manifest['scope']=='dynamic':
        connection=store.connect()
        try:
            facts=[];decisions=[];findings=[]
            for row in _select_records(connection,None,None,keys):
                fact=_record_facts(store,connection,[],None,row,'dynamic')
                raw=fact['current_dynamic_raw']
                if not raw:
                    findings.append(fact['record_key']+' 缺少交易记录')
                    continue
                facts.append(fact)
                decisions.append({'record_key':fact['record_key'],'static':_current_static_decision(fact['current_static_raw']),
                    'dynamic':{'auction':raw.get('竞价筛选'),'pk_checks':raw.get('同题材PK核验明细'),
                               'pk_result':raw.get('同题材PK结果'),'buy_point':raw.get('首开买点'),'outcome':raw.get('买入后结果')}})
            result=verify_dynamic(store,{'records':facts},{'records':decisions},connection)
            result['findings'].extend(findings)
            result.update(passed=not result['findings'],record_count=len(keys))
            return result
        finally:connection.close()
    from .derive import recompute
    result = recompute(store, keys, preview=True,verify_saved=True)
    connection = store.connect()
    findings = result["findings"] + [f"{b['record_key']}: {b['reason']}" for b in result["blocked"]]
    for row in result["records"]:
        saved = connection.execute("SELECT * FROM current_static_research WHERE legacy_record_key=?",(row["record_key"],)).fetchone()
        raw = json.loads(saved["raw_json"])
        actual = (saved["main_theme"],saved["replenishment_result"],saved["suppression_result"])
        if actual != (row["main_theme"],row["replenishment"],row["suppression"]):
            findings.append(row["record_key"] + " 派生字段与当前输入不一致")
        competitors = [v.get("股票代码",v.get("code")) for v in raw.get("首开潜在竞争对手事实清单", [])]
        if competitors != row["competitors"]:
            findings.append(row["record_key"] + " 竞争清单与当前输入不一致")
        if (row["replenishment"] == "补涨" or row["suppression"].startswith("有")) and "首开潜在竞争对手事实清单" in raw:
            findings.append(row["record_key"] + " 旧竞争清单残留")
    if store.db_path == store.root / "data/store/research.sqlite":
        try:
            display = {r["记录键"]:r for r in _read_json(store.root / "一字首开研究总表.json")["一字首开股票与数据"]}
            for row in result["records"]:
                saved = connection.execute("SELECT * FROM current_static_research WHERE legacy_record_key=?",(row["record_key"],)).fetchone()
                raw = json.loads(saved["raw_json"])
                expected = {"唯一主炒":saved["main_theme"],"补涨判断":saved["replenishment_result"],
                            "补涨题材日期":raw.get("补涨题材日期"),"出生当日补涨题材":raw.get("出生当日补涨题材"),
                            "压制判断":saved["suppression_result"],"公告污染":bool(saved["announcement_pollution"]),
                            "潜在竞争对手":raw.get("首开潜在竞争对手事实清单"),
                            "静态筛选结论":raw.get("静态筛选结论")}
                if any(display.get(row["record_key"],{}).get(k)!=v for k,v in expected.items()):
                    findings.append(row["record_key"] + " 总表与当前库不一致")
        except (OSError,ValueError,KeyError) as exc:
            findings.append("总表读取失败："+str(exc))
    connection.close()
    return {"passed":not findings,"record_count":len(result["records"]),"findings":findings,"timing_seconds":result["timing_seconds"]}
