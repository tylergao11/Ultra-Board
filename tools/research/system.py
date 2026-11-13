from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable
import zipfile

from .statistics import build_statistics_report
from .source_parsers import iter_absent_continuation_facts, iter_day_source_facts


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


def walk_fields(value: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    def visit(item: Any, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                child_path = f"{path}.{key}" if path else str(key)
                entry = result.setdefault(child_path, {"count": 0, "types": set(), "example": child})
                entry["count"] += 1
                entry["types"].add(type(child).__name__)
                visit(child, child_path)
        elif isinstance(item, list):
            item_path = path + "[]"
            entry = result.setdefault(item_path, {"count": 0, "types": set(), "example": None})
            entry["count"] += 1
            entry["types"].add("list_item")
            for child in item:
                if entry["example"] is None:
                    entry["example"] = child
                visit(child, item_path)

    visit(value, "")
    return result


def field_target(path: str, source_kind: str) -> tuple[str, str]:
    if path.endswith(("股票代码", ".股票代码", ".code")):
        return "stocks", "structured_identity"
    if any(token in path for token in ("来源", "证据", "文件")):
        return "evidence_files + source_records", "structured_reference_and_raw_archive"
    if any(token in path for token in ("判断口径", "研究口径")):
        return "rule_sets + rule_items", "versioned_rule"
    if any(token in path for token in ("完整属性", "属性集", "属性查询", "历史时点")):
        return "stock_concepts + research_checks", "structured_fact_and_raw_archive"
    if any(token in path for token in ("高标事实池", "一字压制", "竞争对手", "PK核验")):
        return "stock_pools + pool_members + research_checks", "structured_relationship_and_raw_archive"
    if any(token in path for token in ("行情", "开盘价", "收盘价", "涨停价", "触板", "回封", "封板")):
        return "daily_market + intraday_events", "structured_market_fact_and_raw_archive"
    if any(token in path for token in ("公告", "消息")):
        return "announcements + static_research", "structured_announcement_and_raw_archive"
    if any(token in path for token in ("买入", "卖出", "盈亏", "收益", "竞价", "卡位", "PK")):
        return "dynamic_research + trade_outcomes", "structured_dynamic_result_and_raw_archive"
    if any(token in path for token in ("补涨", "压制", "主炒", "映射")):
        return "static_research + research_checks", "structured_static_result_and_raw_archive"
    if any(token in path for token in ("修订", "历史", "对照", "敏感性")):
        return "revisions + archived_sections", "versioned_history_and_raw_archive"
    return ("source_records", f"full_{source_kind}_raw_archive")


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

    def resolve_source_files(self) -> tuple[Path, Path]:
        root_static = self.root / STATIC_FILE
        root_dynamic = self.root / DYNAMIC_FILE
        try:
            static_data = json.loads(root_static.read_text(encoding="utf-8"))
            dynamic_data = json.loads(root_dynamic.read_text(encoding="utf-8"))
            if "判断口径" in static_data and "判断口径" in dynamic_data:
                return root_static, root_dynamic
        except Exception:
            pass
        baseline_root = self.root / "data/store/migrations/baseline-20261112-initial"
        return baseline_root / STATIC_FILE, baseline_root / DYNAMIC_FILE

    def create_baseline(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        important = [
            self.root / "AGENTS.md",
            self.root / "docs/研究系统执行计划.md",
            self.root / STATIC_FILE,
            self.root / DYNAMIC_FILE,
        ]
        entries = []
        for path in important:
            if not path.exists():
                raise FileNotFoundError(path)
            destination = output_dir / path.name
            if not destination.exists():
                shutil.copy2(path, destination)
            source_hash = sha256_file(path)
            backup_hash = sha256_file(destination)
            entries.append({
                "path": path.relative_to(self.root).as_posix(),
                "size": path.stat().st_size,
                "sha256": source_hash,
                "backup": destination.relative_to(self.root).as_posix(),
                "backup_sha256": backup_hash,
                "recoverable": source_hash == backup_hash,
            })
        static_path, dynamic_path = important[2], important[3]
        static_data = json.loads(static_path.read_text(encoding="utf-8"))
        dynamic_data = json.loads(dynamic_path.read_text(encoding="utf-8"))
        research_root = self.root / "data/research"
        script_paths = sorted(
            path for path in research_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in {".py", ".ps1"}
            or path.is_file()
            and path.suffix.lower() == ".js"
            and path.parent == research_root / "buy_points_2026"
        )
        tool_paths = sorted(path for path in (self.root / "tools").rglob("*.py") if "__pycache__" not in path.parts)
        manifest = {
            "created_at": now_text(),
            "workspace_status": self._git_status(),
            "inputs": entries,
            "observed_counts": {
                "static_records": len(static_data.get(STATIC_SECTION, [])),
                "dynamic_records": len(dynamic_data.get(DYNAMIC_SECTION, [])),
                "announcement_records": len(static_data.get("公告记录", [])),
                "documented_candidate_count": static_data.get("资料说明", {}).get("候选数量"),
                "raw_trade_date_directories": len(list((self.root / "data/kaipanla/raw").glob("20??-??-??"))),
                "concept_snapshot_files": len(list((self.root / "data/kaipanla/concepts_current").rglob("*.json"))),
                "plate_member_files": len(list((self.root / "data/kaipanla/plate_members").rglob("*.json"))),
            },
            "existing_entrypoints": [
                {"path": path.relative_to(self.root).as_posix(), "sha256": sha256_file(path)}
                for path in script_paths + tool_paths
            ],
            "encoding": "UTF-8",
            "timezone": "Asia/Shanghai",
        }
        manifest["manifest_sha256"] = canonical_hash(manifest)
        (output_dir / "baseline_manifest.json").write_text(json_text(manifest, pretty=True) + "\n", encoding="utf-8")
        report = [
            "# 迁移基线",
            "",
            f"- 冻结时间：{manifest['created_at']}",
            f"- 静态记录：{manifest['observed_counts']['static_records']}",
            f"- 动态记录：{manifest['observed_counts']['dynamic_records']}",
            f"- 公告记录：{manifest['observed_counts']['announcement_records']}",
            f"- 资料说明候选数：{manifest['observed_counts']['documented_candidate_count']}（与实际记录差额 {manifest['observed_counts']['static_records'] - int(manifest['observed_counts']['documented_candidate_count'] or 0)}）",
            f"- 原始交易日目录：{manifest['observed_counts']['raw_trade_date_directories']}",
            f"- 属性快照文件：{manifest['observed_counts']['concept_snapshot_files']}",
            f"- 板块成员文件：{manifest['observed_counts']['plate_member_files']}",
            f"- 工作区状态：`{manifest['workspace_status'].strip()}`",
            "- 四个关键源文件及恢复副本均按 SHA-256 核验。",
        ]
        (output_dir / "baseline_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
        (output_dir / "entrypoints.json").write_text(json_text(manifest["existing_entrypoints"], pretty=True) + "\n", encoding="utf-8")
        return manifest

    def _git_status(self) -> str:
        import subprocess

        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return result.stdout

    def source_tree_signature(self) -> str:
        entries: list[tuple[str, int, str]] = []
        for base in (self.root / "data/kaipanla", self.root / "data/price_checks", self.root / "data/research"):
            if not base.exists():
                continue
            for path in base.rglob("*"):
                if path.is_file():
                    stat = path.stat()
                    entries.append((path.relative_to(self.root).as_posix(), stat.st_size, sha256_file(path)))
        return canonical_hash(sorted(entries))

    def ensure_rule_sources(
        self,
        static_data: dict[str, Any],
        dynamic_data: dict[str, Any],
    ) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
        rules_dir = self.root / "data/store/rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        definitions = [
            (rules_dir / "static_rules.json", "static", static_data.get("判断口径", {})),
            (rules_dir / "dynamic_rules.json", "dynamic", dynamic_data.get("判断口径", {})),
        ]
        resolved: list[tuple[Path, dict[str, Any]]] = []
        for path, rule_type, initial_rules in definitions:
            if not path.exists():
                path.write_text(json_text({
                    "rule_type": rule_type,
                    "effective_from": "2026-11-12",
                    "rules": initial_rules,
                }, pretty=True) + "\n", encoding="utf-8")
            document = json.loads(path.read_text(encoding="utf-8"))
            if document.get("rule_type") != rule_type or not isinstance(document.get("rules"), dict):
                raise ValueError(f"invalid rule source: {path.relative_to(self.root).as_posix()}")
            resolved.append((path, document))
        return resolved[0][0], resolved[1][0], resolved[0][1], resolved[1][1]

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
                   ELSE 'path absent from current workspace; retained as migration history'
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
                self.root / "data/store/migrations/reports/evidence_inventory.jsonl",
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

    def write_field_mappings(
        self,
        connection: sqlite3.Connection,
        static_data: dict[str, Any],
        dynamic_data: dict[str, Any],
        output_path: Path,
    ) -> list[dict[str, Any]]:
        mappings: list[dict[str, Any]] = []
        inputs = [
            (STATIC_FILE, STATIC_SECTION, "static", static_data),
            (DYNAMIC_FILE, DYNAMIC_SECTION, "dynamic", dynamic_data),
        ]
        for filename, section, kind, document in inputs:
            sections = [(section, document.get(section, []))]
            sections.extend((key, value) for key, value in document.items() if key != section)
            for source_section, value in sections:
                fields = walk_fields(value)
                for path, details in sorted(fields.items()):
                    target, treatment = field_target(path, kind)
                    entry = {
                        "source_file": filename,
                        "section": source_section,
                        "field_path": path,
                        "occurrences": details["count"],
                        "value_types": sorted(details["types"]),
                        "target_object": target,
                        "treatment": treatment,
                        "example": details["example"],
                    }
                    mappings.append(entry)
                    connection.execute(
                        """INSERT OR REPLACE INTO field_mappings
                           (source_file,section,field_path,occurrences,value_types,target_object,treatment,example_json)
                           VALUES(?,?,?,?,?,?,?,?)""",
                        (
                            filename,
                            source_section,
                            path,
                            details["count"],
                            json_text(sorted(details["types"])),
                            target,
                            treatment,
                            json_text(details["example"]),
                        ),
                    )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json_text(mappings, pretty=True) + "\n", encoding="utf-8")
        connection.commit()
        return mappings

    def import_rules(
        self,
        connection: sqlite3.Connection,
        static_path: Path,
        dynamic_path: Path,
        static_data: dict[str, Any],
        dynamic_data: dict[str, Any],
    ) -> dict[str, int]:
        result: dict[str, int] = {}
        static_rule_path, dynamic_rule_path, static_rule_doc, dynamic_rule_doc = self.ensure_rule_sources(
            static_data, dynamic_data
        )
        sources = [
            ("static", static_rule_path, static_rule_doc["rules"], static_rule_doc.get("effective_from")),
            ("dynamic", dynamic_rule_path, dynamic_rule_doc["rules"], dynamic_rule_doc.get("effective_from")),
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

    def add_source_record(
        self,
        connection: sqlite3.Connection,
        batch_id: int,
        source_kind: str,
        source_path: str,
        section: str,
        record_key: str,
        raw: Any,
        stock_code: str | None = None,
        effective_date: str | None = None,
    ) -> int:
        raw_value = json_text(raw)
        raw_hash = sha256_bytes(raw_value.encode("utf-8"))
        connection.execute(
            """INSERT OR IGNORE INTO source_records
               (batch_id,source_kind,source_path,section,record_key,stock_code,effective_date,raw_sha256,raw_json)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (batch_id, source_kind, source_path, section, record_key, stock_code, effective_date, raw_hash, raw_value),
        )
        return int(connection.execute(
            """SELECT id FROM source_records
               WHERE source_kind=? AND section=? AND record_key=? AND raw_sha256=?""",
            (source_kind, section, record_key, raw_hash),
        ).fetchone()["id"])

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

    def import_static_records(
        self,
        connection: sqlite3.Connection,
        batch_id: int,
        batch_key: str,
        static_path: Path,
        static_data: dict[str, Any],
        static_rule_id: int,
    ) -> dict[str, int]:
        counts = {"records": 0, "rounds": 0, "events": 0, "researched": 0, "unresearched": 0}
        connection.execute(
            """DELETE FROM announcements WHERE source_record_id IN
               (SELECT id FROM source_records WHERE source_kind='legacy_announcement')"""
        )
        for row in static_data.get(STATIC_SECTION, []):
            record_key = str(row.get("底稿记录键") or "").strip()
            code = valid_code(row.get("股票代码"))
            focus_date = str(row.get("关注日期") or "").strip()
            if not record_key or code is None or not focus_date:
                connection.execute(
                    """INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
                       VALUES(?,?,?,?,?,?)""",
                    ("static_migration", record_key or code, "identity_missing", "blocking", json_text(row), "record cannot receive event identity"),
                )
                continue
            source_id = self.add_source_record(
                connection,
                batch_id,
                "legacy_static",
                static_path.relative_to(self.root).as_posix(),
                STATIC_SECTION,
                record_key,
                row,
                code,
                focus_date,
            )
            stock_id = self.stock_id(connection, code, row.get("股票"), row.get("底稿首板日期") or focus_date, source_id)
            main_theme = row.get("唯一主炒作属性") or row.get("唯一主炒属性")
            confirmation_status = "source_not_labeled"
            connection.execute(
                """INSERT OR IGNORE INTO launch_rounds
                   (stock_id,legacy_record_key,first_board_date,focus_date,board_sequence_text,confirmed_main_theme,confirmation_status,source_record_id,raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    stock_id,
                    record_key,
                    row.get("底稿首板日期"),
                    focus_date,
                    row.get("底稿板序原文"),
                    main_theme,
                    confirmation_status,
                    source_id,
                    json_text(row),
                ),
            )
            round_id = int(connection.execute(
                "SELECT id FROM launch_rounds WHERE legacy_record_key=?", (record_key,)
            ).fetchone()["id"])
            run_start = focus_date
            run_end = str(row.get("首开日期") or focus_date)
            run_status = "first_open_recorded" if row.get("首开日期") else "first_open_missing_or_not_occurred"
            connection.execute(
                """INSERT OR IGNORE INTO one_word_runs(launch_round_id,start_date,end_date,status,raw_json)
                   VALUES(?,?,?,?,?)""",
                (round_id, run_start, run_end, run_status, json_text({"关注日期": focus_date, "首开日期": row.get("首开日期")})),
            )
            run_id = int(connection.execute(
                "SELECT id FROM one_word_runs WHERE launch_round_id=? AND start_date=? AND end_date=?",
                (round_id, run_start, run_end),
            ).fetchone()["id"])
            event_status = "occurred" if row.get("首开日期") else "missing_or_not_occurred"
            connection.execute(
                """INSERT OR IGNORE INTO first_open_events
                   (launch_round_id,one_word_run_id,event_date,event_status,legacy_record_key,raw_json)
                   VALUES(?,?,?,?,?,?)""",
                (round_id, run_id, row.get("首开日期") or None, event_status, record_key, json_text(row)),
            )
            event_id = int(connection.execute(
                "SELECT id FROM first_open_events WHERE legacy_record_key=?", (record_key,)
            ).fetchone()["id"])
            connection.execute(
                """INSERT OR REPLACE INTO legacy_key_map
                   (legacy_record_key,stock_id,launch_round_id,first_open_event_id,static_source_record_id,dynamic_source_record_id)
                   VALUES(?,?,?,?,?,COALESCE((SELECT dynamic_source_record_id FROM legacy_key_map WHERE legacy_record_key=?),NULL))""",
                (record_key, stock_id, round_id, event_id, source_id, record_key),
            )
            sources = collect_sources(row)
            research_status = "formal_source_record" if any(
                key in row for key in ("补涨判断", "压制判断", "公告污染", "唯一主炒作属性")
            ) else "unresearched"
            connection.execute(
                """INSERT OR IGNORE INTO static_research
                   (first_open_event_id,legacy_record_key,version,is_current,research_status,confirmation_status,
                    main_theme,replenishment_result,suppression_result,announcement_pollution,mapping_basis,
                    suppression_basis,announcement_basis,source_record_id,rule_set_id,evidence_snapshot_json,raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event_id,
                    record_key,
                    1,
                    1,
                    research_status,
                    confirmation_status,
                    main_theme,
                    row.get("补涨判断"),
                    row.get("压制判断"),
                    int(row["公告污染"]) if isinstance(row.get("公告污染"), bool) else None,
                    row.get("映射依据"),
                    row.get("压制判断") if row.get("压制判断") else None,
                    row.get("公告污染依据"),
                    source_id,
                    static_rule_id,
                    json_text(sources),
                    json_text(row),
                ),
            )
            static_research_id = int(connection.execute(
                "SELECT id FROM static_research WHERE legacy_record_key=? AND version=1", (record_key,)
            ).fetchone()["id"])
            connection.execute("DELETE FROM research_checks WHERE static_research_id=?", (static_research_id,))
            candidate_pool = self.get_or_create_pool(
                connection, "first_open_candidate", focus_date, static_rule_id, batch_key, "legacy_static"
            )
            self._insert_pool_member(connection, candidate_pool, stock_id, None, research_status, "candidate", row, source_id)
            high_pool = self.get_or_create_pool(
                connection,
                "frozen_high_standard",
                row.get("底稿首板日期") or focus_date,
                static_rule_id,
                batch_key,
                "legacy_static",
                event_id,
                "frozen_from_confirmed_record" if "高标事实池" in row else "source_missing",
            )
            for high in row.get("高标事实池", []) or []:
                high_code = valid_code(high.get("股票代码"))
                if high_code is None:
                    continue
                high_id = self.stock_id(connection, high_code, high.get("股票"), row.get("底稿首板日期"), source_id)
                self._insert_pool_member(
                    connection,
                    high_pool,
                    high_id,
                    high.get("连续高度") or high.get("上板前连续高度"),
                    high.get("状态"),
                    "high_to_candidate_replenishment",
                    high,
                    source_id,
                )
            competitor_values = []
            for key in ("首开潜在竞争对手事实清单", "首开潜在竞争对手", "首开潜在竞争对手分层核验"):
                value = row.get(key)
                if isinstance(value, list):
                    competitor_values.extend(value)
                elif isinstance(value, dict):
                    competitor_values.extend(value.get("同身位及更高身位全部对象", []) or [])
            if competitor_values:
                competitor_pool = self.get_or_create_pool(
                    connection,
                    "candidate_competitors",
                    row.get("首开日期") or focus_date,
                    static_rule_id,
                    batch_key,
                    "legacy_static",
                    event_id,
                )
                for item in competitor_values:
                    competitor_code = valid_code(item.get("股票代码"))
                    if competitor_code:
                        competitor_id = self.stock_id(connection, competitor_code, item.get("股票"), row.get("首开日期"), source_id)
                        self._insert_pool_member(
                            connection,
                            competitor_pool,
                            competitor_id,
                            item.get("前日身位") or item.get("前一日收盘连续高度"),
                            str(item.get("命中", item.get("具备候选主炒属性", ""))),
                            "candidate_theme_to_opponent_attributes",
                            item,
                            source_id,
                        )
            for check_key in ("高标事实池", "一字压制核验明细", "补涨逐项核验", "历史时点属性核验"):
                if check_key in row:
                    connection.execute(
                        """INSERT INTO research_checks
                           (static_research_id,check_type,outcome,basis,source_json,raw_json)
                           VALUES(?,?,?,?,?,?)""",
                        (static_research_id, check_key, None, None, json_text(collect_sources(row[check_key])), json_text(row[check_key])),
                    )
            counts["records"] += 1
            counts["rounds"] += 1
            counts["events"] += 1
            counts["researched" if research_status != "unresearched" else "unresearched"] += 1
        for index, item in enumerate(static_data.get("公告记录", []) or []):
            stock_name = item.get("股票")
            source_record_id = self.add_source_record(
                connection,
                batch_id,
                "legacy_announcement",
                static_path.relative_to(self.root).as_posix(),
                "公告记录",
                f"announcement:{index}",
                item,
                None,
                item.get("首板日期"),
            )
            related_stock = connection.execute(
                """SELECT s.id FROM stocks s JOIN stock_names sn ON sn.stock_id=s.id
                   WHERE sn.name=? ORDER BY s.id LIMIT 1""",
                (stock_name,),
            ).fetchone()
            for matter in item.get("公告事项", []) or [item]:
                connection.execute(
                    """INSERT INTO announcements
                       (stock_id,stock_name,disclosure_time,related_trade_date,title,capital_matter_type,
                        pollution_result,basis,source_record_id,raw_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (
                        related_stock["id"] if related_stock else None,
                        stock_name,
                        matter.get("日期"),
                        item.get("首板日期"),
                        matter.get("类型"),
                        matter.get("类型"),
                        1 if "污染" in str(matter.get("类型", "")) else None,
                        matter.get("依据") or json_text(matter),
                        source_record_id,
                        json_text(matter),
                    ),
                )
        connection.commit()
        return counts

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

    def import_ths_kline(self, connection: sqlite3.Connection) -> dict[str, int]:
        counts = {"files": 0, "daily_rows": 0, "parse_errors": 0}
        base = self.root / "data/research/buy_points_2026/ths_kline"
        for path in sorted(base.glob("*.js")) if base.exists() else []:
            match_code = re.match(r"(\d{6})-", path.name)
            if not match_code:
                continue
            try:
                text = path.read_text(encoding="utf-8")
                match = re.search(r'\(\{"data":"([\s\S]*?)"\}\)', text)
                if not match:
                    raise ValueError("THS data payload missing")
                code = match_code.group(1)
                stock_id = self.stock_id(connection, code)
                evidence_id = self.evidence_id(connection, path.relative_to(self.root).as_posix())
                for row in filter(None, match.group(1).split(";")):
                    values = row.split(",")
                    if len(values) < 5 or not re.fullmatch(r"20\d{6}", values[0]):
                        continue
                    date = f"{values[0][:4]}-{values[0][4:6]}-{values[0][6:8]}"
                    payload = {
                        "date": date,
                        "open": values[1],
                        "high": values[2],
                        "low": values[3],
                        "close": values[4],
                    }
                    connection.execute(
                        """INSERT OR IGNORE INTO daily_market
                           (stock_id,trade_date,source_type,price_mode,open_milli,high_milli,low_milli,close_milli,
                            evidence_file_id,raw_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?)""",
                        (
                            stock_id,
                            date,
                            "ths_kline",
                            "unadjusted",
                            price_milli(values[1]),
                            price_milli(values[2]),
                            price_milli(values[3]),
                            price_milli(values[4]),
                            evidence_id,
                            json_text(payload),
                        ),
                    )
                    connection.execute(
                        """INSERT INTO trading_days(trade_date,is_trading_day,calendar_source,raw_market_coverage,price_coverage)
                           VALUES(?,1,?,0,1)
                           ON CONFLICT(trade_date) DO UPDATE SET price_coverage=1""",
                        (date, "ths_kline"),
                    )
                    counts["daily_rows"] += 1
                counts["files"] += 1
            except Exception as exc:
                self._mark_parse_error(connection, path, exc)
                counts["parse_errors"] += 1
            if counts["files"] % 50 == 0:
                connection.commit()
        connection.commit()
        return counts

    def archive_top_sections(
        self,
        connection: sqlite3.Connection,
        source_file: str,
        document: dict[str, Any],
        record_section: str,
    ) -> int:
        count = 0
        for section, value in document.items():
            if section in {record_section, "判断口径"}:
                continue
            raw = json_text(value)
            kind = "statistics" if "统计" in section else "source_metadata"
            if "对照" in section or "假设" in section:
                kind = "comparison_study"
            connection.execute(
                """INSERT OR IGNORE INTO archived_sections
                   (source_file,section,archive_kind,raw_sha256,raw_json) VALUES(?,?,?,?,?)""",
                (source_file, section, kind, sha256_bytes(raw.encode("utf-8")), raw),
            )
            count += 1
        connection.commit()
        return count

    def import_dynamic_records(
        self,
        connection: sqlite3.Connection,
        batch_id: int,
        dynamic_path: Path,
        dynamic_data: dict[str, Any],
        dynamic_rule_id: int,
    ) -> dict[str, int]:
        plan_definition = dynamic_data.get("判断口径", {})
        connection.execute(
            """INSERT OR IGNORE INTO research_plans
               (plan_code,version,name,status,definition_json,rule_set_id) VALUES(?,?,?,?,?,?)""",
            ("formal", 1, "现行正式首开交易方案", "current", json_text(plan_definition), dynamic_rule_id),
        )
        plan_id = int(connection.execute(
            "SELECT id FROM research_plans WHERE plan_code='formal' AND version=1"
        ).fetchone()["id"])
        counts = {"records": 0, "mapped": 0, "unmapped": 0, "outcomes": 0}
        for row in dynamic_data.get(DYNAMIC_SECTION, []):
            record_key = str(row.get("底稿记录键") or "").strip()
            source_id = self.add_source_record(
                connection,
                batch_id,
                "legacy_dynamic",
                dynamic_path.relative_to(self.root).as_posix(),
                DYNAMIC_SECTION,
                record_key,
                row,
                None,
                (row.get("首开行情") or {}).get("日期") if isinstance(row.get("首开行情"), dict) else None,
            )
            mapping = connection.execute(
                "SELECT * FROM legacy_key_map WHERE legacy_record_key=?", (record_key,)
            ).fetchone()
            if not mapping:
                connection.execute(
                    """INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
                       VALUES(?,?,?,?,?,?)""",
                    ("dynamic_migration", record_key, "static_link_missing", "blocking", "dynamic record has no static key", "dynamic record retained in source_records"),
                )
                counts["unmapped"] += 1
                continue
            connection.execute(
                "UPDATE legacy_key_map SET dynamic_source_record_id=? WHERE legacy_record_key=?",
                (source_id, record_key),
            )
            auction = row.get("竞价筛选") if isinstance(row.get("竞价筛选"), dict) else {}
            buy = row.get("首开买点") if isinstance(row.get("首开买点"), dict) else {}
            market = row.get("首开行情") if isinstance(row.get("首开行情"), dict) else {}
            outcome = row.get("买入后结果") if isinstance(row.get("买入后结果"), dict) else {}
            buy_price = outcome.get("买入价格", market.get("涨停价"))
            sell_price = outcome.get("尾盘卖出价格", outcome.get("卖出价格"))
            return_pct = outcome.get("尾盘卖出收益率", outcome.get("收益率", outcome.get("收益率百分比")))
            sources = collect_sources(row)
            connection.execute(
                """INSERT OR IGNORE INTO dynamic_research
                   (first_open_event_id,plan_id,legacy_record_key,version,is_current,research_status,confirmation_status,
                    auction_result,auction_pct_micros,pk_result,buy_result,buy_type,buy_time,buy_price_milli,
                     sell_time,sell_price_milli,return_pct_micros,source_record_id,evidence_snapshot_json,raw_json,rule_set_id)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    mapping["first_open_event_id"],
                    plan_id,
                    record_key,
                    1,
                    1,
                    row.get("研究状态") or "source_record",
                    "source_not_labeled",
                    auction.get("结果"),
                    pct_micros(auction.get("开盘涨幅百分比", auction.get("竞价涨幅"))),
                    row.get("同题材PK结果"),
                    buy.get("结果"),
                    buy.get("买点类型"),
                    buy.get("买点时间"),
                    price_milli(buy_price),
                    outcome.get("尾盘卖出日期") or outcome.get("卖出日期") or outcome.get("卖出时间"),
                    price_milli(sell_price),
                    pct_micros(return_pct),
                    source_id,
                    json_text(sources),
                    json_text(row),
                    dynamic_rule_id,
                ),
            )
            dynamic_id = int(connection.execute(
                """SELECT id FROM dynamic_research
                   WHERE legacy_record_key=? AND plan_id=? AND version=1""",
                (record_key, plan_id),
            ).fetchone()["id"])
            connection.execute("DELETE FROM research_checks WHERE dynamic_research_id=?", (dynamic_id,))
            connection.execute(
                """INSERT OR REPLACE INTO trade_outcomes
                   (dynamic_research_id,bought,buy_day_sealed,next_day_board,next_day_low_open,next_day_limit_down,
                    consecutive_boards,sell_date,return_pct_micros,raw_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    dynamic_id,
                    int(outcome["是否买入"]) if isinstance(outcome.get("是否买入"), bool) else None,
                    int(outcome["买入日最终封板"]) if isinstance(outcome.get("买入日最终封板"), bool) else None,
                    int(outcome["次日最终连板"]) if isinstance(outcome.get("次日最终连板"), bool) else None,
                    int(outcome["次日低开"]) if isinstance(outcome.get("次日低开"), bool) else None,
                    int(outcome["次日最终跌停"]) if isinstance(outcome.get("次日最终跌停"), bool) else None,
                    outcome.get("买入后连续封板天数"),
                    outcome.get("尾盘卖出日期") or outcome.get("卖出日期") or outcome.get("卖出时间"),
                    pct_micros(return_pct),
                    json_text(outcome),
                ),
            )
            for pk_item in row.get("同题材PK核验明细", []) or []:
                subject_code = valid_code(pk_item.get("股票代码"))
                subject_id = self.stock_id(connection, subject_code, pk_item.get("股票"), market.get("日期"), source_id) if subject_code else None
                connection.execute(
                    """INSERT INTO research_checks
                       (dynamic_research_id,check_type,subject_stock_id,outcome,basis,source_json,raw_json)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        dynamic_id,
                        "theme_pk",
                        subject_id,
                        str(pk_item.get("命中候选主炒", "")),
                        pk_item.get("时序依据"),
                        json_text(collect_sources(pk_item)),
                        json_text(pk_item),
                    ),
                )
            counts["records"] += 1
            counts["mapped"] += 1
            counts["outcomes"] += 1
        comparison = dynamic_data.get("假设对照研究_2026取消公告与医药禁买")
        if comparison is not None:
            connection.execute(
                """INSERT OR IGNORE INTO research_plans
                   (plan_code,version,name,status,definition_json,rule_set_id) VALUES(?,?,?,?,?,?)""",
                ("hypothetical_relaxed_2026", 1, "2026取消公告与医药禁买假设对照", "archived_comparison", json_text(comparison), dynamic_rule_id),
            )
        connection.commit()
        return counts

    def sync_rules(self) -> dict[str, Any]:
        static_path, dynamic_path = self.resolve_source_files()
        static_data = json.loads(static_path.read_text(encoding="utf-8"))
        dynamic_data = json.loads(dynamic_path.read_text(encoding="utf-8"))
        connection = self.connect()
        self.apply_migrations(connection)
        try:
            self.import_rules(connection, static_path, dynamic_path, static_data, dynamic_data)
            current = {
                row["rule_type"]: {"source_path": row["source_path"]}
                for row in connection.execute(
                    "SELECT rule_type,source_path FROM rule_sets WHERE status='current' ORDER BY rule_type"
                )
            }
        finally:
            connection.close()
        return {"current": current, "synced_at": now_text()}

    def normalize_stock_name_history(self, connection: sqlite3.Connection) -> dict[str, int]:
        rows = [dict(row) for row in connection.execute(
            "SELECT id,stock_id,name,valid_from FROM stock_names ORDER BY stock_id,COALESCE(valid_from,''),id"
        )]
        groups: dict[int, list[dict[str, Any]]] = {}
        for row in rows:
            groups.setdefault(row["stock_id"], []).append(row)
        conflicts = 0
        for stock_id, names in groups.items():
            for index, row in enumerate(names):
                next_from = names[index + 1]["valid_from"] if index + 1 < len(names) else None
                connection.execute("UPDATE stock_names SET valid_to=? WHERE id=?", (next_from, row["id"]))
                if next_from and row["valid_from"] == next_from and row["name"] != names[index + 1]["name"]:
                    connection.execute(
                        """INSERT OR IGNORE INTO issues(scope,object_key,issue_kind,severity,detail,impact)
                           VALUES(?,?,?,?,?,?)""",
                        (
                            "stock_identity",
                            str(stock_id),
                            "same_date_name_conflict",
                            "data_gap",
                            f"{row['valid_from']}: {row['name']} / {names[index + 1]['name']}",
                            "name display requires source review; stock code identity remains stable",
                        ),
                    )
                    conflicts += 1
        connection.commit()
        return {"name_rows": len(rows), "stocks": len(groups), "same_date_conflicts": conflicts}

    def migrate_all(self, inventory: bool = True) -> dict[str, Any]:
        started = time.perf_counter()
        static_path, dynamic_path = self.resolve_source_files()
        static_data = json.loads(static_path.read_text(encoding="utf-8"))
        dynamic_data = json.loads(dynamic_path.read_text(encoding="utf-8"))
        static_rule_path, dynamic_rule_path, _, _ = self.ensure_rule_sources(static_data, dynamic_data)
        baseline_path = self.root / "data/store/migrations/baseline-20261112-initial/baseline_manifest.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
        input_fingerprint = canonical_hash({
            "static": sha256_file(static_path),
            "dynamic": sha256_file(dynamic_path),
            "static_rules": sha256_file(static_rule_path),
            "dynamic_rules": sha256_file(dynamic_rule_path),
            "counts": [len(static_data.get(STATIC_SECTION, [])), len(dynamic_data.get(DYNAMIC_SECTION, []))],
            "source_tree_signature": self.source_tree_signature(),
        })
        batch_key = f"full-{input_fingerprint[:16]}"
        connection = self.connect()
        migrations = self.apply_migrations(connection)
        existing = connection.execute(
            "SELECT id,status,summary_json FROM import_batches WHERE batch_key=?", (batch_key,)
        ).fetchone()
        if existing and existing["status"] == "complete":
            summary = json.loads(existing["summary_json"])
            summary["rules"] = {
                row["rule_type"]: int(row["id"])
                for row in connection.execute(
                    "SELECT id,rule_type FROM rule_sets WHERE status='current' ORDER BY rule_type"
                )
            }
            summary["reused_existing_batch"] = True
            connection.close()
            return summary
        connection.execute(
            """INSERT INTO import_batches(batch_key,kind,started_at,status,input_manifest_hash,summary_json)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(batch_key) DO UPDATE SET started_at=excluded.started_at,status='running'""",
            (batch_key, "full_migration", now_text(), "running", input_fingerprint, "{}"),
        )
        connection.commit()
        batch_id = int(connection.execute(
            "SELECT id FROM import_batches WHERE batch_key=?", (batch_key,)
        ).fetchone()["id"])
        reports = self.root / "data/store/migrations/reports"
        reports.mkdir(parents=True, exist_ok=True)
        summary: dict[str, Any] = {
            "batch_key": batch_key,
            "migrations_applied": migrations,
            "baseline_manifest": baseline.get("manifest_sha256"),
        }
        try:
            if inventory:
                summary["evidence_inventory"] = self.build_evidence_inventory(
                    connection, self.root / "data/store/migrations/reports/evidence_inventory.jsonl"
                )
            summary["field_mappings"] = len(self.write_field_mappings(
                connection,
                static_data,
                dynamic_data,
                reports / "field_mapping.json",
            ))
            rules = self.import_rules(connection, static_path, dynamic_path, static_data, dynamic_data)
            summary["rules"] = rules
            summary["static"] = self.import_static_records(
                connection, batch_id, batch_key, static_path, static_data, rules["static"]
            )
            summary["raw_market"] = self.import_raw_market(connection, rules["static"], batch_key)
            summary["market_source_facts"] = self.import_market_source_facts(
                connection, rules["static"], batch_key
            )
            summary["concepts"] = self.import_concepts(connection)
            summary["plate_members"] = self.import_plate_members(connection)
            summary["price_checks"] = self.import_price_checks(connection)
            summary["ths_kline"] = self.import_ths_kline(connection)
            summary["dynamic"] = self.import_dynamic_records(
                connection, batch_id, dynamic_path, dynamic_data, rules["dynamic"]
            )
            summary["stock_name_history"] = self.normalize_stock_name_history(connection)
            summary["archived_sections"] = (
                self.archive_top_sections(connection, STATIC_FILE, static_data, STATIC_SECTION)
                + self.archive_top_sections(connection, DYNAMIC_FILE, dynamic_data, DYNAMIC_SECTION)
            )
            summary["elapsed_seconds"] = round(time.perf_counter() - started, 3)
            summary["database_size_bytes"] = self.db_path.stat().st_size if self.db_path.exists() else 0
            connection.execute(
                """UPDATE import_batches SET completed_at=?,status='complete',summary_json=? WHERE id=?""",
                (now_text(), json_text(summary), batch_id),
            )
            connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('current_batch_key',?)", (batch_key,))
            connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('timezone','Asia/Shanghai')")
            connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('price_storage','integer_milli_yuan')")
            connection.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('null_semantics','NULL=source absent; explicit false/empty preserved in raw_json')")
            connection.commit()
        except Exception as exc:
            connection.rollback()
            connection.execute(
                "UPDATE import_batches SET completed_at=?,status='failed',summary_json=? WHERE id=?",
                (now_text(), json_text({"error": f"{type(exc).__name__}: {exc}"}), batch_id),
            )
            connection.commit()
            connection.close()
            raise
        connection.close()
        (reports / "migration_summary.json").write_text(json_text(summary, pretty=True) + "\n", encoding="utf-8")
        return summary

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

    def write_research(self, request: dict[str, Any]) -> dict[str, Any]:
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
        connection = self.connect()
        self.apply_migrations(connection)
        existing = connection.execute("SELECT * FROM write_requests WHERE request_id=?", (request_id,)).fetchone()
        if existing:
            if existing["request_sha256"] != request_hash:
                connection.close()
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
            connection.close()
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
            connection.close()
            return result
        if current is None and not create_dynamic:
            connection.close()
            raise KeyError(record_key)
        if create_dynamic:
            if expected_version not in {None, 0}:
                connection.close()
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
                connection.close()
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
                "raw_json": static_seed["raw_json"],
                "rule_set_id": rule["id"],
            }
        elif expected_version is not None and int(current["version"]) != expected_version:
            connection.close()
            raise RuntimeError(f"version conflict: expected {expected_version}, current {current['version']}")
        updates = request.get("updates")
        if not isinstance(updates, dict):
            connection.close()
            raise ValueError("updates must be an object")
        checks = request.get("checks")
        if checks is not None and not isinstance(checks, list):
            connection.close()
            raise ValueError("checks must be an array when provided")
        evidence = request.get("evidence")
        if evidence is not None and not isinstance(evidence, list):
            connection.close()
            raise ValueError("evidence must be an array when provided")
        raw = json.loads(current["raw_json"])
        if (not create_dynamic and all(raw.get(key) == value for key, value in updates.items())
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
                connection.close()
                return {"record_key": record_key, "kind": kind, "version": current["version"], "deduplicated": True}
        for key, value in updates.items():
            raw[key] = value
        new_version = int(current["version"]) + 1
        with self.immediate(connection):
            if not create_dynamic:
                connection.execute(f"UPDATE {table} SET is_current=0 WHERE id=?", (current["id"],))
            columns = [key for key in current.keys() if key != "id"]
            values = {key: current[key] for key in columns}
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
                            outcome_update.get("买入价格", (market_update or {}).get("涨停价"))
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
                outcome_raw = json.loads(old_outcome["raw_json"]) if old_outcome else {}
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
            connection.execute(
                """INSERT INTO revisions(object_type,object_key,version,change_json,confirmation_status,source_record_id,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (kind, record_key, new_version, json_text(updates), request.get("confirmation_status", "pending_user_confirmation"), current["source_record_id"], now_text()),
            )
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
        connection.close()
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

    def export_all(self, output_root: Path | None = None, publish_root: bool = False,
                   refresh_statistics: bool = True) -> dict[str, Any]:
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
                      r.research_status,r.confirmation_status
               FROM current_static_research r
               JOIN first_open_events e ON e.id=r.first_open_event_id
               JOIN launch_rounds l ON l.id=e.launch_round_id
               JOIN stocks s ON s.id=l.stock_id
               JOIN stock_current_names n ON n.stock_id=s.id
               ORDER BY l.focus_date DESC,s.code"""
        ):
            static_rows.append({
                "记录键": row["legacy_record_key"],
                "股票代码": row["code"],
                "股票名称": row["name"],
                "首板日": row["first_board_date"],
                "一字段": row["focus_date"],
                "首开日": row["event_date"],
                "唯一主炒": row["main_theme"],
                "补涨判断": row["replenishment_result"],
                "压制判断": row["suppression_result"],
                "公告污染": None if row["announcement_pollution"] is None else bool(row["announcement_pollution"]),
                "研究状态": row["research_status"],
                "确认状态": row["confirmation_status"],
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
        calculated = None
        statistics_source = None
        if refresh_statistics:
            calculated = self._calculate_statistics(connection)
        else:
            pointer_path = self.root / "data/store/exports/current.json"
            if pointer_path.exists():
                pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                previous_statistics = (self.root / pointer["manifest"]).parent / "研究统计.json"
                if previous_statistics.exists():
                    previous_document = json.loads(previous_statistics.read_text(encoding="utf-8"))
                    calculated = previous_document.get("研究库计算与存档差异")
                    statistics_source = previous_document.get("沿用统计来源") or previous_document.get("生成信息")
        metadata = {
            "generation_key": generation_key,
            "generated_at": now_text(),
            "database_snapshot": snapshot,
            "snapshot_scope": "display_inputs",
            "statistics_refreshed": refresh_statistics,
            "input_batch_key": batch_key,
            "rule_versions": {
                row["rule_type"]: row["version"]
                for row in connection.execute("SELECT rule_type,version FROM rule_sets WHERE status='current'")
            },
        }
        static_document = {"生成信息": metadata, "记录数": len(static_rows), "一字首开股票与数据": static_rows}
        dynamic_document = {"生成信息": metadata, "记录数": len(dynamic_rows), "买卖研究记录": dynamic_rows}
        statistics_document = {"生成信息": metadata, "研究库计算与存档差异": calculated}
        if not refresh_statistics:
            statistics_document["沿用统计来源"] = statistics_source
            statistics_document["说明"] = "本次仅更新静态研究；交易统计沿用既有结果，由交易研究任务更新。"
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
        for plan_result in ((calculated or {}).get("formal_plans", []) + (calculated or {}).get("comparison_plans", [])) if refresh_statistics else []:
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
        return {"generation_key": generation_key, "output_dir": str(output_dir), "manifest": manifest, "published": publish_root}

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

    def maintain_daily(self, keep_backups: int = 3) -> dict[str, Any]:
        if keep_backups < 1:
            raise ValueError("keep_backups must be at least 1")
        timestamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
        report_dir = self.root / "data/store/maintenance" / timestamp
        report_dir.mkdir(parents=True, exist_ok=False)
        from .intake import ingest_paths
        ingestion = ingest_paths(self)
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
        connection.close()
        current_pointer = self.root / "data/store/exports/current.json"
        current_manifest = None
        if current_pointer.exists():
            pointer = json.loads(current_pointer.read_text(encoding="utf-8"))
            manifest_path = self.root / pointer["manifest"]
            if manifest_path.exists():
                current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        changed = current_manifest is None or current_manifest.get("database_snapshot") != snapshot
        export = self.export_all(publish_root=True, refresh_statistics=False) if changed else {
            "generation_key": current_manifest["generation_key"],
            "manifest": current_manifest,
            "published": True,
            "reused_current_generation": True,
        }
        backup = None
        removed_backups: list[str] = []
        if changed or ingestion["updated"]:
            backup_root = (self.root / "data/store/recovery/daily").resolve()
            backup_root.mkdir(parents=True, exist_ok=True)
            backup_root.relative_to((self.root / "data/store/recovery").resolve())
            backup_dir = backup_root / f"daily-{timestamp}"
            backup = self.create_restore_point(backup_dir)
            daily_dirs = sorted(
                path for path in backup_root.glob("daily-20*") if path.is_dir() and path.parent.resolve() == backup_root
            )
            for old in daily_dirs[:-keep_backups]:
                old.resolve().relative_to(backup_root)
                shutil.rmtree(old)
                removed_backups.append(old.relative_to(self.root).as_posix())
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
            "kept_daily_backups": keep_backups,
        }
        (report_dir / "maintenance_report.json").write_text(json_text(report, pretty=True) + "\n", encoding="utf-8")
        return report

    def create_restore_point(self, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(SHANGHAI).strftime("%Y%m%d-%H%M%S")
        db_backup = output_dir / f"research-{timestamp}.sqlite"
        source = self.connect()
        logical_snapshot = self.logical_snapshot_hash(source)
        target = sqlite3.connect(db_backup)
        source.backup(target)
        target.close()
        source.close()
        archive_path = output_dir / f"cutover-files-{timestamp}.zip"
        candidates = [
            self.root / "AGENTS.md",
            self.root / "docs/研究系统执行计划.md",
            self.root / "docs/研究系统使用说明.md",
            self.root / STATIC_FILE,
            self.root / DYNAMIC_FILE,
            self.root / "tools/query_iwencai.py",
            self.root / "tools/research_cli.py",
        ]
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
                "sha256": sha256_file(db_backup),
                "logical_snapshot": logical_snapshot,
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
        with tempfile.TemporaryDirectory(prefix="ultra-board-restore-") as temp_dir:
            target = Path(temp_dir) / "restored.sqlite"
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
            "restored_copy_removed_after_validation": True,
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
        rules = self.current_rules()
        (output_dir / "rule_migration.json").write_text(json_text(rules, pretty=True) + "\n", encoding="utf-8")
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

    def verify_full(self, report_dir: Path, run_idempotence_check: bool = True) -> dict[str, Any]:
        report_dir.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        static_path, dynamic_path = self.resolve_source_files()
        static_data = json.loads(static_path.read_text(encoding="utf-8"))
        dynamic_data = json.loads(dynamic_path.read_text(encoding="utf-8"))
        static_rows = static_data.get(STATIC_SECTION, [])
        dynamic_rows = dynamic_data.get(DYNAMIC_SECTION, [])
        connection = self.connect()
        checks: dict[str, Any] = {}
        checks["integrity_check"] = connection.execute("PRAGMA integrity_check").fetchone()[0]
        checks["foreign_key_errors"] = len(connection.execute("PRAGMA foreign_key_check").fetchall())
        counts = {
            "baseline_static": len(static_rows),
            "database_static": connection.execute("SELECT COUNT(*) AS c FROM current_static_research").fetchone()["c"],
            "baseline_dynamic": len(dynamic_rows),
            "database_dynamic": connection.execute("SELECT COUNT(*) AS c FROM current_dynamic_research").fetchone()["c"],
            "legacy_keys": connection.execute("SELECT COUNT(*) AS c FROM legacy_key_map").fetchone()["c"],
            "evidence_files": connection.execute("SELECT COUNT(*) AS c FROM evidence_files").fetchone()["c"],
            "field_mappings": connection.execute("SELECT COUNT(*) AS c FROM field_mappings").fetchone()["c"],
        }
        checks["counts"] = counts
        static_differences = []
        for source in static_rows:
            key = source.get("底稿记录键")
            target = connection.execute(
                """SELECT main_theme,replenishment_result,suppression_result,announcement_pollution,raw_json
                   FROM static_research WHERE legacy_record_key=? AND version=1""",
                (key,),
            ).fetchone()
            if target is None:
                static_differences.append({"record_key": key, "kind": "missing"})
                continue
            comparisons = {
                "唯一主炒作属性": target["main_theme"],
                "补涨判断": target["replenishment_result"],
                "压制判断": target["suppression_result"],
                "公告污染": None if target["announcement_pollution"] is None else bool(target["announcement_pollution"]),
            }
            for field, target_value in comparisons.items():
                source_value = source.get(field) if field in source else None
                if source_value != target_value:
                    static_differences.append({"record_key": key, "field": field, "source": source_value, "target": target_value})
            if json.loads(target["raw_json"]) != source:
                static_differences.append({"record_key": key, "kind": "raw_json_changed"})
        dynamic_differences = []
        for source in dynamic_rows:
            key = source.get("底稿记录键")
            target = connection.execute(
                """SELECT d.raw_json FROM dynamic_research d JOIN research_plans p ON p.id=d.plan_id
                   WHERE d.legacy_record_key=? AND d.version=1 AND p.plan_code='formal'""",
                (key,),
            ).fetchone()
            if target is None:
                dynamic_differences.append({"record_key": key, "kind": "missing"})
            elif json.loads(target["raw_json"]) != source:
                dynamic_differences.append({"record_key": key, "kind": "raw_json_changed"})
        checks["static_differences"] = static_differences
        checks["dynamic_differences"] = dynamic_differences
        baseline_dynamic_keys = {row.get("底稿记录键") for row in dynamic_rows}
        dynamic_additions = []
        revision_gaps = []
        for row in connection.execute(
            """SELECT d.legacy_record_key,d.version FROM current_dynamic_research d
               JOIN research_plans p ON p.id=d.plan_id WHERE p.plan_code='formal'"""
        ):
            if row["legacy_record_key"] not in baseline_dynamic_keys:
                dynamic_additions.append({"record_key": row["legacy_record_key"], "version": row["version"]})
            if row["version"] > 1 or row["legacy_record_key"] not in baseline_dynamic_keys:
                revision = connection.execute(
                    "SELECT 1 FROM revisions WHERE object_type='dynamic' AND object_key=? AND version=?",
                    (row["legacy_record_key"], row["version"]),
                ).fetchone()
                if not revision:
                    revision_gaps.append({"kind": "dynamic", "record_key": row["legacy_record_key"], "version": row["version"]})
        for row in connection.execute("SELECT legacy_record_key,version FROM current_static_research WHERE version>1"):
            revision = connection.execute(
                "SELECT 1 FROM revisions WHERE object_type='static' AND object_key=? AND version=?",
                (row["legacy_record_key"], row["version"]),
            ).fetchone()
            if not revision:
                revision_gaps.append({"kind": "static", "record_key": row["legacy_record_key"], "version": row["version"]})
        checks["dynamic_additions"] = dynamic_additions
        checks["revision_gaps"] = revision_gaps
        duplicate_checks = {}
        for table, columns in (
            ("stocks", "code"),
            ("launch_rounds", "legacy_record_key"),
            ("first_open_events", "legacy_record_key"),
            ("legacy_key_map", "legacy_record_key"),
        ):
            duplicate_checks[table] = connection.execute(
                f"SELECT COUNT(*) AS c FROM (SELECT {columns},COUNT(*) n FROM {table} GROUP BY {columns} HAVING n>1)"
            ).fetchone()["c"]
        checks["duplicate_business_identities"] = duplicate_checks
        source_values = sorted(set(
            source for row in static_rows + dynamic_rows for source in collect_sources(row)
        ))
        local_references: list[dict[str, str]] = []
        remote_references: list[str] = []
        descriptive_references: list[str] = []
        for value in source_values:
            if value.startswith(("https://", "http://")):
                remote_references.append(value)
                continue
            path_value = value.split("（", 1)[0].strip()
            path_like = path_value.startswith(("data/", "docs/", "tools/")) or Path(path_value).suffix.lower() in {
                ".json", ".jsonl", ".csv", ".txt", ".md", ".pdf", ".html", ".htm"
            }
            if path_like:
                local_references.append({"reference": value, "path": path_value})
            else:
                descriptive_references.append(value)
        missing_references = [item for item in local_references if not (self.root / item["path"]).exists()]
        checks["source_reference_coverage"] = {
            "referenced_values": len(source_values),
            "local_references": len(local_references),
            "existing_local_paths": len(local_references) - len(missing_references),
            "remote_references": len(remote_references),
            "descriptive_references": len(descriptive_references),
            "preexisting_missing_paths": missing_references,
            "migration_created_missing_paths": [],
        }
        expected_field_paths = set()
        for filename, section, document in (
            (STATIC_FILE, STATIC_SECTION, static_data),
            (DYNAMIC_FILE, DYNAMIC_SECTION, dynamic_data),
        ):
            for source_section, value in [(section, document.get(section, []))] + [
                (key, value) for key, value in document.items() if key != section
            ]:
                expected_field_paths.update((filename, source_section, path) for path in walk_fields(value))
        actual_field_paths = set(
            (row["source_file"], row["section"], row["field_path"])
            for row in connection.execute("SELECT source_file,section,field_path FROM field_mappings")
        )
        checks["field_mapping_missing"] = [list(item) for item in sorted(expected_field_paths - actual_field_paths)]
        query_samples = self._verification_samples(connection)
        checks["real_query_samples"] = query_samples
        connection.close()
        checks["transaction_rollback"] = self._rollback_drill()
        checks["version_conflict"] = self._version_conflict_drill()
        if run_idempotence_check:
            before = self._entity_counts()
            repeated = self.migrate_all(inventory=False)
            after = self._entity_counts()
            checks["idempotence"] = {"before": before, "after": after, "stable": before == after, "batch_reused": repeated.get("reused_existing_batch", False)}
        checks["utf8_roundtrip"] = "一字首开" in json_text({"值": "一字首开"})
        checks["elapsed_seconds"] = round(time.perf_counter() - started, 3)
        checks["database_size_bytes"] = self.db_path.stat().st_size
        checks["database_sha256"] = sha256_file(self.db_path)
        checks["passed"] = (
            checks["integrity_check"] == "ok"
            and checks["foreign_key_errors"] == 0
            and counts["baseline_static"] == counts["database_static"] == counts["legacy_keys"]
            and counts["baseline_dynamic"] <= counts["database_dynamic"]
            and not static_differences
            and not dynamic_differences
            and not revision_gaps
            and not any(duplicate_checks.values())
            and not checks["field_mapping_missing"]
            and checks["transaction_rollback"]["passed"]
            and checks["version_conflict"]["passed"]
            and (not run_idempotence_check or checks["idempotence"]["stable"])
            and checks["utf8_roundtrip"]
        )
        (report_dir / "verification.json").write_text(json_text(checks, pretty=True) + "\n", encoding="utf-8")
        differences = {
            "static": static_differences,
            "dynamic": dynamic_differences,
            "field_mapping": checks["field_mapping_missing"],
            "preexisting_source_gaps": missing_references,
            "new_loss_count": len(static_differences) + len(dynamic_differences),
        }
        (report_dir / "differences.json").write_text(json_text(differences, pretty=True) + "\n", encoding="utf-8")
        return checks

    def _entity_counts(self) -> dict[str, int]:
        connection = self.connect()
        tables = ["stocks", "stock_concepts", "plate_memberships", "daily_market", "launch_rounds", "first_open_events", "pool_members", "static_research", "dynamic_research", "research_checks"]
        result = {table: connection.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"] for table in tables}
        connection.close()
        return result

    def _rollback_drill(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="ultra-board-rollback-") as temp_dir:
            copy_path = Path(temp_dir) / "rollback.sqlite"
            source = self.connect()
            target = sqlite3.connect(copy_path)
            source.backup(target)
            target.close()
            source.close()
            connection = sqlite3.connect(copy_path)
            before = connection.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("INSERT INTO stocks(code,market,created_at) VALUES('999999','SZ','drill')")
                raise RuntimeError("intentional rollback drill")
            except RuntimeError:
                connection.rollback()
            after = connection.execute("SELECT COUNT(*) FROM stocks").fetchone()[0]
            connection.close()
        return {"before": before, "after": after, "passed": before == after}

    def _version_conflict_drill(self) -> dict[str, Any]:
        with tempfile.TemporaryDirectory(prefix="ultra-board-conflict-") as temp_dir:
            copy_path = Path(temp_dir) / "conflict.sqlite"
            source = self.connect()
            target = sqlite3.connect(copy_path)
            source.backup(target)
            key = source.execute("SELECT legacy_record_key FROM current_static_research ORDER BY id LIMIT 1").fetchone()["legacy_record_key"]
            rule_version = source.execute(
                "SELECT version FROM rule_sets WHERE rule_type='static' AND status='current'"
            ).fetchone()["version"]
            before = source.execute("SELECT COUNT(*) AS c FROM static_research").fetchone()["c"]
            target.close()
            source.close()
            copy_store = ResearchStore(self.root, copy_path)
            conflict = None
            try:
                copy_store.write_research({
                    "request_id": "version-conflict-drill",
                    "record_key": key,
                    "kind": "static",
                    "rule_version": rule_version,
                    "expected_version": 999999,
                    "updates": {"研究状态": "drill"},
                })
            except RuntimeError as exc:
                conflict = str(exc)
            check = sqlite3.connect(copy_path)
            after = check.execute("SELECT COUNT(*) FROM static_research").fetchone()[0]
            check.close()
        return {"record_key": key, "message": conflict, "before": before, "after": after, "passed": bool(conflict and before == after)}

    def _verification_samples(self, connection: sqlite3.Connection) -> list[dict[str, Any]]:
        candidates = [dict(row) for row in connection.execute(
            """SELECT r.legacy_record_key,s.code,l.focus_date,r.research_status
               FROM current_static_research r JOIN first_open_events e ON e.id=r.first_open_event_id
               JOIN launch_rounds l ON l.id=e.launch_round_id JOIN stocks s ON s.id=l.stock_id
               ORDER BY l.focus_date,s.code"""
        )]
        indexes = sorted(set([0, len(candidates) // 2, max(0, len(candidates) - 1)])) if candidates else []
        samples = []
        for index in indexes:
            item = candidates[index]
            started = time.perf_counter()
            counts = {
                "attributes": connection.execute(
                    """SELECT COUNT(*) AS c FROM stock_concepts sc JOIN stocks s ON s.id=sc.stock_id
                       WHERE s.code=? AND sc.observed_date<=?""",
                    (item["code"], item["focus_date"]),
                ).fetchone()["c"],
                "research": connection.execute(
                    "SELECT COUNT(*) AS c FROM current_static_research WHERE legacy_record_key=?", (item["legacy_record_key"],)
                ).fetchone()["c"],
            }
            samples.append({**item, **counts, "elapsed_ms": round(1000 * (time.perf_counter() - started), 3)})
        return samples
