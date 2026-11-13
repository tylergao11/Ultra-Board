"""Unified command line entry for the Ultra-Board research database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import zipfile

from research.system import ResearchStore, json_text, now_text, sha256_bytes, sha256_file
from research.batch import commit_batch, verify_batch_current, prepare_batch, submission_key
from research.intake import fetch_attributes, ingest_paths
from research.derive import recompute, set_theme
from research.scratch import Workspace, clean as clean_temporary


ROOT = Path(__file__).resolve().parents[1]


def store_for(args: argparse.Namespace) -> ResearchStore:
    return ResearchStore(ROOT, Path(args.db) if getattr(args, "db", None) else None)


def emit(value) -> None:
    print(json_text(value, pretty=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Ultra-Board unified research store")
    parser.add_argument("--db", help="SQLite path; defaults to data/store/research.sqlite")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("sync-rules", help="synchronize the current rule files without reimporting data")
    sub.add_parser("summary", help="show current database counts")
    environment = sub.add_parser("sector-top3", help="show original sector top three for five saved trading sessions")
    environment.add_argument("--date", required=True)
    rules = sub.add_parser("rules", help="show the current research rules")
    rules.add_argument("--scope", choices=["static", "dynamic", "all"], default="static")
    ingest = sub.add_parser("ingest", help="incrementally ingest saved files or directories; no full migration")
    ingest.add_argument("--path", action="append", dest="paths")
    fetch = sub.add_parser("fetch-attributes", help="save and incrementally ingest stock attributes")
    fetch.add_argument("--code", action="append", required=True, dest="codes")
    fetch.add_argument("--refresh", action="store_true", help="fetch a new same-day snapshot")

    stock = sub.add_parser("stock", help="query a stock file")
    stock.add_argument("--code", required=True)

    attributes = sub.add_parser("attributes", help="query point-in-time attributes")
    attributes.add_argument("--code", required=True)
    attributes.add_argument("--date", required=True)

    pool = sub.add_parser("pool", help="query a dated stock pool")
    pool.add_argument("--type", required=True)
    pool.add_argument("--date", required=True)
    pool.add_argument("--record-key")
    pool.add_argument("--input-batch", dest="input_version", help="defaults to the current imported data")

    research = sub.add_parser("research", help="query a complete research record")
    research.add_argument("--record-key", required=True)
    research.add_argument("--plan", default="formal")

    issues = sub.add_parser("issues", help="query preserved data gaps and impacts")
    issues.add_argument("--from-date")
    issues.add_argument("--to-date")

    impact = sub.add_parser("impact", help="locate research affected by a stock, source, date or rule object")
    impact.add_argument("--object", required=True)

    derive = sub.add_parser("derive", help="local automatic static matching; inputs contain only judgements")
    derive.add_argument("--input", help="optional themes, announcements and record_keys JSON")
    derive.add_argument("--batch", help="reuse record keys from a prepared batch directory")
    derive.add_argument("--record-key", action="append", dest="record_keys")
    derive.add_argument("--preview", action="store_true")
    derive.add_argument("--report", help="save timing and results as JSON")
    theme = sub.add_parser("theme-set", help="change one launch theme and refresh all related static results locally")
    theme.add_argument("--record-key", required=True)
    theme.add_argument("--theme", required=True)
    theme.add_argument("--basis")
    theme.add_argument("--preview", action="store_true")
    theme.add_argument("--report")

    batch_prepare = sub.add_parser("batch-prepare", help="prepare one lightweight research batch and decision template")
    batch_prepare.add_argument("--output", required=True, help="output directory for facts.json and decisions.json")
    batch_prepare.add_argument("--limit", type=int)
    batch_prepare.add_argument("--from-date")
    batch_prepare.add_argument("--to-date")
    batch_prepare.add_argument("--scope", choices=["static", "both"], default="static")
    batch_prepare.add_argument("--fetch-missing", action="store_true", default=True, help="fetch missing stock attributes (default)")
    batch_prepare.add_argument("--offline", action="store_false", dest="fetch_missing", help="prepare from saved facts and list missing attributes")
    batch_prepare.add_argument("--year", type=int)
    batch_prepare.add_argument("--record-key", action="append", dest="record_keys")

    batch_commit = sub.add_parser("batch-commit", help="commit a compact decision file and run fast batch verification")
    batch_commit.add_argument("--batch", required=True)
    batch_commit.add_argument("--no-publish", action="store_true", help="skip regenerating the two display tables")

    batch_verify = sub.add_parser("batch-verify", help="run the fast per-batch database gate")
    batch_verify.add_argument("--batch", required=True)

    export = sub.add_parser("export", help="generate compact tables, CSV and statistics")
    export.add_argument("--output-root")
    export.add_argument("--publish-root", action="store_true")

    verify = sub.add_parser("verify", help="run full real-data verification")
    verify.add_argument("--report-dir", default="data/store/verification/current")

    reports = sub.add_parser("reports", help="write schema, rule and coverage reports")
    reports.add_argument("--output", default="data/store/migrations/reports")

    backup = sub.add_parser("backup", help="create a coherent database and cutover restore point")
    backup.add_argument("--output", default="data/store/migrations/recovery/current")

    drill = sub.add_parser("restore-drill", help="restore a backup into an isolated copy and verify it")
    drill.add_argument("--backup", required=True)
    drill.add_argument("--report", default="data/store/migrations/verification/restore_drill.json")

    restore = sub.add_parser("restore", help="restore a database backup with a pre-restore safety copy")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--target", default="data/store/research.sqlite")
    restore.add_argument("--restore-files", action="store_true", help="also restore the matching cutover files archive")

    evidence = sub.add_parser("register-evidence", help="register one newly saved source response")
    evidence.add_argument("--path", required=True)
    sub.add_parser("refresh-evidence", help="rebuild the current evidence inventory and mark historical paths")
    maintain = sub.add_parser("maintain", help="process newly downloaded daily data, verify, publish and rotate backups")
    maintain.add_argument("--keep-backups", type=int, default=3)
    temporary = sub.add_parser("temp-new",help="create an owned temporary workspace")
    temporary.add_argument("--purpose",required=True)
    temporary.add_argument("--file",action="append",dest="files",default=[])
    temporary.add_argument("--owner-pid",type=int)
    cleanup = sub.add_parser("temp-clean",help="delete only registered temporary files")
    cleanup.add_argument("--id")
    cleanup.add_argument("--owner-pid",type=int)
    snapshot = sub.add_parser("db-snapshot",help="create a consistent SQLite snapshot including committed WAL data")
    snapshot.add_argument("--output",required=True)

    args = parser.parse_args()
    store = store_for(args)
    if args.command == "sector-top3":
        from research.environment import sector_top3
        emit(sector_top3(store, args.date))
    elif args.command == "temp-new":
        workspace = Workspace(ROOT,args.purpose,args.files,owner_pid=args.owner_pid or os.getppid())
        emit({"id":workspace.path.name,"path":str(workspace.path)})
    elif args.command == "temp-clean":
        emit(clean_temporary(ROOT,args.id,args.owner_pid))
    elif args.command == "db-snapshot":
        emit(store.database_snapshot(ROOT / args.output))
    elif args.command == "sync-rules":
        emit(store.sync_rules())
    elif args.command == "summary":
        connection = store.connect()
        store.apply_migrations(connection)
        tables = [
            "evidence_files", "stocks", "stock_concepts", "plate_memberships", "daily_market",
            "announcements", "launch_rounds", "first_open_events", "stock_pools", "pool_members",
            "current_static_research", "current_dynamic_research", "issues",
        ]
        result = {
            "database": str(store.db_path),
            "database_size": store.db_path.stat().st_size if store.db_path.exists() else 0,
            "tables": {name: connection.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"] for name in tables},
            "rules": {row["rule_type"]: row["source_path"] for row in connection.execute("SELECT rule_type,source_path FROM rule_sets WHERE status='current'")},
        }
        connection.close()
        emit(result)
    elif args.command == "rules":
        current = store.current_rules()
        emit(current if args.scope == "all" else {key: value for key, value in current.items() if key == args.scope})
    elif args.command == "ingest":
        result = ingest_paths(store, args.paths)
        emit(result)
        if result["errors"]:
            raise SystemExit(1)
    elif args.command == "fetch-attributes":
        result = fetch_attributes(store, args.codes, args.refresh)
        emit(result)
        if result["errors"] or (result["intake"] and result["intake"]["errors"]):
            raise SystemExit(1)
    elif args.command == "stock":
        emit(store.query_stock(args.code))
    elif args.command == "attributes":
        emit(store.query_attributes(args.code, args.date))
    elif args.command == "pool":
        emit(store.query_pool(args.type, args.date, args.record_key, args.input_version, None))
    elif args.command == "research":
        emit(store.query_research(args.record_key, args.plan))
    elif args.command == "issues":
        emit(store.query_issues(args.from_date, args.to_date))
    elif args.command == "impact":
        emit(store.query_impact(args.object))
    elif args.command in {"derive", "theme-set"}:
        submitted = None
        receipt = None
        if args.command == "theme-set":
            result = set_theme(store, args.record_key, args.theme, args.basis, args.preview)
        else:
            if args.input and args.report and (ROOT / args.input).resolve()==(ROOT / args.report).resolve():
                raise ValueError("输入文件和输出报告须使用不同路径")
            payload = json.loads((ROOT / args.input).read_text(encoding="utf-8")) if args.input else None
            if args.input and not args.preview:
                submitted = (ROOT / args.input).resolve()
                receipt = {"key":submission_key(store,submitted,"input"),
                           "sha256":hashlib.sha256(submitted.read_bytes()).hexdigest(),"phase":"static"}
                connection = store.connect()
                saved = connection.execute("SELECT value FROM store_meta WHERE key=?",(receipt["key"],)).fetchone()
                connection.close()
                saved = json.loads(saved[0]) if saved else None
                if saved and saved["sha256"]==receipt["sha256"]:
                    payload = {"record_keys":saved["record_keys"]}
            keys = list(args.record_keys or [])
            if args.batch:
                batch = json.loads((ROOT / args.batch / "batch.json").read_text(encoding="utf-8"))
                keys.extend(batch["record_keys"])
            if receipt and saved and saved["sha256"]==receipt["sha256"] and not saved["record_keys"] and not keys:
                result = {"record_count":0,"complete":0,"blocked":[],"changed":0,"export":store.publish_pending()}
            else:
                result = recompute(store, keys, payload, args.preview,receipt=receipt)
        if args.report:
            report = ROOT / args.report
            report.parent.mkdir(parents=True, exist_ok=True)
            report.write_text(json_text(result, pretty=True) + "\n", encoding="utf-8")
        if submitted:
            if submitted.is_relative_to((ROOT / "data/research").resolve()):
                submitted.unlink()
                connection = store.connect()
                connection.execute("DELETE FROM store_meta WHERE key=?",(receipt["key"],))
                connection.commit()
                connection.close()
        emit(result)
    elif args.command == "batch-prepare":
        emit(prepare_batch(
            store,
            ROOT / args.output,
            limit=args.limit,
            year=args.year,
            record_keys=args.record_keys,
            scope=args.scope,
            from_date=args.from_date,
            to_date=args.to_date,
            fetch_missing=args.fetch_missing,
        ))
    elif args.command == "batch-commit":
        emit(commit_batch(
            store,
            ROOT / args.batch / "facts.json",
            ROOT / args.batch / "decisions.json",
            publish=not args.no_publish,
        ))
    elif args.command == "batch-verify":
        result = verify_batch_current(store,ROOT / args.batch)
        emit(result)
        if not result["passed"]:
            raise SystemExit(1)
    elif args.command == "export":
        emit(store.export_all(ROOT / args.output_root if args.output_root else None, args.publish_root))
    elif args.command == "verify":
        result = store.verify_full(ROOT / args.report_dir)
        emit(result)
        if not result["passed"]:
            raise SystemExit(1)
    elif args.command == "reports":
        emit(store.write_contract_reports(ROOT / args.output))
    elif args.command == "backup":
        emit(store.create_restore_point(ROOT / args.output))
    elif args.command == "restore-drill":
        emit(store.restore_drill(ROOT / args.backup, ROOT / args.report))
    elif args.command == "restore":
        backup_path = (ROOT / args.backup).resolve()
        target_path = (ROOT / args.target).resolve()
        check = sqlite3.connect(backup_path)
        integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
        check.close()
        if integrity != "ok":
            raise RuntimeError(f"backup integrity check failed: {integrity}")
        restored_files: list[str] = []
        temporary_cleanup = None
        pre_restore_files = None
        if args.restore_files:
            manifest_path = backup_path.parent / "restore_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            archive_path = (ROOT / manifest["files"]["path"]).resolve()
            if sha256_file(archive_path) != manifest["files"]["sha256"]:
                raise RuntimeError("cutover files archive checksum mismatch")
            expected = {item["path"]: item for item in manifest["files"].get("entries", [])}
            with Workspace(ROOT,"restore-files",expected) as workspace:
                staging = workspace.path
                with zipfile.ZipFile(archive_path, "r") as archive:
                    if set(archive.namelist()) != set(expected):
                        raise RuntimeError("cutover files archive entry list mismatch")
                    for name, item in expected.items():
                        payload = archive.read(name)
                        if len(payload) != item["size"] or sha256_bytes(payload) != item["sha256"]:
                            raise RuntimeError(f"cutover archive entry checksum mismatch: {name}")
                        destination = (staging / name).resolve()
                        destination.relative_to(staging.resolve())
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(payload)
                pre_restore_files = backup_path.parent / f"pre-restore-files-{backup_path.stem}.zip"
                with zipfile.ZipFile(pre_restore_files, "w", compression=zipfile.ZIP_DEFLATED) as safety_archive:
                    for name in expected:
                        current = (ROOT / name).resolve()
                        current.relative_to(ROOT.resolve())
                        if current.exists():
                            safety_archive.write(current, name)
                for name in expected:
                    source_file = staging / name
                    destination = (ROOT / name).resolve()
                    destination.relative_to(ROOT.resolve())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    staged_file = destination.with_name(f".{destination.name}.restoring")
                    shutil.copy2(source_file, staged_file)
                    os.replace(staged_file, destination)
                    restored_files.append(name)
            temporary_cleanup = workspace.cleanup_result
        safety = target_path.with_suffix(target_path.suffix + ".pre-restore")
        if target_path.exists():
            shutil.copy2(target_path, safety)
        temporary = target_path.with_suffix(target_path.suffix + ".restoring")
        shutil.copy2(backup_path, temporary)
        os.replace(temporary, target_path)
        emit({
            "restored_at": now_text(),
            "backup": str(backup_path),
            "backup_sha256": sha256_file(backup_path),
            "target": str(target_path),
            "pre_restore_copy": str(safety) if safety.exists() else None,
            "restored_files": restored_files,
            "temporary_cleanup": temporary_cleanup,
            "pre_restore_files_archive": str(pre_restore_files) if pre_restore_files else None,
        })
    elif args.command == "register-evidence":
        emit({"evidence_id": store.register_evidence_path(ROOT / args.path), "path": args.path})
    elif args.command == "refresh-evidence":
        emit(store.refresh_evidence_inventory())
    elif args.command == "maintain":
        emit(store.maintain_daily(args.keep_backups))


if __name__ == "__main__":
    try:
        main()
    except (KeyError, ValueError, RuntimeError, FileNotFoundError, sqlite3.Error) as exc:
        print(json_text({"error": type(exc).__name__, "message": str(exc)}, pretty=True), file=sys.stderr)
        raise SystemExit(1)
