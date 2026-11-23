import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research.system import ResearchStore


def _minimal_workspace(root: Path) -> ResearchStore:
    (root / "data/store/rules").mkdir(parents=True, exist_ok=True)
    (root / "data/store/exports").mkdir(parents=True, exist_ok=True)
    (root / "tools/research").mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# test workflow\n", encoding="utf-8")
    (root / "data/store/rules/static_rules.json").write_text(
        json.dumps({"effective_from": "2026-11-20", "rule_type": "static", "rules": {"自动匹配": {}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "data/store/rules/dynamic_rules.json").write_text(
        json.dumps({"effective_from": "2026-11-20", "rule_type": "dynamic", "rules": {"统一入选口径": ["口径A"]}}, ensure_ascii=False),
        encoding="utf-8",
    )
    # Link real migrations directory so apply_migrations initializes full schema cleanly.
    real_migrations = Path(__file__).resolve().parent / "migrations"
    store = ResearchStore(root)
    store.migrations_dir = real_migrations
    conn = store.connect()
    try:
        store.apply_migrations(conn)
    finally:
        conn.close()
    store.sync_rules()
    return store


def _seed_one_dynamic_row(store: ResearchStore) -> None:
    conn = store.connect()
    try:
        dyn_rule_id = conn.execute(
            "SELECT id FROM rule_sets WHERE rule_type='dynamic' AND status='current'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO import_batches(batch_key,kind,started_at,status) VALUES('b1','test','2026-11-20T00:00:00+08:00','done')"
        )
        batch_id = conn.execute("SELECT id FROM import_batches WHERE batch_key='b1'").fetchone()[0]
        conn.execute(
            """INSERT INTO source_records(batch_id,source_kind,source_path,section,record_key,stock_code,effective_date,raw_sha256,raw_json)
               VALUES(?,'test','test.json','main','000001|2026-11-20','000001','2026-11-20','sha1','{}')""",
            (batch_id,),
        )
        source_id = conn.execute("SELECT id FROM source_records WHERE record_key='000001|2026-11-20'").fetchone()[0]
        conn.execute(
            "INSERT INTO research_plans(plan_code,version,name,status,definition_json,rule_set_id) VALUES('formal',1,'正式','current','{}',?)",
            (dyn_rule_id,),
        )
        plan_id = conn.execute("SELECT id FROM research_plans WHERE plan_code='formal'").fetchone()[0]
        conn.execute("INSERT INTO stocks(code,market,created_at) VALUES('000001','SZ','2026-11-20T00:00:00+08:00')")
        stock_id = conn.execute("SELECT id FROM stocks WHERE code='000001'").fetchone()[0]
        conn.execute(
            """INSERT INTO launch_rounds(stock_id,legacy_record_key,first_board_date,focus_date,confirmation_status,source_record_id,raw_json)
               VALUES(?,'000001|2026-11-20','2026-11-19','2026-11-20','user_confirmed',?,'{}')""",
            (stock_id, source_id),
        )
        round_id = conn.execute("SELECT id FROM launch_rounds").fetchone()[0]
        conn.execute(
            """INSERT INTO first_open_events(launch_round_id,event_date,event_status,legacy_record_key,raw_json)
               VALUES(?,'2026-11-20','open','000001|2026-11-20','{}')""",
            (round_id,),
        )
        event_id = conn.execute("SELECT id FROM first_open_events").fetchone()[0]
        conn.execute(
            """INSERT INTO dynamic_research(
                   first_open_event_id,plan_id,legacy_record_key,version,is_current,
                   research_status,confirmation_status,source_record_id,evidence_snapshot_json,raw_json,rule_set_id
               ) VALUES(?,?,?,1,1,'formal_research','user_confirmed',?,'{}','{}',?)""",
            (event_id, plan_id, "000001|2026-11-20", source_id, dyn_rule_id),
        )
        conn.commit()
    finally:
        conn.close()


class SyncGuardTest(unittest.TestCase):
    def test_stale_db_vs_git_export_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = _minimal_workspace(root)
            (root / "data/store/exports/current.json").write_text(
                json.dumps({"generation_key": "20261123-999999-abcdef1234"}, ensure_ascii=False),
                encoding="utf-8",
            )
            health = store.sync_health()
            self.assertFalse(health["ok"])
            self.assertFalse(health["db_matches_git_export"])
            with self.assertRaisesRegex(RuntimeError, "落后于当前 Git 导出批次"):
                store.ensure_write_safe()

            conn = store.connect()
            try:
                conn.execute(
                    """INSERT INTO generation_batches(
                           generation_key,created_at,database_sha256,input_batch_key,
                           rule_versions_json,output_dir,manifest_json
                       ) VALUES('20261123-999999-abcdef1234','2026-11-23','abc','batch','{}','out','{}')"""
                )
                conn.commit()
            finally:
                conn.close()

            health_after = store.sync_health()
            self.assertTrue(health_after["ok"])
            self.assertTrue(health_after["db_matches_git_export"])
            store.ensure_write_safe()

    def test_dynamic_rule_change_blocked_without_explicit_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = _minimal_workspace(root)
            _seed_one_dynamic_row(store)

            # Modify dynamic_rules.json by a single rule item
            (root / "data/store/rules/dynamic_rules.json").write_text(
                json.dumps({"effective_from": "2026-11-23", "rule_type": "dynamic", "rules": {"统一入选口径": ["口径A", "口径B"]}}, ensure_ascii=False),
                encoding="utf-8",
            )

            health = store.sync_health()
            self.assertFalse(health["ok"])
            self.assertFalse(health["dynamic_rule_synced"])
            self.assertEqual(health["dynamic_research_count"], 1)

            with self.assertRaisesRegex(RuntimeError, "清空全部 1 条动态交易研究记录"):
                store.ensure_write_safe()
            with self.assertRaisesRegex(RuntimeError, "清空全部 1 条动态交易研究记录"):
                store.sync_rules()

            # Verify row is still completely intact after blocked attempts
            conn = store.connect()
            try:
                count = conn.execute("SELECT COUNT(*) FROM current_dynamic_research").fetchone()[0]
                self.assertEqual(count, 1)
            finally:
                conn.close()

            # Explicit confirmation proceeds as intended
            store.sync_rules(confirm_dynamic_rule_change=True)
            conn = store.connect()
            try:
                count_after = conn.execute("SELECT COUNT(*) FROM current_dynamic_research").fetchone()[0]
                self.assertEqual(count_after, 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
