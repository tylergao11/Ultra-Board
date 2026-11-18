"""Incremental source intake. Original files and research conclusions remain intact."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .system import SHANGHAI, canonical_hash, json_text, sha256_file, valid_code


def _kind(path: str) -> str:
    if path.startswith('data/market_status/') and path.endswith('.json'):
        return 'suspensions'
    if path.startswith('data/kaipanla/stock_history/'):
        return 'history'
    if path.startswith("data/kaipanla/raw/"):
        name = Path(path).name
        return "raw" if name in {"zt_pool.json", "historical_messages.json", "sector_ladder.json"} or name.startswith("limit_performance_") else "evidence"
    if path.startswith("data/kaipanla/concepts_current/"):
        return "concepts"
    if path.startswith("data/kaipanla/plate_members/"):
        return "members"
    if path.startswith("data/price_checks/"):
        return "prices"
    return "evidence"


def ingest_paths(store, paths: list[Path | str] | None = None) -> dict:
    """Explicit paths hash only those files; daily discovery checks metadata first."""
    started = time.perf_counter()
    explicit = paths is not None
    roots = paths if explicit else ["data/kaipanla/raw", "data/kaipanla/concepts_current",
                                   "data/kaipanla/plate_members", "data/kaipanla/stock_history", "data/price_checks", "data/market_status"]
    files = set()
    for value in roots:
        path = (store.root / value).resolve()
        path.relative_to(store.root.resolve())
        if path.is_dir():
            files.update(item for item in path.rglob("*") if item.is_file() and (item.suffix==".json" or (item.suffix==".js" and item.parent.name=="ths_kline")))
        elif path.is_file():
            files.add(path)
        elif explicit:
            raise FileNotFoundError(path)
    connection = store.connect()
    receipts = {row["key"][7:]: json.loads(row["value"]) for row in connection.execute(
        "SELECT key,value FROM store_meta WHERE key LIKE 'intake:%'"
    )}
    evidence = {row["path"]: dict(row) for row in connection.execute(
        """SELECT e.*,c.sha256,c.size_bytes FROM evidence_files e
           JOIN evidence_contents c ON c.id=e.content_id WHERE e.parse_status='indexed' ORDER BY e.id"""
    )}
    # Existing structured rows provide the initial receipt; registration alone does not.
    parsed = set()
    if any(path.relative_to(store.root).as_posix() not in receipts for path in files):
        for table in ("stock_concepts", "plate_memberships", "daily_market", "market_source_facts"):
            parsed.update(row[0] for row in connection.execute(f"SELECT DISTINCT evidence_file_id FROM {table}"))
    pending = {}
    result = {"files_considered": len(files), "files_hashed": 0, "updated": [], "unchanged": 0,
              "affected_records": [], "errors": [], "full_imports": 0}
    for path in sorted(files):
        relative = path.relative_to(store.root).as_posix()
        stat = path.stat()
        receipt = receipts.get(relative)
        previous = evidence.get(relative)
        metadata = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
        if not explicit and receipt and all(receipt.get(k) == v for k, v in metadata.items()):
            result["unchanged"] += 1
            continue
        modified = datetime.fromtimestamp(stat.st_mtime, SHANGHAI).isoformat(timespec="seconds")
        baseline = previous and (previous["id"] in parsed or _kind(relative) == "evidence")
        if not explicit and baseline and previous["size_bytes"] == stat.st_size and previous["modified_at"] == modified:
            digest = previous["sha256"]
        else:
            digest = sha256_file(path)
            result["files_hashed"] += 1
        metadata["sha256"] = digest
        if (receipt and receipt["sha256"] == digest) or (baseline and previous["sha256"] == digest):
            connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES(?,?)",
                               (f"intake:{relative}", json_text(metadata)))
            result["unchanged"] += 1
            continue
        unit = ("raw", path.parent.name) if _kind(relative) == "raw" else (_kind(relative), relative)
        pending.setdefault(unit, []).append((path, relative, metadata))
    connection.commit()
    batch = connection.execute("SELECT value FROM store_meta WHERE key='current_batch_key'").fetchone()
    rule = connection.execute("SELECT id FROM rule_sets WHERE rule_type='static' AND status='current'").fetchone()
    raw_days = sorted(path.name for path in (store.root / "data/kaipanla/raw").glob("20??-??-??") if path.is_dir())
    try:
        for (kind, unit), items in pending.items():
            try:
                with store.immediate(connection):
                    for path, relative, metadata in items:
                        store.register_evidence_path(path, connection)
                        if kind in {"concepts", "members", "prices"}:
                            table = {"concepts": "stock_concepts", "members": "plate_memberships", "prices": "daily_market"}[kind]
                            connection.execute(f"DELETE FROM {table} WHERE evidence_file_id IN (SELECT id FROM evidence_files WHERE path=?)", (relative,))
                    if kind == "raw":
                        if not batch or not rule:
                            raise ValueError("initialize the research database before daily intake")
                        affected_days = {unit}
                        index = raw_days.index(unit)
                        if index + 1 < len(raw_days):
                            affected_days.add(raw_days[index + 1])
                        pool_path = store.root / "data/kaipanla/raw" / unit / "zt_pool.json"
                        if pool_path.exists():
                            document = json.loads(pool_path.read_text(encoding="utf-8"))
                            if not isinstance(document.get("stocks"), list):
                                raise ValueError("zt_pool stocks must be an array")
                            if document.get("date", unit) != unit:
                                raise ValueError("zt_pool date differs from directory date")
                            store.register_evidence_path(pool_path, connection)
                            connection.execute("DELETE FROM intraday_events WHERE trade_date=? AND event_type='first_limit' AND evidence_file_id IN (SELECT id FROM evidence_files WHERE path=?)", (unit, pool_path.relative_to(store.root).as_posix()))
                            connection.execute("DELETE FROM daily_market WHERE trade_date=? AND source_type='kaipanla_limit_pool'", (unit,))
                            connection.execute("""DELETE FROM pool_members WHERE pool_id IN
                                (SELECT id FROM stock_pools WHERE pool_date=? AND input_version=? AND candidate_event_id IS NULL
                                 AND pool_type IN ('limit_up','strict_one_word','high_standard'))""", (unit, batch["value"]))
                            store.import_raw_market(connection, rule["id"], batch["value"], [pool_path], commit=False)
                        for day in affected_days:
                            connection.execute("DELETE FROM market_source_facts WHERE trade_date=?", (day,))
                            connection.execute("""DELETE FROM pool_members WHERE pool_id IN
                                (SELECT id FROM stock_pools WHERE pool_date=? AND input_version=?
                                 AND candidate_event_id IS NULL AND pool_type='broken_high_standard')""", (day, batch["value"]))
                        store.import_market_source_facts(connection, rule["id"], batch["value"], affected_days, commit=False)
                        impacted = connection.execute("""SELECT l.legacy_record_key FROM launch_rounds l
                            JOIN first_open_events e ON e.launch_round_id=l.id
                            WHERE l.first_board_date<=? AND COALESCE(e.event_date,l.focus_date)>=?""", (unit, unit)).fetchall()
                        for row in impacted:
                            connection.execute("""INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
                                VALUES('source_update',?,'facts_changed','review',?,?)""",
                                (row[0], f"source date {unit} refreshed", "Review the changed event facts; saved research conclusions are preserved."))
                        result["affected_records"].extend(row[0] for row in impacted)
                    elif kind == "concepts":
                        store.import_concepts(connection, [item[0] for item in items], commit=False)
                    elif kind == "members":
                        store.import_plate_members(connection, [item[0] for item in items], commit=False)
                    elif kind == "prices":
                        store.import_price_checks(connection, [item[0] for item in items], commit=False)
                    elif kind == 'history':
                        from .events import import_history_file
                        for item in items:import_history_file(store,connection,item[0])
                    elif kind == 'suspensions':
                        from .events import import_suspension_file
                        for item in items:import_suspension_file(store,connection,item[0])
                    for path, relative, metadata in items:
                        connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES(?,?)",
                                           (f"intake:{relative}", json_text(metadata)))
                result["updated"].extend(item[1] for item in items)
            except Exception as exc:
                store._evidence_cache.clear()
                result["errors"].append({"scope": unit, "files": [item[1] for item in items],
                                         "error": f"{type(exc).__name__}: {exc}"})
    finally:
        connection.close()
    result["affected_records"] = sorted(set(result["affected_records"]))
    result["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    return result


def fetch_attributes(store, codes: list[str], refresh: bool = False) -> dict:
    """Fetch independent stocks concurrently; ingest together and retain per-stock failures."""
    started = time.perf_counter()
    codes = sorted(set(codes))
    if any(valid_code(code) != code for code in codes):
        raise ValueError("stock codes must contain six digits")
    date = datetime.now(SHANGHAI).date().isoformat()
    directory = store.root / "data/kaipanla/concepts_current" / date
    endpoint = "https://apphq.longhuvip.com/w1/api/index.php"
    def fetch(code):
        path = directory / f"{code}.json"
        if path.exists() and not refresh:
            return path
        parameters = {"a": "GetStockIDPlate", "c": "StockL2Data", "StockID": code,
                      "Type": "2", "apiv": "w43", "PhoneOSNew": "1"}
        request = Request(endpoint + "?" + urlencode(parameters))
        with urlopen(request, timeout=20) as response:
            raw = json.loads(response.read().decode("utf-8"))
        if str(raw.get("errcode", "0")) != "0":
            raise ValueError(f"source returned errcode {raw.get('errcode')}")
        concepts = (raw.get("List") or []) + (raw.get("ListJX") or [])
        if not concepts:
            raise ValueError("source returned an empty attribute set; existing snapshot retained")
        document = {"code": code, "captured_date": date, "snapshot_mode": "current", "raw_response": raw,
                    "concepts": concepts, "source_endpoint": endpoint, "source_parameters": parameters}
        directory.mkdir(parents=True, exist_ok=True)
        # A same-day refresh gets its own raw file; earlier evidence remains readable.
        if path.exists():
            path = directory / f"{code}-{datetime.now(SHANGHAI).strftime('%H%M%S%f')}.json"
        path.write_text(json_text(document, pretty=True) + "\n", encoding="utf-8")
        return path
    saved, errors = [], []
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(fetch, code): code for code in codes}
        for future in as_completed(tasks):
            try:
                saved.append(future.result())
            except Exception as exc:
                errors.append({"code": tasks[future], "error": f"{type(exc).__name__}: {exc}"})
    intake = ingest_paths(store, saved) if saved else None
    return {"saved": [path.relative_to(store.root).as_posix() for path in sorted(saved)], "errors": errors,
            "intake": intake, "elapsed_seconds": round(time.perf_counter() - started, 3)}


def sync_candidates(store, start: str, end: str) -> dict:
    """Register or advance strict one-word (>=2 boards) candidate events from ingested limit pools."""
    datetime.strptime(start, "%Y-%m-%d")
    datetime.strptime(end, "%Y-%m-%d")
    connection = store.connect()
    created, advanced, opened = [], [], []
    try:
        dates = [r[0] for r in connection.execute(
            "SELECT DISTINCT trade_date FROM daily_market WHERE source_type='kaipanla_limit_pool' ORDER BY trade_date"
        )]
        next_day = {dates[i]: (dates[i + 1] if i + 1 < len(dates) else None) for i in range(len(dates))}
        stocks = connection.execute(
            """SELECT DISTINCT d.stock_id, s.code FROM daily_market d
               JOIN stocks s ON s.id=d.stock_id
               WHERE d.source_type='kaipanla_limit_pool' AND d.strict_one_word=1
                 AND d.board_height>=2 AND d.trade_date BETWEEN ? AND ?
               ORDER BY s.code""",
            (start, end),
        ).fetchall()
        batch_id = connection.execute("SELECT id FROM import_batches ORDER BY id LIMIT 1").fetchone()[0]
        rule_id = connection.execute(
            "SELECT id FROM rule_sets WHERE rule_type='static' AND status='current' ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        empty_hash = canonical_hash({})
        with store.immediate(connection):
            for stock_id, code in stocks:
                rows = connection.execute(
                    """SELECT trade_date, board_height, strict_one_word FROM daily_market
                       WHERE stock_id=? AND source_type='kaipanla_limit_pool' AND board_height IS NOT NULL
                       ORDER BY trade_date""",
                    (stock_id,),
                ).fetchall()
                rounds: list[list[tuple[str, int, int]]] = []
                for trade_date, height, strict in rows:
                    if height == 1 or not rounds or height != rounds[-1][-1][1] + 1:
                        rounds.append([(trade_date, int(height), int(strict or 0))])
                    else:
                        rounds[-1].append((trade_date, int(height), int(strict or 0)))
                for rnd in rounds:
                    if rnd[0][1] != 1:
                        continue
                    first_board = rnd[0][0]
                    idx = 0
                    while idx < len(rnd):
                        if not rnd[idx][2]:
                            idx += 1
                            continue
                        j = idx
                        while j + 1 < len(rnd) and rnd[j + 1][2]:
                            j += 1
                        run_start = rnd[idx][0]
                        focus_date, focus_height, _ = rnd[j]
                        idx = j + 1
                        if focus_height < 2 or not (start <= focus_date <= end):
                            continue
                        event_date = next_day.get(focus_date)
                        seq_rows = [r for r in rnd if r[0] <= focus_date]
                        seq_text = "；".join(
                            f"{d[5:]} {'首板' if h == 1 else f'{h}连板'}" + ("一字" if s else "")
                            for d, h, s in seq_rows
                        )
                        key = f"{code}|{focus_date}"
                        name_row = connection.execute(
                            "SELECT name FROM stock_current_names WHERE stock_id=?", (stock_id,)
                        ).fetchone()
                        name = name_row[0] if name_row else code
                        existing = connection.execute(
                            "SELECT * FROM legacy_key_map WHERE legacy_record_key=?", (key,)
                        ).fetchone()
                        if existing:
                            fo = connection.execute(
                                "SELECT event_date FROM first_open_events WHERE id=?",
                                (existing["first_open_event_id"],),
                            ).fetchone()
                            if event_date and not fo["event_date"]:
                                connection.execute(
                                    "UPDATE first_open_events SET event_date=?, event_status='occurred' WHERE id=?",
                                    (event_date, existing["first_open_event_id"]),
                                )
                                connection.execute(
                                    "UPDATE one_word_runs SET status='occurred' WHERE launch_round_id=?",
                                    (existing["launch_round_id"],),
                                )
                                cur_sr = connection.execute(
                                    "SELECT id, raw_json FROM static_research WHERE legacy_record_key=? AND is_current=1",
                                    (key,),
                                ).fetchone()
                                if cur_sr:
                                    raw = json.loads(cur_sr["raw_json"])
                                    raw["首开日期"] = event_date
                                    connection.execute(
                                        "UPDATE static_research SET raw_json=? WHERE id=?",
                                        (json_text(raw), cur_sr["id"]),
                                    )
                                opened.append(key)
                            continue
                        prior = connection.execute(
                            """SELECT l.legacy_record_key FROM launch_rounds l
                               WHERE l.stock_id=? AND l.first_board_date=?
                                 AND l.focus_date>=? AND l.focus_date<?
                               ORDER BY l.focus_date DESC LIMIT 1""",
                            (stock_id, first_board, run_start, focus_date),
                        ).fetchone()
                        if prior and not connection.execute(
                            "SELECT 1 FROM dynamic_research WHERE legacy_record_key=?", (prior[0],)
                        ).fetchone():
                            old_key = prior[0]
                            m = connection.execute(
                                "SELECT * FROM legacy_key_map WHERE legacy_record_key=?", (old_key,)
                            ).fetchone()
                            connection.execute("DELETE FROM research_dependencies WHERE record_key=?", (old_key,))
                            connection.execute(
                                "UPDATE source_records SET record_key=?, effective_date=? WHERE id=?",
                                (key, focus_date, m["static_source_record_id"]),
                            )
                            connection.execute(
                                "UPDATE launch_rounds SET legacy_record_key=?, focus_date=?, board_sequence_text=? WHERE id=?",
                                (key, focus_date, seq_text, m["launch_round_id"]),
                            )
                            connection.execute(
                                "UPDATE one_word_runs SET start_date=?, end_date=?, status=? WHERE launch_round_id=?",
                                (run_start, focus_date, "occurred" if event_date else "first_open_missing_or_not_occurred", m["launch_round_id"]),
                            )
                            connection.execute(
                                "UPDATE first_open_events SET legacy_record_key=?, event_date=?, event_status=? WHERE id=?",
                                (key, event_date, "occurred" if event_date else "pending_open", m["first_open_event_id"]),
                            )
                            connection.execute(
                                "UPDATE legacy_key_map SET legacy_record_key=? WHERE legacy_record_key=?",
                                (key, old_key),
                            )
                            connection.execute(
                                "UPDATE static_research SET legacy_record_key=? WHERE legacy_record_key=?",
                                (key, old_key),
                            )
                            cur_sr = connection.execute(
                                "SELECT id, raw_json FROM static_research WHERE legacy_record_key=? AND is_current=1",
                                (key,),
                            ).fetchone()
                            if cur_sr:
                                raw = json.loads(cur_sr["raw_json"])
                                raw.update({
                                    "底稿记录键": key,
                                    "关注日期": focus_date,
                                    "底稿板序原文": seq_text,
                                    "进板高度": f"{focus_height}进{focus_height + 1}",
                                    "首开日期": event_date or "",
                                })
                                connection.execute(
                                    "UPDATE static_research SET raw_json=? WHERE id=?",
                                    (json_text(raw), cur_sr["id"]),
                                )
                            advanced.append({"from": old_key, "to": key, "event_date": event_date})
                            continue
                        sr_id = connection.execute(
                            """INSERT INTO source_records
                               (batch_id,source_kind,source_path,section,record_key,stock_code,effective_date,raw_sha256,raw_json)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (batch_id, "record_anchor", "一字首开研究总表.json", "一字首开股票与数据", key, code, focus_date, empty_hash, "{}"),
                        ).lastrowid
                        lr_id = connection.execute(
                            """INSERT INTO launch_rounds
                               (stock_id,legacy_record_key,first_board_date,focus_date,board_sequence_text,
                                confirmed_main_theme,confirmation_status,source_record_id,raw_json)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (stock_id, key, first_board, focus_date, seq_text, None, "pending_user_confirmation", sr_id, "{}"),
                        ).lastrowid
                        ow_id = connection.execute(
                            """INSERT INTO one_word_runs(launch_round_id,start_date,end_date,status,raw_json)
                               VALUES(?,?,?,?,?)""",
                            (lr_id, run_start, focus_date, "occurred" if event_date else "first_open_missing_or_not_occurred", "{}"),
                        ).lastrowid
                        fo_id = connection.execute(
                            """INSERT INTO first_open_events
                               (launch_round_id,one_word_run_id,event_date,event_status,legacy_record_key,raw_json)
                               VALUES(?,?,?,?,?,?)""",
                            (lr_id, ow_id, event_date, "occurred" if event_date else "pending_open", key, "{}"),
                        ).lastrowid
                        connection.execute(
                            """INSERT INTO legacy_key_map
                               (legacy_record_key,stock_id,launch_round_id,first_open_event_id,static_source_record_id,dynamic_source_record_id)
                               VALUES(?,?,?,?,?,NULL)""",
                            (key, stock_id, lr_id, fo_id, sr_id),
                        )
                        seed_raw = {
                            "底稿记录键": key,
                            "股票代码": code,
                            "股票": name,
                            "关注日期": focus_date,
                            "底稿首板日期": first_board,
                            "底稿板序原文": seq_text,
                            "进板高度": f"{focus_height}进{focus_height + 1}",
                            "首开日期": event_date or "",
                        }
                        connection.execute(
                            """INSERT INTO static_research
                               (first_open_event_id,legacy_record_key,version,is_current,research_status,
                                confirmation_status,source_record_id,rule_set_id,evidence_snapshot_json,raw_json)
                               VALUES(?,?,1,1,'unresearched','pending_user_confirmation',?,?,?,?)""",
                            (fo_id, key, sr_id, rule_id, "[]", json_text(seed_raw)),
                        )
                        created.append({"record_key": key, "first_board_date": first_board, "event_date": event_date})
    finally:
        connection.close()
    return {"start": start, "end": end, "created": created, "advanced": advanced, "opened": opened}

