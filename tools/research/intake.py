"""Incremental source intake. Original files and research conclusions remain intact."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .system import SHANGHAI, json_text, sha256_file, valid_code


def _kind(path: str) -> str:
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
                                   "data/kaipanla/plate_members", "data/price_checks"]
    files = set()
    for value in roots:
        path = (store.root / value).resolve()
        path.relative_to(store.root.resolve())
        if path.is_dir():
            files.update(item for item in path.rglob("*.json") if item.is_file())
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
    imported = {}
    if any(path.relative_to(store.root).as_posix() not in receipts for path in files):
        for table in ("stock_concepts", "plate_memberships", "daily_market", "market_source_facts"):
            parsed.update(row[0] for row in connection.execute(f"SELECT DISTINCT evidence_file_id FROM {table}"))
        # Seed empty successful sources from the verified full-import inventory once.
        # Empty daily responses have no fact rows and still must not trigger a rebuild.
        full = connection.execute("SELECT summary_json FROM import_batches WHERE kind='full_migration' AND status='complete' ORDER BY id DESC LIMIT 1").fetchone()
        inventory = store.root / "data/store/migrations/reports/evidence_inventory.jsonl"
        summary = json.loads(full[0]) if full else {}
        if inventory.exists() and sha256_file(inventory) == summary.get("evidence_inventory", {}).get("inventory_sha256"):
            reports = {"concepts": ["concepts"], "members": ["plate_members"], "prices": ["price_checks"],
                       "raw": ["raw_market", "market_source_facts"], "evidence": []}
            with inventory.open(encoding="utf-8") as source:
                for line in source:
                    item = json.loads(line)
                    if all(key in summary and not summary[key].get("parse_errors") for key in reports[_kind(item["path"]) ]):
                        imported[item["path"]] = item["sha256"]
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
        baseline = previous and (previous["id"] in parsed or imported.get(relative) == previous["sha256"] or _kind(relative) == "evidence")
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
