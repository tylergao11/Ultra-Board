from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable
import zipfile

from .statistics import build_statistics_report
from .source_parsers import iter_absent_continuation_facts, iter_day_source_facts
from .scratch import Workspace


SHANGHAI = timezone(timedelta(hours=8))
STATIC_FILE = "一字首开研究总表.json"
DYNAMIC_FILE = "一字首开买卖研究表.json"
STATIC_SECTION = "一字首开股票与数据"
DYNAMIC_SECTION = "买卖研究记录"


def now_text() -> str:
    return datetime.now(SHANGHAI).isoformat(timespec="seconds")


def json_text(value: Any, *, pretty: bool = False) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2 if pretty else None,
        separators=None if pretty else (",", ":"),
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return sha256_bytes(json_text(value).encode("utf-8"))


def price_milli(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int((Decimal(str(value)) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return None


def pct_micros(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int((Decimal(str(value)) * 1_000_000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return None


def market_for(code: str) -> str:
    if code.startswith(("4", "8", "92")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def valid_code(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if re.fullmatch(r"\d{6}", text) else None


def source_date_from_path(path: str) -> str | None:
    match = re.search(r"(?:^|/)(20\d{2}-\d{2}-\d{2})(?:/|$)", path.replace("\\", "/"))
    return match.group(1) if match else None


def evidence_category(relative_path: str) -> str:
    value = relative_path.replace("\\", "/")
    if value.startswith("data/kaipanla/raw/"):
        return "kaipanla_raw"
    if value.startswith("data/kaipanla/concepts_current/"):
        return "concept_snapshot"
    if value.startswith("data/kaipanla/plate_members/"):
        return "plate_membership"
    if value.startswith("data/kaipanla/"):
        return "kaipanla_other"
    if value.startswith("data/price_checks/"):
        return "price_check"
    if value.startswith("data/research/"):
        return "research_evidence"
    if value.startswith("tools/"):
        return "tool_source"
    if value.startswith("docs/"):
        return "project_document"
    return "research_source"




def collect_sources(value: Any) -> list[str]:
    found: list[str] = []

    def visit(item: Any, parent_key: str = "") -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if "来源" in str(key) or str(key) in {"文件", "source"}:
                    if isinstance(child, str):
                        found.append(child)
                    elif isinstance(child, list):
                        found.extend(str(v) for v in child if isinstance(v, str))
                visit(child, str(key))
        elif isinstance(item, list):
            for child in item:
                visit(child, parent_key)

    visit(value)
    return sorted(set(path for path in found if path))


class ResearchStore:
    def __init__(self, root: Path | str, db_path: Path | str | None = None) -> None:
        self.root = Path(root).resolve()
        self.db_path = Path(db_path).resolve() if db_path else self.root / "data/store/research.sqlite"
        self.migrations_dir = self.root / "tools/research/migrations"
        self._stock_cache: dict[str, int] = {}
        self._evidence_cache: dict[str, int | None] = {}

    def connect(self, path: Path | None = None) -> sqlite3.Connection:
        target = path or self.db_path
        target.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(target, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def immediate(self, connection: sqlite3.Connection):
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()

    def apply_migrations(self, connection: sqlite3.Connection) -> list[int]:
        applied: list[int] = []
        for path in sorted(self.migrations_dir.glob("*.sql")):
            version = int(path.name.split("_", 1)[0])
            payload = path.read_bytes()
            checksum = sha256_bytes(payload)
            exists = connection.execute(
                "SELECT checksum FROM schema_migrations WHERE version=?", (version,)
            ).fetchone() if self._table_exists(connection, "schema_migrations") else None
            if exists:
                if exists["checksum"] != checksum:
                    raise RuntimeError(f"migration checksum mismatch: {path.name}")
                continue
            connection.executescript(payload.decode("utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
                (version, path.name, checksum, now_text()),
            )
            connection.commit()
            applied.append(version)
        return applied

    @staticmethod
    def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone() is not None





    def register_evidence_path(self, path: Path | str, connection: sqlite3.Connection | None = None) -> int:
        target = Path(path)
        if not target.is_absolute():
            target = self.root / target
        target = target.resolve()
        relative = target.relative_to(self.root).as_posix()
        digest = sha256_file(target)
        own = connection is None
        conn = connection or self.connect()
        conn.execute(
            "INSERT OR IGNORE INTO evidence_contents(sha256,size_bytes) VALUES(?,?)",
            (digest, target.stat().st_size),
        )
        content_id = conn.execute("SELECT id FROM evidence_contents WHERE sha256=?", (digest,)).fetchone()["id"]
        modified = datetime.fromtimestamp(target.stat().st_mtime, SHANGHAI).isoformat(timespec="seconds")
        conn.execute(
            """INSERT OR IGNORE INTO evidence_files
               (path,content_id,category,source_date,captured_at,modified_at,parse_status)
               VALUES(?,?,?,?,?,?,?)""",
            (relative, content_id, evidence_category(relative), source_date_from_path(relative), None, modified, "indexed"),
        )
        row_id = conn.execute(
            "SELECT id FROM evidence_files WHERE path=? AND content_id=?", (relative, content_id)
        ).fetchone()["id"]
        conn.execute("UPDATE evidence_files SET parse_status='superseded_path_version' WHERE path=? AND id<>?", (relative, row_id))
        conn.execute("UPDATE evidence_files SET parse_status='indexed',parse_error=NULL,modified_at=? WHERE id=?", (modified, row_id))
        if own:
            conn.commit()
            conn.close()
        self._evidence_cache[relative] = row_id
        return row_id

    def build_evidence_inventory(self, connection: sqlite3.Connection, output_path: Path) -> dict[str, Any]:
        candidates: list[Path] = []
        for base in (self.root / "data/kaipanla", self.root / "data/price_checks", self.root / "data/research"):
            if base.exists():
                candidates.extend(path for path in base.rglob("*") if path.is_file())
        candidates.extend([
            self.root / "AGENTS.md",
            self.root / "docs/研究系统执行计划.md",
            self.root / STATIC_FILE,
            self.root / DYNAMIC_FILE,
        ])
        candidates.extend(path for path in (self.root / "tools").rglob("*.py") if "__pycache__" not in path.parts)
        rules_dir = self.root / "data/store/rules"
        if rules_dir.exists():
            candidates.extend(path for path in rules_dir.rglob("*.json") if path.is_file())
        candidates = sorted(set(path.resolve() for path in candidates if path.exists()))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
        totals: dict[str, int] = {"files": 0, "bytes": 0, "duplicate_contents": 0}
        seen_hashes: set[str] = set()
        connection.execute("DROP TABLE IF EXISTS temp.current_evidence_paths")
        connection.execute(
            "CREATE TEMP TABLE current_evidence_paths(path TEXT NOT NULL, content_id INTEGER NOT NULL, PRIMARY KEY(path,content_id))"
        )
        with temp_path.open("w", encoding="utf-8", newline="\n") as output:
            for index, path in enumerate(candidates, start=1):
                relative = path.relative_to(self.root).as_posix()
                digest = sha256_file(path)
                duplicate = digest in seen_hashes
                seen_hashes.add(digest)
                stat = path.stat()
                entry = {
                    "path": relative,
                    "sha256": digest,
                    "size": stat.st_size,
                    "modified_at": datetime.fromtimestamp(stat.st_mtime, SHANGHAI).isoformat(timespec="seconds"),
                    "category": evidence_category(relative),
                    "source_date": source_date_from_path(relative),
                    "duplicate_content": duplicate,
                }
                output.write(json_text(entry) + "\n")
                connection.execute(
                    "INSERT OR IGNORE INTO evidence_contents(sha256,size_bytes) VALUES(?,?)",
                    (digest, stat.st_size),
                )
                content_id = connection.execute(
                    "SELECT id FROM evidence_contents WHERE sha256=?", (digest,)
                ).fetchone()["id"]
                connection.execute(
                    """INSERT OR IGNORE INTO evidence_files
                       (path,content_id,category,source_date,captured_at,modified_at,parse_status)
                       VALUES(?,?,?,?,?,?,?)""",
                    (relative, content_id, entry["category"], entry["source_date"], None, entry["modified_at"], "indexed"),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO current_evidence_paths(path,content_id) VALUES(?,?)",
                    (relative, content_id),
                )
                totals["files"] += 1
                totals["bytes"] += stat.st_size
                totals["duplicate_contents"] += int(duplicate)
                if index % 250 == 0:
                    connection.commit()
        os.replace(temp_path, output_path)
        connection.execute(
            """UPDATE evidence_files AS evidence
               SET parse_status=CASE
                   WHEN EXISTS(SELECT 1 FROM current_evidence_paths current
                               WHERE current.path=evidence.path AND current.content_id=evidence.content_id)
                       THEN 'indexed'
                   WHEN EXISTS(SELECT 1 FROM current_evidence_paths current WHERE current.path=evidence.path)
                       THEN 'superseded_path_version'
                   ELSE 'removed_from_current_workspace'
               END,
               parse_error=CASE
                   WHEN EXISTS(SELECT 1 FROM current_evidence_paths current WHERE current.path=evidence.path)
                       THEN NULL
                   ELSE 'path absent from current workspace'
               END"""
        )
        connection.execute("DROP TABLE current_evidence_paths")
        connection.commit()
        totals["unique_contents"] = len(seen_hashes)
        totals["active_files"] = connection.execute(
            "SELECT COUNT(*) AS c FROM evidence_files WHERE parse_status='indexed'"
        ).fetchone()["c"]
        totals["historical_versions"] = connection.execute(
            "SELECT COUNT(*) AS c FROM evidence_files WHERE parse_status='superseded_path_version'"
        ).fetchone()["c"]
        totals["removed_paths"] = connection.execute(
            "SELECT COUNT(*) AS c FROM evidence_files WHERE parse_status='removed_from_current_workspace'"
        ).fetchone()["c"]
        totals["inventory_sha256"] = sha256_file(output_path)
        return totals

    def refresh_evidence_inventory(self) -> dict[str, Any]:
        connection = self.connect()
        self.apply_migrations(connection)
        try:
            return self.build_evidence_inventory(
                connection,
                self.root / "data/store/verification/current/evidence_inventory.jsonl",
            )
        finally:
            connection.close()

    def evidence_id(self, connection: sqlite3.Connection, value: str | None) -> int | None:
        if not value:
            return None
        normalized = value.replace("\\", "/").lstrip("./")
        if normalized in self._evidence_cache:
            return self._evidence_cache[normalized]
        row = connection.execute(
            "SELECT id FROM evidence_files WHERE path=? ORDER BY id DESC LIMIT 1", (normalized,)
        ).fetchone()
        result = int(row["id"]) if row else None
        self._evidence_cache[normalized] = result
        return result


    def import_rules(
        self,
        connection: sqlite3.Connection,
        static_path: Path,
        dynamic_path: Path,
        static_data: dict[str, Any],
        dynamic_data: dict[str, Any],
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        for kind, document in (("static", static_data), ("dynamic", dynamic_data)):
            if document.get("rule_type") != kind or not isinstance(document.get("rules"), dict):
                raise ValueError(f"invalid current rule source: {kind}")
        sources = [
            ("static", static_path, static_data["rules"], static_data.get("effective_from")),
            ("dynamic", dynamic_path, dynamic_data["rules"], dynamic_data.get("effective_from")),
        ]
        agents_path = self.root / "AGENTS.md"
        sources.append((
            "workflow",
            agents_path,
            {"每批复盘流程及约束": agents_path.read_text(encoding="utf-8")},
            datetime.now(SHANGHAI).date().isoformat(),
        ))
        for rule_type, path, rules, effective_from in sources:
            digest = sha256_file(path)
            version = f"{effective_from or datetime.now(SHANGHAI).date().isoformat()}-{digest[:12]}"
            connection.execute(
                "UPDATE rule_sets SET status='superseded' WHERE rule_type=? AND version<>?",
                (rule_type, version),
            )
            connection.execute(
                """INSERT OR IGNORE INTO rule_sets
                   (rule_type,version,status,source_path,source_sha256,effective_from,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (rule_type, version, "current", path.relative_to(self.root).as_posix(), digest, effective_from, now_text()),
            )
            connection.execute(
                "UPDATE rule_sets SET status='current' WHERE rule_type=? AND version=?",
                (rule_type, version),
            )
            rule_id = connection.execute(
                "SELECT id FROM rule_sets WHERE rule_type=? AND version=?", (rule_type, version)
            ).fetchone()["id"]
            result[rule_type] = rule_id
            for section, content in rules.items():
                values = content if isinstance(content, list) else [content]
                for sequence, value in enumerate(values, start=1):
                    connection.execute(
                        """INSERT OR REPLACE INTO rule_items
                           (rule_set_id,section,sequence_no,text_value,raw_json) VALUES(?,?,?,?,?)""",
                        (rule_id, section, sequence, value if isinstance(value, str) else None, json_text(value)),
                    )
        connection.commit()
        return result

    def stock_id(
        self,
        connection: sqlite3.Connection,
        code: str,
        name: str | None = None,
        valid_from: str | None = None,
        source_record_id: int | None = None,
    ) -> int:
        normalized = valid_code(code)
        if normalized is None:
            raise ValueError(f"invalid stock code: {code!r}")
        if normalized not in self._stock_cache:
            connection.execute(
                "INSERT OR IGNORE INTO stocks(code,market,created_at) VALUES(?,?,?)",
                (normalized, market_for(normalized), now_text()),
            )
            self._stock_cache[normalized] = int(
                connection.execute("SELECT id FROM stocks WHERE code=?", (normalized,)).fetchone()["id"]
            )
        stock_id = self._stock_cache[normalized]
        if name:
            clean_name = str(name).strip()
            existing_name = connection.execute(
                "SELECT id,valid_from FROM stock_names WHERE stock_id=? AND name=? ORDER BY id LIMIT 1",
                (stock_id, clean_name),
            ).fetchone()
            if existing_name:
                if valid_from and (existing_name["valid_from"] is None or valid_from > existing_name["valid_from"]):
                    connection.execute(
                        "UPDATE stock_names SET valid_from=?,source_record_id=COALESCE(source_record_id,?) WHERE id=?",
                        (valid_from, source_record_id, existing_name["id"]),
                    )
            else:
                connection.execute(
                    """INSERT INTO stock_names(stock_id,name,valid_from,valid_to,source_record_id)
                       VALUES(?,?,?,?,?)""",
                    (stock_id, clean_name, valid_from, None, source_record_id),
                )
        return stock_id


    def get_or_create_pool(
        self,
        connection: sqlite3.Connection,
        pool_type: str,
        pool_date: str,
        rule_set_id: int | None,
        input_version: str,
        source_kind: str,
        candidate_event_id: int | None = None,
        coverage_status: str = "complete_from_source",
    ) -> int:
        existing = connection.execute(
            """SELECT id FROM stock_pools WHERE pool_type=? AND pool_date=? AND rule_set_id IS ?
               AND candidate_event_id IS ? AND input_version=? AND source_kind=? ORDER BY id LIMIT 1""",
            (pool_type, pool_date, rule_set_id, candidate_event_id, input_version, source_kind),
        ).fetchone()
        if existing:
            return int(existing["id"])
        connection.execute(
            """INSERT OR IGNORE INTO stock_pools
               (pool_type,pool_date,rule_set_id,candidate_event_id,input_version,coverage_status,source_kind)
               VALUES(?,?,?,?,?,?,?)""",
            (pool_type, pool_date, rule_set_id, candidate_event_id, input_version, coverage_status, source_kind),
        )
        row = connection.execute(
            """SELECT id FROM stock_pools WHERE pool_type=? AND pool_date=?
               AND rule_set_id IS ? AND candidate_event_id IS ? AND input_version=? AND source_kind=?""",
            (pool_type, pool_date, rule_set_id, candidate_event_id, input_version, source_kind),
        ).fetchone()
        return int(row["id"])

    def _insert_pool_member(
        self,
        connection: sqlite3.Connection,
        pool_id: int,
        stock_id: int,
        height: int | None,
        status: str | None,
        direction: str | None,
        raw: Any,
        source_record_id: int | None = None,
        evidence_file_id: int | None = None,
    ) -> None:
        connection.execute(
            """INSERT OR IGNORE INTO pool_members
               (pool_id,stock_id,board_height,member_status,query_direction,source_record_id,evidence_file_id,raw_json)
               VALUES(?,?,?,?,?,?,?,?)""",
            (pool_id, stock_id, height, status, direction, source_record_id, evidence_file_id, json_text(raw)),
        )


    def import_raw_market(
        self,
        connection: sqlite3.Connection,
        static_rule_id: int,
        batch_key: str,
        paths: list[Path] | None = None,
        commit: bool = True,
    ) -> dict[str, int]:
        counts = {"dates": 0, "rows": 0, "strict_one_word": 0, "high_standard": 0}
        for path in paths if paths is not None else sorted((self.root / "data/kaipanla/raw").glob("20??-??-??/zt_pool.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                if not commit:
                    raise
                self._mark_parse_error(connection, path, exc)
                continue
            date = document.get("date") or path.parent.name
            evidence_id = self.evidence_id(connection, path.relative_to(self.root).as_posix())
            connection.execute(
                """INSERT INTO trading_days(trade_date,is_trading_day,calendar_source,raw_market_coverage,price_coverage)
                   VALUES(?,1,?,1,0)
                   ON CONFLICT(trade_date) DO UPDATE SET raw_market_coverage=1""",
                (date, "kaipanla_raw"),
            )
            all_pool = self.get_or_create_pool(connection, "limit_up", date, static_rule_id, batch_key, "kaipanla_raw")
            strict_pool = self.get_or_create_pool(connection, "strict_one_word", date, static_rule_id, batch_key, "kaipanla_raw")
            high_pool = self.get_or_create_pool(connection, "high_standard", date, static_rule_id, batch_key, "kaipanla_raw")
            for item in document.get("stocks", []) or []:
                code = valid_code(item.get("code"))
                if code is None:
                    continue
                stock_id = self.stock_id(connection, code, item.get("name"), date)
                raw = item.get("raw") if isinstance(item.get("raw"), list) else []
                strict = bool(len(raw) > 17 and raw[16] == 0 and raw[17] == 0)
                timestamp = item.get("first_limit_ts")
                event_time = None
                if isinstance(timestamp, (int, float)) and timestamp > 0:
                    event_time = datetime.fromtimestamp(timestamp, SHANGHAI).strftime("%H:%M:%S")
                connection.execute(
                    """INSERT OR IGNORE INTO daily_market
                       (stock_id,trade_date,source_type,price_mode,close_milli,limit_up_milli,board_height,
                        first_limit_time,strict_one_word,evidence_file_id,raw_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        stock_id,
                        date,
                        "kaipanla_limit_pool",
                        "unadjusted",
                        price_milli(item.get("price")),
                        price_milli(item.get("price")),
                        item.get("boards"),
                        event_time,
                        int(strict),
                        evidence_id,
                        json_text(item),
                    ),
                )
                if event_time:
                    connection.execute(
                        """INSERT OR IGNORE INTO intraday_events
                           (stock_id,trade_date,event_type,event_time,time_precision,value_json,evidence_file_id)
                           VALUES(?,?,?,?,?,?,?)""",
                        (stock_id, date, "first_limit", event_time, "second", json_text({"source_timestamp": timestamp}), evidence_id),
                    )
                self._insert_pool_member(connection, all_pool, stock_id, item.get("boards"), "limit_up", None, item, evidence_file_id=evidence_id)
                if strict:
                    self._insert_pool_member(connection, strict_pool, stock_id, item.get("boards"), "strict_one_word", "upward_suppression", item, evidence_file_id=evidence_id)
                    counts["strict_one_word"] += 1
                if int(item.get("boards") or 0) >= 4:
                    self._insert_pool_member(connection, high_pool, stock_id, item.get("boards"), "advanced", "high_to_candidate_replenishment", item, evidence_file_id=evidence_id)
                    counts["high_standard"] += 1
                counts["rows"] += 1
            counts["dates"] += 1
            if commit and counts["dates"] % 50 == 0:
                connection.commit()
        if commit:
            self._import_calendar_file(connection)
            connection.commit()
        return counts

    def import_market_source_facts(
        self,
        connection: sqlite3.Connection,
        static_rule_id: int,
        batch_key: str,
        dates: set[str] | None = None,
        commit: bool = True,
    ) -> dict[str, int]:
        counts: dict[str, int] = {"facts": 0, "days": 0, "broken_high": 0, "parse_errors": 0}
        raw_root = self.root / "data/kaipanla/raw"
        day_directories = sorted(
            path for path in raw_root.glob("20??-??-??") if path.is_dir()
        )
        for day in day_directories:
            if dates is not None and day.name not in dates:
                continue
            try:
                for fact in iter_day_source_facts(day, source_root=self.root):
                    code = valid_code(fact.get("stock_code"))
                    stock_id = self.stock_id(
                        connection, code, fact.get("stock_name"), fact.get("source_date")
                    ) if code else None
                    evidence_id = self.evidence_id(connection, fact.get("source_path"))
                    connection.execute(
                        """INSERT OR IGNORE INTO market_source_facts
                           (fact_type,source_kind,trade_date,stock_id,stock_code,stock_name,sector_code,
                            sector_name,topic,topic_tags,description,board_height,event_time,event_datetime,
                            evidence_file_id,raw_location,raw_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            fact.get("fact_type"),
                            fact.get("source_kind"),
                            fact.get("source_date"),
                            stock_id,
                            code,
                            fact.get("stock_name"),
                            fact.get("sector_code"),
                            fact.get("sector_name"),
                            fact.get("topic"),
                            fact.get("topic_tags"),
                            fact.get("description"),
                            fact.get("board_height"),
                            fact.get("event_time"),
                            fact.get("event_datetime"),
                            evidence_id,
                            fact.get("raw_location"),
                            json_text(fact.get("raw")),
                        ),
                    )
                    counts["facts"] += 1
                counts["days"] += 1
            except Exception as exc:
                if not commit:
                    raise
                connection.execute(
                    """INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        "market_source_parse",
                        day.name,
                        "parse_error",
                        "data_gap",
                        f"{type(exc).__name__}: {exc}",
                        "same-day message, ladder, or performance facts for this date require review",
                    ),
                )
                counts["parse_errors"] += 1
            if commit and counts["days"] % 50 == 0:
                connection.commit()
        for index in range(1, len(day_directories)):
            previous = day_directories[index - 1]
            current = day_directories[index]
            if dates is not None and current.name not in dates:
                continue
            current_pool_path = current / "zt_pool.json"
            if not current_pool_path.exists():
                continue
            try:
                current_document = json.loads(current_pool_path.read_text(encoding="utf-8"))
                current_codes = [item.get("code") for item in current_document.get("stocks", []) or []]
                performance_paths = sorted(previous.glob("limit_performance_*.json"))
                broken_facts = list(iter_absent_continuation_facts(
                    performance_paths,
                    current_codes,
                    current_date=current.name,
                    minimum_prior_height=4,
                    source_root=self.root,
                ))
                if not broken_facts:
                    continue
                pool_id = self.get_or_create_pool(
                    connection,
                    "broken_high_standard",
                    current.name,
                    static_rule_id,
                    batch_key,
                    "kaipanla_limit_performance",
                )
                for fact in broken_facts:
                    code = valid_code(fact.get("stock_code"))
                    if code is None:
                        continue
                    stock_id = self.stock_id(connection, code, fact.get("stock_name"), current.name)
                    evidence_id = self.evidence_id(connection, fact.get("source_path"))
                    self._insert_pool_member(
                        connection,
                        pool_id,
                        stock_id,
                        fact.get("prior_board_height"),
                        "broken_today",
                        "high_to_candidate_replenishment",
                        fact,
                        evidence_file_id=evidence_id,
                    )
                    counts["broken_high"] += 1
            except Exception as exc:
                if not commit:
                    raise
                connection.execute(
                    """INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        "broken_high_pool",
                        current.name,
                        "derive_error",
                        "data_gap",
                        f"{type(exc).__name__}: {exc}",
                        "broken-high membership for this date requires source review",
                    ),
                )
        if commit:
            connection.commit()
        return counts

    def _import_calendar_file(self, connection: sqlite3.Connection) -> None:
        calendar_paths = sorted((self.root / "data/kaipanla").glob("market_calendar*.json"))
        for path in calendar_paths:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for row in document.get("info", []) if isinstance(document, dict) else []:
                if isinstance(row, list) and row and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(row[-1])):
                    date = str(row[-1])
                    connection.execute(
                        """INSERT OR IGNORE INTO trading_days
                           (trade_date,is_trading_day,calendar_source,raw_market_coverage,price_coverage)
                           VALUES(?,1,?,0,0)""",
                        (date, path.relative_to(self.root).as_posix()),
                    )
        non_trading = self.root / "data/kaipanla/non_trading_days.json"
        if non_trading.exists():
            try:
                for date in json.loads(non_trading.read_text(encoding="utf-8")):
                    connection.execute(
                        """INSERT OR REPLACE INTO trading_days
                           (trade_date,is_trading_day,calendar_source,raw_market_coverage,price_coverage)
                           VALUES(?,0,?,0,0)""",
                        (date, non_trading.relative_to(self.root).as_posix()),
                    )
            except Exception:
                pass

    def _mark_parse_error(self, connection: sqlite3.Connection, path: Path, exc: Exception) -> None:
        relative = path.relative_to(self.root).as_posix()
        connection.execute(
            "UPDATE evidence_files SET parse_status='error', parse_error=? WHERE path=?",
            (f"{type(exc).__name__}: {exc}", relative),
        )
        connection.execute(
            """INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
               VALUES(?,?,?,?,?,?)""",
            ("evidence_parse", relative, "parse_error", "data_gap", str(exc), "facts from this file remain indexed as raw evidence"),
        )

    def import_concepts(self, connection: sqlite3.Connection, paths: list[Path] | None = None,
                        commit: bool = True) -> dict[str, int]:
        counts = {"files": 0, "relations": 0, "parse_errors": 0}
        for path in paths if paths is not None else sorted((self.root / "data/kaipanla/concepts_current").rglob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(document.get("concepts"), list):
                    raise ValueError("concepts must be an array")
                code = valid_code(document.get("code") or path.stem)
                if code is None:
                    raise ValueError("stock code missing")
                observed = str(document.get("captured_date") or path.parent.name)
                stock_id = self.stock_id(connection, code, None, observed)
                evidence_id = self.evidence_id(connection, path.relative_to(self.root).as_posix())
                for item in document.get("concepts", []) or []:
                    if isinstance(item, dict):
                        source_code = str(item.get("CCode") or "") or None
                        name = str(item.get("CName") or "").strip()
                        analysis = item.get("Analysis")
                    elif isinstance(item, list) and len(item) >= 2:
                        source_code = str(item[0] or "") or None
                        name = str(item[1] or "").strip()
                        analysis = None
                    else:
                        continue
                    if not name:
                        continue
                    connection.execute(
                        "INSERT OR IGNORE INTO concepts(source_code,source_name,unified_name) VALUES(?,?,?)",
                        (source_code, name, name),
                    )
                    concept_id = int(connection.execute(
                        "SELECT id FROM concepts WHERE source_code IS ? AND source_name=?", (source_code, name)
                    ).fetchone()["id"])
                    connection.execute(
                        """INSERT OR IGNORE INTO stock_concepts
                           (stock_id,concept_id,observed_date,captured_date,applies_from,applies_to,
                            historical_status,analysis,evidence_file_id)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            stock_id,
                            concept_id,
                            observed,
                            observed,
                            observed,
                            None,
                            "current_snapshot_not_backfilled",
                            analysis,
                            evidence_id,
                        ),
                    )
                    counts["relations"] += 1
                counts["files"] += 1
            except Exception as exc:
                if not commit:
                    raise
                self._mark_parse_error(connection, path, exc)
                counts["parse_errors"] += 1
            if commit and counts["files"] % 100 == 0:
                connection.commit()
        if commit:
            connection.commit()
        return counts

    def import_plate_members(self, connection: sqlite3.Connection, paths: list[Path] | None = None,
                             commit: bool = True) -> dict[str, int]:
        counts = {"files": 0, "memberships": 0, "parse_errors": 0}
        for path in paths if paths is not None else sorted((self.root / "data/kaipanla/plate_members").rglob("*.json")):
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(document.get("members"), list):
                    raise ValueError("members must be an array")
                date = str(document.get("date") or path.parent.name)
                plate_code = str(document.get("plate_id") or path.stem)
                plate_name = document.get("plate_name") or document.get("name")
                evidence_id = self.evidence_id(connection, path.relative_to(self.root).as_posix())
                for item in document.get("members", []) or []:
                    code = valid_code(item.get("code"))
                    if code is None:
                        continue
                    stock_id = self.stock_id(connection, code, item.get("name"), date)
                    connection.execute(
                        """INSERT OR IGNORE INTO plate_memberships
                           (plate_code,plate_name,trade_date,stock_id,stock_name,evidence_file_id)
                           VALUES(?,?,?,?,?,?)""",
                        (plate_code, plate_name, date, stock_id, item.get("name"), evidence_id),
                    )
                    counts["memberships"] += 1
                counts["files"] += 1
            except Exception as exc:
                if not commit:
                    raise
                self._mark_parse_error(connection, path, exc)
                counts["parse_errors"] += 1
            if commit and counts["files"] % 50 == 0:
                connection.commit()
        if commit:
            connection.commit()
        return counts

    def import_price_checks(self, connection: sqlite3.Connection, paths: list[Path] | None = None,
                            commit: bool = True) -> dict[str, int]:
        counts = {"files": 0, "daily_rows": 0, "parse_errors": 0}
        for path in paths if paths is not None else sorted((self.root / "data/price_checks").rglob("*.json")):
            if path.parent.name == 'iwencai':
                from .events import import_provider_file
                counts['daily_rows'] += import_provider_file(self, connection, path)
                counts['files'] += 1
                continue
            from .market import daily_file_identity, import_daily_file, research_price_needs
            if daily_file_identity(path):
                code, _ = daily_file_identity(path)
                needs, _ = research_price_needs(connection)
                years = {year for stock,year in needs if stock==code}
                counts["daily_rows"] += import_daily_file(self, connection, path, years) if years else 0
                counts["files"] += 1
                continue
            code = valid_code(path.stem)
            if code is None:
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(document, dict):
                    continue
                date_rows = [
                    (date, value) for date, value in document.items()
                    if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", str(date)) and isinstance(value, dict)
                ]
                if not date_rows:
                    continue
                evidence_id = self.evidence_id(connection, path.relative_to(self.root).as_posix())
                stock_id = self.stock_id(connection, code)
                for date, value in date_rows:
                    connection.execute(
                        """INSERT OR IGNORE INTO daily_market
                           (stock_id,trade_date,source_type,price_mode,open_milli,high_milli,low_milli,close_milli,
                            evidence_file_id,raw_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            stock_id,
                            date,
                            "price_check_json",
                            "source_declared_or_unadjusted",
                            price_milli(value.get("open")),
                            price_milli(value.get("high")),
                            price_milli(value.get("low")),
                            price_milli(value.get("close")),
                            evidence_id,
                            json_text(value),
                        ),
                    )
                    connection.execute(
                        """INSERT INTO trading_days(trade_date,is_trading_day,calendar_source,raw_market_coverage,price_coverage)
                           VALUES(?,1,?,0,1)
                           ON CONFLICT(trade_date) DO UPDATE SET price_coverage=1""",
                        (date, "price_checks"),
                    )
                    counts["daily_rows"] += 1
                counts["files"] += 1
            except Exception as exc:
                if not commit:
                    raise
                self._mark_parse_error(connection, path, exc)
                counts["parse_errors"] += 1
            if commit and counts["files"] % 200 == 0:
                connection.commit()
        if commit:
            connection.commit()
        return counts




    def discard_obsolete_research(self, connection):
        """Delete replaced judgments; raw market evidence and current conclusions stay intact."""
        obsolete = """SELECT d.id FROM dynamic_research d
            LEFT JOIN rule_sets r ON r.id=d.rule_set_id
            JOIN research_plans p ON p.id=d.plan_id
            WHERE d.is_current=0 OR r.status IS NOT 'current' OR p.status<>'current'"""
        connection.execute(f"DELETE FROM research_checks WHERE dynamic_research_id IN ({obsolete})")
        connection.execute(f"DELETE FROM trade_outcomes WHERE dynamic_research_id IN ({obsolete})")
        connection.execute(f"DELETE FROM dynamic_research WHERE id IN ({obsolete})")
        connection.execute("DELETE FROM static_research WHERE is_current=0")
        connection.execute("DELETE FROM revisions")
        connection.execute("DELETE FROM rule_items WHERE rule_set_id IN (SELECT id FROM rule_sets WHERE status='superseded')")
        connection.execute("DELETE FROM write_requests WHERE object_type='dynamic' AND object_key NOT IN (SELECT legacy_record_key FROM dynamic_research)")
        connection.execute("DELETE FROM archived_sections WHERE archive_kind IN ('statistics','comparison_study')")
        connection.execute("DELETE FROM statistics WHERE plan_id IN (SELECT id FROM research_plans WHERE status<>'current')")
        connection.execute("DELETE FROM research_plans WHERE status<>'current' AND id NOT IN (SELECT plan_id FROM dynamic_research)")
        connection.execute("UPDATE legacy_key_map SET dynamic_source_record_id=NULL WHERE dynamic_source_record_id IN (SELECT id FROM source_records WHERE source_kind='legacy_dynamic')")
        connection.execute("UPDATE stock_names SET source_record_id=NULL WHERE source_record_id IN (SELECT id FROM source_records WHERE source_kind='legacy_dynamic')")
        connection.execute("DELETE FROM source_records WHERE source_kind='legacy_dynamic' AND id NOT IN (SELECT source_record_id FROM dynamic_research WHERE source_record_id IS NOT NULL)")

    def sync_rules(self) -> dict[str, Any]:
        static_path = self.root / "data/store/rules/static_rules.json"
        dynamic_path = self.root / "data/store/rules/dynamic_rules.json"
        static_data = json.loads(static_path.read_text(encoding="utf-8"))
        dynamic_data = json.loads(dynamic_path.read_text(encoding="utf-8"))
        connection = self.connect()
        self.apply_migrations(connection)
        try:
            saved = {r["rule_type"]:r["source_sha256"] for r in connection.execute("SELECT rule_type,source_sha256 FROM rule_sets WHERE status='current'")}
            digests = {"static":sha256_file(static_path),"dynamic":sha256_file(dynamic_path),"workflow":sha256_file(self.root / "AGENTS.md")}
            reused = saved==digests
            if not reused:
                self.import_rules(connection, static_path, dynamic_path, static_data, dynamic_data)
            # Current trade results use active rules; obsolete derived judgments are deleted.
            view_sql = """CREATE VIEW current_dynamic_research AS
                SELECT d.* FROM dynamic_research d
                JOIN rule_sets r ON r.id=d.rule_set_id
                JOIN research_plans p ON p.id=d.plan_id
                WHERE d.is_current=1 AND r.rule_type='dynamic' AND r.status='current'
                  AND p.status='current'"""
            existing_view = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='view' AND name='current_dynamic_research'"
            ).fetchone()
            if not existing_view or existing_view[0] != view_sql:
                connection.execute("DROP VIEW IF EXISTS current_dynamic_research")
                connection.execute(view_sql)
                connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('statistics_export_pending','1')")
            connection.execute(
                """UPDATE research_plans SET definition_json=?,rule_set_id=(
                    SELECT id FROM rule_sets WHERE rule_type='dynamic' AND status='current')
                    WHERE plan_code='formal' AND status='current'""",
                (json_text({"规则来源": "data/store/rules/dynamic_rules.json"}),),
            )
            if not reused:
                connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('statistics_export_pending','1')")
            self.discard_obsolete_research(connection)
            connection.commit()
            current = {
                row["rule_type"]: {"source_path": row["source_path"]}
                for row in connection.execute(
                    "SELECT rule_type,source_path FROM rule_sets WHERE status='current' ORDER BY rule_type"
                )
            }
        finally:
            connection.close()
        return {"current": current, "synced_at": now_text(),"reused":reused}



    def logical_snapshot_hash(self, connection: sqlite3.Connection) -> str:
        tables = [
            "stocks",
            "stock_names",
            "concepts",
            "stock_concepts",
            "plate_memberships",
            "daily_market",
            "intraday_events",
            "announcements",
            "launch_rounds",
            "one_word_runs",
            "first_open_events",
            "stock_pools",
            "pool_members",
            "research_plans",
            "rule_sets",
            "static_research",
            "dynamic_research",
            "research_checks",
            "trade_outcomes",
            "revisions",
            "issues",
        ]
        digest = hashlib.sha256()
        for table in tables:
            digest.update(f"table:{table}\n".encode("utf-8"))
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                digest.update(json_text(list(row)).encode("utf-8"))
                digest.update(b"\n")
        batch = connection.execute(
            "SELECT value FROM store_meta WHERE key='current_batch_key'"
        ).fetchone()["value"]
        digest.update(f"batch:{batch}\n".encode("utf-8"))
        schema = [dict(row) for row in connection.execute(
            "SELECT version,checksum FROM schema_migrations ORDER BY version"
        )]
        digest.update(json_text(schema).encode("utf-8"))
        return digest.hexdigest()

    def query_stock(self, code: str) -> dict[str, Any]:
        connection = self.connect()
        row = connection.execute(
            "SELECT * FROM stock_current_names WHERE code=?", (code,)
        ).fetchone()
        if not row:
            connection.close()
            raise KeyError(code)
        stock_id = row["stock_id"]
        result = {
            "stock": dict(row),
            "name_history": [dict(item) for item in connection.execute(
                "SELECT name,valid_from,valid_to FROM stock_names WHERE stock_id=? ORDER BY COALESCE(valid_from,'')", (stock_id,)
            )],
            "launch_rounds": [dict(item) for item in connection.execute(
                """SELECT legacy_record_key,first_board_date,focus_date,confirmed_main_theme,confirmation_status
                   FROM launch_rounds WHERE stock_id=? ORDER BY focus_date""", (stock_id,)
            )],
            "first_open_events": [dict(item) for item in connection.execute(
                """SELECT e.legacy_record_key,e.event_date,e.event_status
                   FROM first_open_events e JOIN launch_rounds r ON r.id=e.launch_round_id
                   WHERE r.stock_id=? ORDER BY COALESCE(e.event_date,r.focus_date)""", (stock_id,)
            )],
            "coverage": [dict(item) for item in connection.execute(
                """SELECT source_type,MIN(trade_date) AS first_date,MAX(trade_date) AS last_date,COUNT(*) AS rows
                   FROM daily_market WHERE stock_id=? GROUP BY source_type ORDER BY source_type""", (stock_id,)
            )],
        }
        connection.close()
        return result

    def query_attributes(self, code: str, research_date: str) -> dict[str, Any]:
        connection = self.connect()
        stock = connection.execute("SELECT id FROM stocks WHERE code=?", (code,)).fetchone()
        if not stock:
            connection.close()
            raise KeyError(code)
        rows = [dict(item) for item in connection.execute(
            """SELECT c.source_code,c.source_name,c.unified_name,sc.observed_date,sc.captured_date,
                      sc.historical_status,sc.analysis,ef.path AS evidence
               FROM stock_concepts sc JOIN concepts c ON c.id=sc.concept_id
               LEFT JOIN evidence_files ef ON ef.id=sc.evidence_file_id
               WHERE sc.stock_id=? AND sc.observed_date<=?
               AND sc.observed_date=(SELECT MAX(sc2.observed_date) FROM stock_concepts sc2
                                     WHERE sc2.stock_id=sc.stock_id AND sc2.observed_date<=?)
               ORDER BY c.unified_name,c.source_name""",
            (stock["id"], research_date, research_date),
        )]
        plate_rows = [dict(item) for item in connection.execute(
            """SELECT plate_code,plate_name,trade_date,ef.path AS evidence
               FROM plate_memberships pm LEFT JOIN evidence_files ef ON ef.id=pm.evidence_file_id
               WHERE pm.stock_id=? AND pm.trade_date<=? AND pm.trade_date=(
                   SELECT MAX(pm2.trade_date) FROM plate_memberships pm2
                   WHERE pm2.stock_id=pm.stock_id AND pm2.trade_date<=?)
               ORDER BY plate_code""",
            (stock["id"], research_date, research_date),
        )]
        result = {
            "stock_code": code,
            "research_date": research_date,
            "selection": "latest evidence snapshot at or before research date",
            "attributes": rows,
            "plate_memberships": plate_rows,
            "missing": not rows and not plate_rows,
        }
        connection.close()
        return result

    def query_pool(
        self,
        pool_type: str,
        pool_date: str,
        record_key: str | None = None,
        input_version: str | None = None,
        rule_version: str | None = None,
    ) -> dict[str, Any]:
        connection = self.connect()
        parameters: list[Any] = [pool_type, pool_date]
        current_batch = connection.execute(
            "SELECT value FROM store_meta WHERE key='current_batch_key'"
        ).fetchone()["value"]
        selected_input = input_version or current_batch
        filters = []
        if record_key:
            filters.append("e.legacy_record_key=?")
            parameters.append(record_key)
        if selected_input != "all":
            filters.append("p.input_version=?")
            parameters.append(selected_input)
        if rule_version:
            filters.append("r.version=?")
            parameters.append(rule_version)
        extra_filter = "" if not filters else " AND " + " AND ".join(filters)
        pools = [dict(item) for item in connection.execute(
            f"""SELECT p.id,p.pool_type,p.pool_date,p.coverage_status,p.source_kind,p.input_version,
                        r.version AS rule_version,
                       e.legacy_record_key AS candidate_record_key
                 FROM stock_pools p LEFT JOIN first_open_events e ON e.id=p.candidate_event_id
                 LEFT JOIN rule_sets r ON r.id=p.rule_set_id
                 WHERE p.pool_type=? AND p.pool_date=? {extra_filter} ORDER BY p.id""",
            parameters,
        )]
        for pool in pools:
            pool["members"] = [dict(item) for item in connection.execute(
                """SELECT s.code,n.name,pm.board_height,pm.member_status,pm.query_direction,ef.path AS evidence
                   FROM pool_members pm JOIN stocks s ON s.id=pm.stock_id
                   JOIN stock_current_names n ON n.stock_id=s.id
                   LEFT JOIN evidence_files ef ON ef.id=pm.evidence_file_id
                   WHERE pm.pool_id=? ORDER BY COALESCE(pm.board_height,0) DESC,s.code""",
                (pool["id"],),
            )]
        connection.close()
        return {
            "pool_type": pool_type,
            "pool_date": pool_date,
            "current_input_version": current_batch,
            "selected_input_version": selected_input,
            "selected_rule_version": rule_version,
            "pools": pools,
        }

    def query_research(self, record_key: str, plan_code: str = "formal") -> dict[str, Any]:
        connection = self.connect()
        mapping = connection.execute(
            """SELECT m.*,s.code,n.name,e.event_date,e.event_status
               FROM legacy_key_map m JOIN stocks s ON s.id=m.stock_id
               JOIN stock_current_names n ON n.stock_id=s.id
               JOIN first_open_events e ON e.id=m.first_open_event_id
               WHERE m.legacy_record_key=?""",
            (record_key,),
        ).fetchone()
        if not mapping:
            connection.close()
            raise KeyError(record_key)
        static = connection.execute(
            "SELECT * FROM current_static_research WHERE legacy_record_key=?", (record_key,)
        ).fetchone()
        dynamic = connection.execute(
            """SELECT d.* FROM current_dynamic_research d JOIN research_plans p ON p.id=d.plan_id
               WHERE d.legacy_record_key=? AND p.plan_code=?""",
            (record_key, plan_code),
        ).fetchone()
        result = {
            "identity": dict(mapping),
            "static": dict(static) if static else None,
            "dynamic": dict(dynamic) if dynamic else None,
            "static_checks": [dict(item) for item in connection.execute(
                "SELECT check_type,outcome,basis,source_json,raw_json FROM research_checks WHERE static_research_id=?",
                (static["id"] if static else -1,),
            )],
            "dynamic_checks": [dict(item) for item in connection.execute(
                "SELECT check_type,outcome,basis,source_json,raw_json FROM research_checks WHERE dynamic_research_id=?",
                (dynamic["id"] if dynamic else -1,),
            )],
        }
        connection.close()
        return result

    def query_issues(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        connection = self.connect()
        rows = [dict(item) for item in connection.execute(
            "SELECT * FROM issues ORDER BY severity,scope,object_key"
        )]
        connection.close()
        if start or end:
            rows = [row for row in rows if (not start or str(row.get("object_key") or "") >= start) and (not end or str(row.get("object_key") or "") <= end)]
        return rows

    def query_impact(self, change_object: str) -> dict[str, Any]:
        needle = str(change_object).strip()
        if not needle:
            raise ValueError("change object is required")
        like = f"%{needle}%"
        connection = self.connect()
        static_keys = {
            row["legacy_record_key"] for row in connection.execute(
                """SELECT legacy_record_key FROM current_static_research
                   WHERE legacy_record_key LIKE ? OR raw_json LIKE ? OR evidence_snapshot_json LIKE ?""",
                (like, like, like),
            )
        }
        dynamic_keys = {
            row["legacy_record_key"] for row in connection.execute(
                """SELECT legacy_record_key FROM current_dynamic_research
                   WHERE legacy_record_key LIKE ? OR raw_json LIKE ? OR evidence_snapshot_json LIKE ?""",
                (like, like, like),
            )
        }
        static_keys.update(
            row["legacy_record_key"] for row in connection.execute(
                """SELECT research.legacy_record_key FROM current_static_research research
                   JOIN rule_sets rules ON rules.id=research.rule_set_id WHERE rules.version=?""",
                (needle,),
            )
        )
        dynamic_keys.update(
            row["legacy_record_key"] for row in connection.execute(
                """SELECT research.legacy_record_key FROM current_dynamic_research research
                   JOIN rule_sets rules ON rules.id=research.rule_set_id WHERE rules.version=?""",
                (needle,),
            )
        )
        stock = connection.execute("SELECT id FROM stocks WHERE code=?", (needle,)).fetchone()
        if stock:
            static_keys.update(
                row["legacy_record_key"] for row in connection.execute(
                    "SELECT legacy_record_key FROM launch_rounds WHERE stock_id=?", (stock["id"],)
                )
            )
            dynamic_keys.update(
                row["legacy_record_key"] for row in connection.execute(
                    """SELECT d.legacy_record_key FROM current_dynamic_research d
                       JOIN first_open_events e ON e.id=d.first_open_event_id
                       JOIN launch_rounds l ON l.id=e.launch_round_id WHERE l.stock_id=?""",
                    (stock["id"],),
                )
            )
        issues = [dict(row) for row in connection.execute(
            "SELECT * FROM issues WHERE object_key LIKE ? OR detail LIKE ? OR impact LIKE ? ORDER BY severity,scope",
            (like, like, like),
        )]
        source_records = [dict(row) for row in connection.execute(
            """SELECT source_kind,source_path,section,record_key,effective_date
               FROM source_records WHERE record_key LIKE ? OR raw_json LIKE ? ORDER BY source_kind,record_key LIMIT 500""",
            (like, like),
        )]
        connection.close()
        return {
            "change_object": needle,
            "static_record_keys": sorted(static_keys),
            "dynamic_record_keys": sorted(dynamic_keys),
            "issues": issues,
            "source_records": source_records,
            "counts": {
                "static_records": len(static_keys),
                "dynamic_records": len(dynamic_keys),
                "issues": len(issues),
                "source_records": len(source_records),
            },
        }

    def current_rules(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for kind in ("static", "dynamic"):
            path = self.root / f"data/store/rules/{kind}_rules.json"
            result[kind] = {"source": path.relative_to(self.root).as_posix(),
                            "sections": json.loads(path.read_text(encoding="utf-8"))["rules"]}
        result["workflow"] = {"source": "AGENTS.md", "sections": {"workflow": (self.root / "AGENTS.md").read_text(encoding="utf-8")}}
        return result

    def write_research(self, request: dict[str, Any], connection=None) -> dict[str, Any]:
        if connection is not None:
            return self._write_research(request, connection)
        owned = self.connect()
        try:
            self.apply_migrations(owned)
            with self.immediate(owned):
                return self._write_research(request, owned)
        finally:
            owned.close()

    def _write_research(self, request: dict[str, Any], connection) -> dict[str, Any]:
        request_id = str(request.get("request_id") or "")
        record_key = str(request.get("record_key") or "")
        kind = str(request.get("kind") or "")
        rule_version = str(request.get("rule_version") or "") or None
        plan_code = str(request.get("plan_code") or "formal")
        expected_value = request.get("expected_version")
        expected_version = int(expected_value) if expected_value is not None else None
        if not request_id or not record_key or kind not in {"static", "dynamic"}:
            raise ValueError("request_id, record_key and kind=static|dynamic are required")
        request_hash = canonical_hash(request)
        existing = connection.execute("SELECT * FROM write_requests WHERE request_id=?", (request_id,)).fetchone()
        if existing:
            if existing["request_sha256"] != request_hash:
                raise RuntimeError("request_id already used with different content")
        table = "static_research" if kind == "static" else "dynamic_research"
        if rule_version:
            rule = connection.execute(
                "SELECT id,version FROM rule_sets WHERE rule_type=? AND version=? AND status='current'",
                (kind, rule_version),
            ).fetchone()
        else:
            rule = connection.execute(
                "SELECT id,version FROM rule_sets WHERE rule_type=? AND status='current' ORDER BY id DESC LIMIT 1",
                (kind,),
            ).fetchone()
        if not rule:
            raise RuntimeError(f"current rule source is missing for {kind}")
        if kind == "static":
            current = connection.execute(
                "SELECT * FROM static_research WHERE legacy_record_key=? AND is_current=1",
                (record_key,),
            ).fetchone()
        else:
            current = connection.execute(
                """SELECT d.* FROM dynamic_research d JOIN research_plans p ON p.id=d.plan_id
                   WHERE d.legacy_record_key=? AND d.is_current=1 AND p.plan_code=?
                   ORDER BY d.version DESC LIMIT 1""",
                (record_key, plan_code),
            ).fetchone()
        create_dynamic = kind == "dynamic" and current is None
        if (existing and current and json.loads(existing["result_json"]).get("version") == current["version"]
                and int(current["rule_set_id"]) == int(rule["id"])):
            result = json.loads(existing["result_json"])
            result["deduplicated"] = True
            return result
        if current is None and not create_dynamic:
            raise KeyError(record_key)
        if create_dynamic:
            if expected_version not in {None, 0}:
                raise RuntimeError(f"version conflict: expected {expected_version}, current 0")
            mapping = connection.execute(
                "SELECT * FROM legacy_key_map WHERE legacy_record_key=?",
                (record_key,),
            ).fetchone()
            plan = connection.execute(
                """SELECT * FROM research_plans
                   WHERE plan_code=? AND status='current'
                   ORDER BY version DESC LIMIT 1""",
                (plan_code,),
            ).fetchone()
            static_seed = connection.execute(
                """SELECT raw_json,evidence_snapshot_json FROM static_research
                   WHERE legacy_record_key=? AND is_current=1""",
                (record_key,),
            ).fetchone()
            if not mapping or not plan or not static_seed:
                raise KeyError(record_key)
            current = {
                "first_open_event_id": mapping["first_open_event_id"],
                "plan_id": plan["id"],
                "legacy_record_key": record_key,
                "version": 0,
                "is_current": 0,
                "research_status": "unresearched",
                "confirmation_status": "source_not_labeled",
                "auction_result": None,
                "auction_pct_micros": None,
                "pk_result": None,
                "buy_result": None,
                "buy_type": None,
                "buy_time": None,
                "buy_price_milli": None,
                "sell_time": None,
                "sell_price_milli": None,
                "return_pct_micros": None,
                "source_record_id": mapping["static_source_record_id"],
                "evidence_snapshot_json": static_seed["evidence_snapshot_json"],
                "raw_json": json_text({"底稿记录键": record_key}),
                "rule_set_id": rule["id"],
            }
        elif expected_version is not None and int(current["version"]) != expected_version:
            raise RuntimeError(f"version conflict: expected {expected_version}, current {current['version']}")
        updates = request.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("updates must be an object")
        remove_fields = request.get("remove_fields", [])
        if not isinstance(remove_fields, list) or any(not isinstance(key, str) for key in remove_fields):
            raise ValueError("remove_fields must be a string array")
        checks = request.get("checks")
        if checks is not None and not isinstance(checks, list):
            raise ValueError("checks must be an array when provided")
        evidence = request.get("evidence")
        if evidence is not None and not isinstance(evidence, list):
            raise ValueError("evidence must be an array when provided")
        raw = json.loads(current["raw_json"])
        replace_dynamic = kind == "dynamic" and request.get("replace") is True
        if (not create_dynamic and all(raw.get(key) == value for key, value in updates.items())
                and all(key not in raw for key in remove_fields)
                and (evidence is None or json.loads(current["evidence_snapshot_json"]) == evidence)
                and int(current["rule_set_id"]) == int(rule["id"])
                and current["research_status"] == request.get("research_status", "formal_research")
                and current["confirmation_status"] == request.get("confirmation_status", "pending_user_confirmation")):
            saved_checks = [dict(row) for row in connection.execute(
                "SELECT check_type,subject_stock_id,outcome,basis,source_json,raw_json FROM research_checks WHERE "
                + ("static_research_id" if kind == "static" else "dynamic_research_id") + "=? ORDER BY id", (current["id"],)
            )]
            desired_checks = [{"check_type": item["check_type"], "outcome": item.get("outcome"),
                               "subject_stock_id": item.get("subject_stock_id"),
                               "basis": item.get("basis"), "source_json": json_text(item.get("sources", [])),
                               "raw_json": json_text(item.get("raw", item))} for item in checks or []]
            if any(item.get("subject_code") for item in checks or []):
                desired_checks = []  # Resolve code-based subject changes through the normal write path.
            if checks is None or saved_checks == desired_checks:
                return {"record_key": record_key, "kind": kind, "version": current["version"], "deduplicated": True}
        trade_fields = ("唯一主炒作属性", "补涨判断", "压制判断", "公告污染", "公告真实属性", "首开日期",
                        "首开潜在竞争对手事实清单", "开盘啦完整属性集")
        changed_trade_inputs = kind == "static" and any(
            (key in updates and raw.get(key) != updates[key]) or (key in remove_fields and key in raw)
            for key in trade_fields
        )
        if replace_dynamic:
            raw = {"底稿记录键": record_key}
        for key, value in updates.items():
            raw[key] = value
        for key in remove_fields:
            raw.pop(key, None)
        new_version = int(current["version"]) + 1
        with nullcontext():
            if not create_dynamic:
                connection.execute(f"UPDATE {table} SET is_current=0 WHERE id=?", (current["id"],))
            columns = [key for key in current.keys() if key != "id"]
            values = {key: current[key] for key in columns}
            if replace_dynamic:
                for name in ('auction_result','auction_pct_micros','pk_result','buy_result','buy_type','buy_time',
                             'buy_price_milli','sell_time','sell_price_milli','return_pct_micros'):
                    values[name] = None
            values["version"] = new_version
            values["is_current"] = 1
            values["research_status"] = request.get("research_status", "formal_research")
            values["raw_json"] = json_text(raw)
            if evidence is not None:
                values["evidence_snapshot_json"] = json_text(evidence)
            values["confirmation_status"] = request.get("confirmation_status", "pending_user_confirmation")
            values["rule_set_id"] = int(rule["id"])
            if kind == "static":
                column_map = {
                    "唯一主炒作属性": "main_theme",
                    "补涨判断": "replenishment_result",
                    "压制判断": "suppression_result",
                    "压制依据": "suppression_basis",
                    "公告污染": "announcement_pollution",
                    "映射依据": "mapping_basis",
                    "公告污染依据": "announcement_basis",
                }
                for key, column in column_map.items():
                    if key in updates:
                        values[column] = int(updates[key]) if key == "公告污染" and isinstance(updates[key], bool) else updates[key]
            else:
                auction_update = updates.get("竞价筛选") if isinstance(updates.get("竞价筛选"), dict) else None
                buy_update = updates.get("首开买点") if isinstance(updates.get("首开买点"), dict) else None
                outcome_update = updates.get("买入后结果") if isinstance(updates.get("买入后结果"), dict) else None
                market_update = updates.get("首开行情") if isinstance(updates.get("首开行情"), dict) else None
                if auction_update is not None:
                    values["auction_result"] = auction_update.get("结果")
                    values["auction_pct_micros"] = pct_micros(
                        auction_update.get("开盘涨幅百分比", auction_update.get("竞价涨幅"))
                    )
                if "同题材PK结果" in updates:
                    values["pk_result"] = updates["同题材PK结果"]
                if buy_update is not None:
                    values["buy_result"] = buy_update.get("结果")
                    values["buy_type"] = buy_update.get("买点类型")
                    values["buy_time"] = buy_update.get("买点时间")
                if outcome_update is not None:
                    if outcome_update.get("是否买入") is False and "买入价格" not in outcome_update:
                        values["buy_price_milli"] = None
                    else:
                        values["buy_price_milli"] = price_milli(
                            outcome_update.get("买入价格", ((market_update or {}).get("event") or {}).get("limit_up"))
                        ) or values["buy_price_milli"]
                    values["sell_time"] = outcome_update.get(
                        "尾盘卖出日期", outcome_update.get("卖出日期", outcome_update.get("卖出时间"))
                    )
                    values["sell_price_milli"] = price_milli(
                        outcome_update.get("尾盘卖出价格", outcome_update.get("卖出价格"))
                    )
                    values["return_pct_micros"] = pct_micros(
                        outcome_update.get("尾盘卖出收益率", outcome_update.get("收益率", outcome_update.get("收益率百分比")))
                    )
            placeholders = ",".join("?" for _ in columns)
            cursor = connection.execute(
                f"INSERT INTO {table}({','.join(columns)}) VALUES({placeholders})",
                [values[column] for column in columns],
            )
            check_rows = checks
            if check_rows is None and not create_dynamic:
                foreign_key = "static_research_id" if kind == "static" else "dynamic_research_id"
                check_rows = [
                    {
                        "check_type": row["check_type"],
                        "subject_stock_id": row["subject_stock_id"],
                        "outcome": row["outcome"],
                        "basis": row["basis"],
                        "sources": json.loads(row["source_json"]),
                        "raw": json.loads(row["raw_json"]),
                    }
                    for row in connection.execute(
                        f"SELECT * FROM research_checks WHERE {foreign_key}=? ORDER BY id",
                        (current["id"],),
                    )
                ]
            for check in check_rows or []:
                if not isinstance(check, dict) or not check.get("check_type"):
                    raise ValueError("each check must be an object with check_type")
                subject_id = check.get("subject_stock_id")
                if subject_id is None and check.get("subject_code"):
                    subject = connection.execute(
                        "SELECT id FROM stocks WHERE code=?",
                        (valid_code(check["subject_code"]),),
                    ).fetchone()
                    if not subject:
                        raise ValueError(f"unknown check subject: {check['subject_code']}")
                    subject_id = subject["id"]
                connection.execute(
                    """INSERT INTO research_checks
                       (static_research_id,dynamic_research_id,check_type,subject_stock_id,outcome,basis,source_json,raw_json)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (
                        cursor.lastrowid if kind == "static" else None,
                        cursor.lastrowid if kind == "dynamic" else None,
                        check["check_type"],
                        subject_id,
                        check.get("outcome"),
                        check.get("basis"),
                        json_text(check.get("sources", [])),
                        json_text(check.get("raw", check)),
                    ),
                )
            if kind == "dynamic":
                old_outcome = connection.execute(
                    "SELECT raw_json FROM trade_outcomes WHERE dynamic_research_id=?", (current["id"],)
                ).fetchone() if not create_dynamic else None
                outcome_raw = json.loads(old_outcome["raw_json"]) if old_outcome and not replace_dynamic else {}
                if isinstance(updates.get("买入后结果"), dict):
                    outcome_raw.update(updates["买入后结果"])
                connection.execute(
                    """INSERT INTO trade_outcomes
                       (dynamic_research_id,bought,buy_day_sealed,next_day_board,next_day_low_open,next_day_limit_down,
                        consecutive_boards,sell_date,return_pct_micros,raw_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        cursor.lastrowid,
                        int(outcome_raw["是否买入"]) if isinstance(outcome_raw.get("是否买入"), bool) else None,
                        int(outcome_raw["买入日最终封板"]) if isinstance(outcome_raw.get("买入日最终封板"), bool) else None,
                        int(outcome_raw["次日最终连板"]) if isinstance(outcome_raw.get("次日最终连板"), bool) else None,
                        int(outcome_raw["次日低开"]) if isinstance(outcome_raw.get("次日低开"), bool) else None,
                        int(outcome_raw["次日最终跌停"]) if isinstance(outcome_raw.get("次日最终跌停"), bool) else None,
                        outcome_raw.get("买入后连续封板天数"),
                        outcome_raw.get("尾盘卖出日期") or outcome_raw.get("卖出日期") or outcome_raw.get("卖出时间"),
                        pct_micros(outcome_raw.get("尾盘卖出收益率", outcome_raw.get("收益率", outcome_raw.get("收益率百分比")))),
                        json_text(outcome_raw),
                    ),
                )
            if changed_trade_inputs:
                # Only changed trade inputs invalidate its dependent decision.
                trade_ids = "SELECT id FROM dynamic_research WHERE legacy_record_key=?"
                connection.execute(f"DELETE FROM research_checks WHERE dynamic_research_id IN ({trade_ids})", (record_key,))
                connection.execute(f"DELETE FROM trade_outcomes WHERE dynamic_research_id IN ({trade_ids})", (record_key,))
                connection.execute("DELETE FROM dynamic_research WHERE legacy_record_key=?", (record_key,))
            self.discard_obsolete_research(connection)
            connection.execute("DELETE FROM write_requests WHERE object_type=? AND object_key=?", (kind, record_key))
            result = {
                "record_key": record_key,
                "kind": kind,
                "version": new_version,
                "plan_code": plan_code if kind == "dynamic" else None,
                "affected_exports": [STATIC_FILE if kind == "static" else DYNAMIC_FILE],
            }
            connection.execute(
                "INSERT OR REPLACE INTO write_requests(request_id,object_type,object_key,request_sha256,result_json,created_at) VALUES(?,?,?,?,?,?)",
                (request_id, kind, record_key, request_hash, json_text(result), now_text()),
            )
        return result

    def export_snapshot_hash(self, connection: sqlite3.Connection) -> str:
        """Hash display inputs only; full-store hashing belongs to backup/verification."""
        digest = hashlib.sha256()
        for table in ("current_static_research", "current_dynamic_research", "stock_current_names",
                      "first_open_events", "launch_rounds", "research_plans", "rule_sets", "trade_outcomes"):
            digest.update(table.encode("ascii"))
            for row in connection.execute(f"SELECT * FROM {table} ORDER BY 1"):
                digest.update(json_text(list(row)).encode("utf-8"))
        return digest.hexdigest()

    def export_all(self, output_root: Path | None = None, publish_root: bool = False) -> dict[str, Any]:
        self.sync_rules()
        connection = self.connect()
        batch_key = connection.execute(
            "SELECT value FROM store_meta WHERE key='current_batch_key'"
        ).fetchone()["value"]
        snapshot = self.export_snapshot_hash(connection)
        generation_key = f"{datetime.now(SHANGHAI).strftime('%Y%m%d-%H%M%S-%f')}-{snapshot[:10]}"
        base = output_root or self.root / "data/store/exports"
        output_dir = base / generation_key
        output_dir.mkdir(parents=True, exist_ok=False)
        static_rows = []
        for row in connection.execute(
            """SELECT r.legacy_record_key,s.code,n.name,l.first_board_date,l.focus_date,e.event_date,
                      r.main_theme,r.replenishment_result,r.suppression_result,r.announcement_pollution,
                      r.research_status,r.confirmation_status,r.raw_json
               FROM current_static_research r
               JOIN first_open_events e ON e.id=r.first_open_event_id
               JOIN launch_rounds l ON l.id=e.launch_round_id
               JOIN stocks s ON s.id=l.stock_id
               JOIN stock_current_names n ON n.stock_id=s.id
               ORDER BY l.focus_date DESC,s.code"""
        ):
            static_raw = json.loads(row["raw_json"])
            static_rows.append({
                "记录键": row["legacy_record_key"],
                "股票代码": row["code"],
                "股票名称": row["name"],
                "首板日": row["first_board_date"],
                "一字段": row["focus_date"],
                "首开日": row["event_date"],
                "唯一主炒": row["main_theme"],
                "补涨题材日期": static_raw.get("补涨题材日期"),
                "出生当日补涨题材": static_raw.get("出生当日补涨题材"),
                "补涨判断": row["replenishment_result"],
                "压制判断": row["suppression_result"],
                "公告污染": None if row["announcement_pollution"] is None else bool(row["announcement_pollution"]),
                "研究状态": row["research_status"],
                "确认状态": row["confirmation_status"],
                "静态筛选结论": static_raw.get("静态筛选结论"),
                "潜在竞争对手": static_raw.get("首开潜在竞争对手事实清单"),
                "待补齐": static_raw.get("自动推导缺项"),
            })
        dynamic_rows = []
        for row in connection.execute(
            """SELECT d.legacy_record_key,s.code,n.name,e.event_date,p.plan_code,p.name AS plan_name,
                      d.auction_result,d.pk_result,d.buy_result,d.buy_type,d.buy_time,d.buy_price_milli,
                      d.sell_time,d.sell_price_milli,d.return_pct_micros,d.research_status,d.confirmation_status
               FROM current_dynamic_research d JOIN research_plans p ON p.id=d.plan_id
               JOIN first_open_events e ON e.id=d.first_open_event_id
               JOIN launch_rounds l ON l.id=e.launch_round_id
               JOIN stocks s ON s.id=l.stock_id JOIN stock_current_names n ON n.stock_id=s.id
               ORDER BY COALESCE(e.event_date,l.focus_date) DESC,s.code,p.plan_code"""
        ):
            dynamic_rows.append({
                "记录键": row["legacy_record_key"],
                "股票代码": row["code"],
                "股票名称": row["name"],
                "首开日": row["event_date"],
                "方案": row["plan_name"],
                "竞价结果": row["auction_result"],
                "卡位结果": row["pk_result"],
                "买点结果": row["buy_result"],
                "买点类型": row["buy_type"],
                "买点时间": row["buy_time"],
                "买入价格": None if row["buy_price_milli"] is None else row["buy_price_milli"] / 1000,
                "卖点时间": row["sell_time"],
                "卖出价格": None if row["sell_price_milli"] is None else row["sell_price_milli"] / 1000,
                "盈亏百分比": None if row["return_pct_micros"] is None else row["return_pct_micros"] / 1_000_000,
                "研究状态": row["research_status"],
                "确认状态": row["confirmation_status"],
            })
        calculated = self._calculate_statistics(connection)
        metadata = {
            "generation_key": generation_key,
            "generated_at": now_text(),
            "database_snapshot": snapshot,
            "snapshot_scope": "display_inputs",
            "statistics_refreshed": True,
            "input_batch_key": batch_key,
            "rule_versions": {
                row["rule_type"]: row["version"]
                for row in connection.execute("SELECT rule_type,version FROM rule_sets WHERE status='current'")
            },
        }
        static_document = {"生成信息": metadata, "记录数": len(static_rows), "一字首开股票与数据": static_rows}
        dynamic_document = {"生成信息": metadata, "记录数": len(dynamic_rows), "买卖研究记录": dynamic_rows}
        statistics_document = {"生成信息": metadata, "当前研究统计": calculated}
        files: list[Path] = []
        for filename, value in (
            (STATIC_FILE, static_document),
            (DYNAMIC_FILE, dynamic_document),
            ("研究统计.json", statistics_document),
        ):
            path = output_dir / filename
            path.write_text(json_text(value, pretty=True) + "\n", encoding="utf-8")
            files.append(path)
        self._write_csv(output_dir / "一字首开研究总表.csv", static_rows)
        self._write_csv(output_dir / "一字首开买卖研究表.csv", dynamic_rows)
        files.extend([output_dir / "一字首开研究总表.csv", output_dir / "一字首开买卖研究表.csv"])
        manifest = {
            **metadata,
            "files": [
                {"name": path.name, "size": path.stat().st_size, "sha256": sha256_file(path)}
                for path in files
            ],
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json_text(manifest, pretty=True) + "\n", encoding="utf-8")
        connection.execute(
            """INSERT INTO generation_batches
               (generation_key,created_at,database_sha256,input_batch_key,rule_versions_json,output_dir,manifest_json)
               VALUES(?,?,?,?,?,?,?)""",
            (
                generation_key,
                metadata["generated_at"],
                snapshot,
                batch_key,
                json_text(metadata["rule_versions"]),
                output_dir.relative_to(self.root).as_posix(),
                json_text(manifest),
            ),
        )
        generation_id = connection.execute(
            "SELECT id FROM generation_batches WHERE generation_key=?", (generation_key,)
        ).fetchone()["id"]
        connection.execute("DELETE FROM statistics")
        for plan_result in calculated["formal_plans"]:
            plan_id = plan_result["plan"]["id"]
            for key, value in plan_result.get("metrics", {}).items():
                connection.execute(
                    """INSERT INTO statistics(generation_id,plan_id,metric_key,metric_value,numerator,denominator,raw_json)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        generation_id,
                        plan_id,
                        key,
                        str(value.get("percent")) if isinstance(value, dict) and value.get("percent") is not None else None,
                        value.get("numerator") if isinstance(value, dict) else None,
                        value.get("denominator") if isinstance(value, dict) else None,
                        json_text(value),
                    ),
                )
        connection.commit()
        connection.close()
        if publish_root:
            for name in (STATIC_FILE, DYNAMIC_FILE):
                source = output_dir / name
                temp = self.root / f".{name}.new"
                shutil.copy2(source, temp)
                os.replace(temp, self.root / name)
            current = base / "current.json"
            temp_current = base / ".current.json.new"
            temp_current.write_text(json_text({"generation_key": generation_key, "manifest": manifest_path.relative_to(self.root).as_posix()}, pretty=True) + "\n", encoding="utf-8")
            os.replace(temp_current, current)
        removed_exports = self._prune_exports(base,output_dir) if publish_root else 0
        if publish_root or self.db_path != self.root / "data/store/research.sqlite":
            connection = self.connect()
            try:
                connection.execute("DELETE FROM store_meta WHERE key='static_export_pending'")
                connection.execute("DELETE FROM store_meta WHERE key='statistics_export_pending'")
                connection.commit()
            finally:
                connection.close()
        return {"generation_key": generation_key, "output_dir": str(output_dir), "manifest": manifest,
                "published": publish_root,"removed_exports":removed_exports}

    def publish_pending(self, output_root=None, publish_root=True):
        self.sync_rules()
        connection = self.connect()
        try:
            pending = {r["key"] for r in connection.execute("SELECT key FROM store_meta WHERE value='1' AND key IN ('static_export_pending','statistics_export_pending')")}
        finally:
            connection.close()
        if not pending:
            return None
        return self.export_all(output_root,publish_root=publish_root and self.db_path==self.root / "data/store/research.sqlite")

    @staticmethod
    def _prune_exports(base: Path, current: Path) -> int:
        allowed = {STATIC_FILE,DYNAMIC_FILE,"研究统计.json","一字首开研究总表.csv","一字首开买卖研究表.csv","manifest.json"}
        removed = 0
        for directory in base.iterdir():
            if directory == current or not directory.is_dir() or directory.is_symlink():
                continue
            if not re.fullmatch(r"\d{8}-\d{6}(?:-\d{6})?-[a-f0-9]{10}",directory.name):
                continue
            if directory.resolve().parent != base.resolve():
                continue
            files = list(directory.iterdir())
            if any(not p.is_file() or p.is_symlink() or p.name not in allowed for p in files):
                continue
            for path in files:
                path.unlink()
            directory.rmdir()
            removed += 1
        return removed

    @staticmethod
    def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            if not rows:
                handle.write("")
                return
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    @staticmethod
    def _calculate_statistics(connection: sqlite3.Connection) -> dict[str, Any]:
        return build_statistics_report(connection)

    def maintain_daily(self, keep_backups: int = 0) -> dict[str, Any]:
        if keep_backups < 0:
            raise ValueError("keep_backups must be nonnegative")
        timestamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S-%f")
        report_dir = self.root / "data/store/maintenance/current"
        report_dir.mkdir(parents=True, exist_ok=True)
        from .intake import ingest_paths
        ingestion = ingest_paths(self)
        self.sync_rules()
        connection = self.connect()
        verification_started = time.perf_counter()
        foreign_key_errors = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        verification = {
            "passed": foreign_key_errors == 0 and not ingestion["errors"],
            "foreign_key_errors": foreign_key_errors,
            "elapsed_seconds": round(time.perf_counter() - verification_started, 3),
        }
        if not verification["passed"]:
            connection.close()
            (report_dir / "maintenance_report.json").write_text(json_text({"ingestion": ingestion, "verification": verification}, pretty=True) + "\n", encoding="utf-8")
            raise RuntimeError(f"daily database check failed: {report_dir}")
        snapshot = self.export_snapshot_hash(connection)
        pending=bool(connection.execute("SELECT 1 FROM store_meta WHERE key IN ('static_export_pending','statistics_export_pending') AND value='1'").fetchone())
        connection.close()
        current_pointer = self.root / "data/store/exports/current.json"
        current_manifest = None
        if current_pointer.exists():
            pointer = json.loads(current_pointer.read_text(encoding="utf-8"))
            manifest_path = self.root / pointer["manifest"]
            if manifest_path.exists():
                current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed = pending or current_manifest is None or current_manifest.get("database_snapshot") != snapshot
        export = self.export_all(publish_root=True) if changed else {
            "generation_key": current_manifest["generation_key"],
            "manifest": current_manifest,
            "published": True,
            "reused_current_generation": True,
        }
        backup = None
        removed_backups: list[str] = []
        pending_backup_cleanup = []
        if keep_backups and (changed or ingestion["updated"]):
            backup_root = (self.root / "data/store/recovery/daily").resolve()
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_root.relative_to((self.root / "data/store/recovery").resolve())
            backup_dir = backup_root / f"daily-{timestamp}"
            backup = self.create_restore_point(backup_dir)
            daily_dirs = sorted(
                path for path in backup_root.glob("daily-20*") if path.is_dir() and path.parent.resolve() == backup_root
            )
            for old in daily_dirs[:-keep_backups]:
                try:
                    self._remove_daily_backup(old)
                    removed_backups.append(old.relative_to(self.root).as_posix())
                except (OSError,ValueError,KeyError) as exc:
                    pending_backup_cleanup.append({"path":str(old),"reason":str(exc)})
        latest_raw_dates = sorted(
            path.name for path in (self.root / "data/kaipanla/raw").glob("20??-??-??") if path.is_dir()
        )
        report = {
            "performed_at": now_text(),
            "latest_raw_trade_date": latest_raw_dates[-1] if latest_raw_dates else None,
            "raw_trade_date_directories": len(latest_raw_dates),
            "ingestion": ingestion,
            "verification": {
                "passed": verification["passed"],
                "scope": "incremental intake and foreign keys",
                "foreign_key_errors": verification["foreign_key_errors"],
                "elapsed_seconds": verification["elapsed_seconds"],
            },
            "database_changed_since_current_generation": changed,
            "export": export,
            "backup": backup,
            "removed_old_daily_backups": removed_backups,
            "pending_backup_cleanup": pending_backup_cleanup,
            "kept_daily_backups": keep_backups,
        }
        (report_dir / "maintenance_report.json").write_text(json_text(report, pretty=True) + "\n", encoding="utf-8")
        return report

    def _remove_daily_backup(self, directory):
        base = (self.root / "data/store/recovery/daily").resolve()
        if directory.is_symlink() or directory.resolve().parent!=base:
            raise ValueError("恢复点目录归属不符")
        if not any(directory.iterdir()):
            directory.rmdir()
            return
        marker = directory / "restore_manifest.json"
        manifest = json.loads(marker.read_text(encoding="utf-8"))
        files = [(self.root / manifest[k]["path"]).resolve() for k in ("database","files")]
        if any(p.parent!=directory.resolve() for p in files):
            raise ValueError("恢复点文件清单超出该目录")
        expected = set(files+[marker])
        if any(p.is_symlink() or not p.is_file() or p not in expected for p in directory.iterdir()):
            raise ValueError("恢复点目录存在未登记内容")
        for path in files+[marker]:
            path.unlink(missing_ok=True)
        directory.rmdir()

    def database_snapshot(self, destination: Path) -> dict[str, Any]:
        destination = destination.resolve()
        if destination==self.db_path:
            raise ValueError("快照目标须与正式库分开")
        destination.parent.mkdir(parents=True,exist_ok=True)
        source = self.connect()
        target = sqlite3.connect(destination)
        target.row_factory = sqlite3.Row
        try:
            source.backup(target)
            target.execute("PRAGMA journal_mode=DELETE")
            snapshot = self.logical_snapshot_hash(target)
            tables = ["stocks","stock_concepts","plate_memberships","daily_market","announcements",
                      "launch_rounds","first_open_events","current_static_research","current_dynamic_research"]
            counts = {name:target.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in tables}
            rules = {r["rule_type"]:r["source_path"] for r in target.execute("SELECT rule_type,source_path FROM rule_sets WHERE status='current'")}
        finally:
            target.close()
            source.close()
        return {"path":str(destination),"sha256":sha256_file(destination),"size_bytes":destination.stat().st_size,
                "logical_snapshot":snapshot,"tables":counts,"rules":rules}

    def create_restore_point(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S-%f")
        db_backup = output_dir / f"research-{timestamp}.sqlite"
        snapshot = self.database_snapshot(db_backup)
        archive_path = output_dir / f"cutover-files-{timestamp}.zip"
        candidates = [
            self.root / "README.md",
            self.root / "docs/GitHub与多电脑使用.md",
            self.root / "AGENTS.md",
            self.root / "docs/研究系统执行计划.md",
            self.root / "docs/研究系统使用说明.md",
            self.root / STATIC_FILE,
            self.root / DYNAMIC_FILE,
            self.root / "tools/query_iwencai.py",
            self.root / "tools/research_cli.py",
        ]
        candidates.extend((self.root / "tools").glob("*.ps1"))
        candidates.extend(
            path for path in (self.root / "tools/research").rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        )
        candidates.extend(
            path for path in (self.root / "data/store/rules").glob("*.json") if path.is_file()
        )
        old_scripts = self.root / "data/research/buy_points_2026"
        candidates.extend(path for path in old_scripts.glob("*.js") if path.is_file())
        candidates = sorted(set(path.resolve() for path in candidates if path.exists()))
        archive_entries = [
            {
                "path": path.relative_to(self.root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in candidates
        ]
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in candidates:
                archive.write(path, path.relative_to(self.root).as_posix())
        manifest = {
            "created_at": now_text(),
            "database": {
                "path": db_backup.relative_to(self.root).as_posix(),
                "sha256": snapshot["sha256"],
                "logical_snapshot": snapshot["logical_snapshot"],
            },
            "files": {
                "path": archive_path.relative_to(self.root).as_posix(),
                "sha256": sha256_file(archive_path),
                "entries": archive_entries,
            },
        }
        (output_dir / "restore_manifest.json").write_text(json_text(manifest, pretty=True) + "\n", encoding="utf-8")
        return manifest

    def restore_drill(self, backup_path: Path, report_path: Path) -> dict[str, Any]:
        manifest_path = backup_path.parent / "restore_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_database = manifest["database"]
        archive_path = self.root / manifest["files"]["path"]
        database_hash_match = sha256_file(backup_path) == expected_database["sha256"]
        archive_hash_match = archive_path.exists() and sha256_file(archive_path) == manifest["files"]["sha256"]
        archive_errors: list[str] = []
        if archive_hash_match:
            expected_entries = {item["path"]: item for item in manifest["files"].get("entries", [])}
            with zipfile.ZipFile(archive_path, "r") as archive:
                actual_names = set(archive.namelist())
                for name, expected in expected_entries.items():
                    if name not in actual_names:
                        archive_errors.append(f"missing:{name}")
                        continue
                    payload = archive.read(name)
                    if len(payload) != expected["size"] or sha256_bytes(payload) != expected["sha256"]:
                        archive_errors.append(f"checksum:{name}")
                unexpected = sorted(actual_names - set(expected_entries))
                archive_errors.extend(f"unexpected:{name}" for name in unexpected)
        with Workspace(self.root,"restore-drill") as workspace:
            target = workspace.file("restored.sqlite")
            shutil.copy2(backup_path, target)
            connection = sqlite3.connect(target)
            connection.row_factory = sqlite3.Row
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            static_count = connection.execute("SELECT COUNT(*) FROM current_static_research").fetchone()[0]
            dynamic_count = connection.execute("SELECT COUNT(*) FROM current_dynamic_research").fetchone()[0]
            restored_snapshot = self.logical_snapshot_hash(connection)
            connection.close()
        result = {
            "performed_at": now_text(),
            "backup": backup_path.relative_to(self.root).as_posix(),
            "backup_sha256": sha256_file(backup_path),
            "database_hash_match": database_hash_match,
            "logical_snapshot": restored_snapshot,
            "logical_snapshot_match": restored_snapshot == expected_database.get("logical_snapshot"),
            "files_archive": manifest["files"]["path"],
            "files_archive_hash_match": archive_hash_match,
            "files_archive_entry_count": len(manifest["files"].get("entries", [])),
            "files_archive_errors": archive_errors,
            "integrity_check": integrity,
            "foreign_key_errors": len(foreign_keys),
            "static_records": static_count,
            "dynamic_records": dynamic_count,
            "restored_copy_removed_after_validation": not workspace.cleanup_result["pending"],
        }
        result["passed"] = bool(
            integrity == "ok"
            and not foreign_keys
            and database_hash_match
            and result["logical_snapshot_match"]
            and archive_hash_match
            and not archive_errors
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json_text(result, pretty=True) + "\n", encoding="utf-8")
        return result

    def write_contract_reports(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        connection = self.connect()
        tables = [row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        dictionary = [
            "# 研究库数据字典",
            "",
            "统一约定：时区为 Asia/Shanghai；日期为 ISO `YYYY-MM-DD`；时间保留来源精度；价格以千分之一元整数保存；比例以百万分之一保存；NULL 表示源资料没有该值，显式 false 与空字符串保留在原文 JSON。",
            "",
        ]
        schema_report: dict[str, Any] = {}
        for table in tables:
            columns = [dict(row) for row in connection.execute(f"PRAGMA table_info('{table}')")]
            schema_report[table] = columns
            dictionary.extend([f"## {table}", "", "| 字段 | 类型 | 非空 | 主键 |", "| --- | --- | --- | --- |"])
            for column in columns:
                dictionary.append(f"| {column['name']} | {column['type']} | {column['notnull']} | {column['pk']} |")
            dictionary.append("")
        (output_dir / "data_dictionary.md").write_text("\n".join(dictionary) + "\n", encoding="utf-8")
        counts = {
            table: connection.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"]
            for table in tables
        }
        coverage = {
            "generated_at": now_text(),
            "table_counts": counts,
            "schema": schema_report,
            "issues": [dict(row) for row in connection.execute("SELECT * FROM issues ORDER BY severity,scope")],
        }
        (output_dir / "database_coverage.json").write_text(json_text(coverage, pretty=True) + "\n", encoding="utf-8")
        connection.close()
        return {"tables": len(tables), "counts": counts, "issues": len(coverage["issues"])}

    def verify_full(self, report_dir: Path) -> dict[str, Any]:
        from .validation import verify_store
        return verify_store(self,report_dir)
