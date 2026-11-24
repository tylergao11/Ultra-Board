import json
import tempfile
import unittest
from pathlib import Path

from research.derive import reset_static
from research.test_sync_guard import _minimal_workspace


def _seed_reset_fixture(store):
    conn = store.connect()
    try:
        static_rule_id = conn.execute(
            "SELECT id FROM rule_sets WHERE rule_type='static' AND status='current'"
        ).fetchone()[0]
        dyn_rule_id = conn.execute(
            "SELECT id FROM rule_sets WHERE rule_type='dynamic' AND status='current'"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO import_batches(batch_key,kind,started_at,status) VALUES('b1','test','2026-11-24T00:00:00+08:00','done')"
        )
        batch_id = conn.execute("SELECT id FROM import_batches WHERE batch_key='b1'").fetchone()[0]
        conn.execute("INSERT OR REPLACE INTO store_meta(key,value) VALUES('current_batch_key','b1')")
        conn.execute(
            "INSERT INTO research_plans(plan_code,version,name,status,definition_json,rule_set_id) VALUES('formal',1,'正式','current','{}',?)",
            (dyn_rule_id,),
        )
        plan_id = conn.execute("SELECT id FROM research_plans WHERE plan_code='formal'").fetchone()[0]

        def add_stock(code, name):
            conn.execute("INSERT INTO stocks(code,market,created_at) VALUES(?,'SZ','2026-11-24T00:00:00+08:00')", (code,))
            sid = conn.execute("SELECT id FROM stocks WHERE code=?", (code,)).fetchone()[0]
            conn.execute(
                "INSERT INTO stock_names(stock_id,name,valid_from) VALUES(?,?,'2023-01-01')", (sid, name)
            )
            return sid

        s_old = add_stock("000001", "旧票")
        s_cross = add_stock("000002", "跨年票")
        s_new = add_stock("000003", "新年票")
        s_high_old = add_stock("000004", "老高标")
        s_high_cross = add_stock("000005", "跨年高标")

        def add_static(sid, code, name, fb, focus, ev, theme, with_dynamic=False):
            key = f"{code}|{focus}"
            conn.execute(
                """INSERT INTO source_records(batch_id,source_kind,source_path,section,record_key,stock_code,effective_date,raw_sha256,raw_json)
                   VALUES(?,'record_anchor','一字首开研究总表.json','一字首开股票与数据',?,?,?,'sha','{}')""",
                (batch_id, key, code, focus),
            )
            sr_id = conn.execute("SELECT id FROM source_records WHERE record_key=?", (key,)).fetchone()[0]
            conn.execute(
                """INSERT INTO launch_rounds(stock_id,legacy_record_key,first_board_date,focus_date,confirmed_main_theme,confirmation_status,source_record_id,raw_json)
                   VALUES(?,?,?,?,?,'source_not_labeled',?,'{}')""",
                (sid, key, fb, focus, theme, sr_id),
            )
            lr_id = conn.execute("SELECT id FROM launch_rounds WHERE legacy_record_key=?", (key,)).fetchone()[0]
            conn.execute(
                "INSERT INTO first_open_events(launch_round_id,event_date,event_status,legacy_record_key,raw_json) VALUES(?,?,'occurred',?,'{}')",
                (lr_id, ev, key),
            )
            fo_id = conn.execute("SELECT id FROM first_open_events WHERE legacy_record_key=?", (key,)).fetchone()[0]
            conn.execute(
                """INSERT INTO legacy_key_map(legacy_record_key,stock_id,launch_round_id,first_open_event_id,static_source_record_id)
                   VALUES(?,?,?,?,?)""",
                (key, sid, lr_id, fo_id, sr_id),
            )
            raw = {
                "底稿记录键": key,
                "股票代码": code,
                "股票": name,
                "关注日期": focus,
                "底稿首板日期": fb,
                "底稿板序原文": "1-2",
                "进板高度": "2进3",
                "首开日期": ev,
                "唯一主炒作属性": theme,
                "补涨判断": "先锋",
                "压制判断": "非压制",
                "自动推导": True,
            }
            conn.execute(
                """INSERT INTO static_research(
                       first_open_event_id,legacy_record_key,version,is_current,research_status,confirmation_status,
                       main_theme,replenishment_result,suppression_result,mapping_basis,suppression_basis,
                       source_record_id,rule_set_id,evidence_snapshot_json,raw_json
                   ) VALUES(?,?,1,1,'formal_source_record','source_not_labeled',?,'先锋','非压制','旧依据','旧压制',?,?,'["a.json"]',?)""",
                (fo_id, key, theme, sr_id, static_rule_id, json.dumps(raw, ensure_ascii=False)),
            )
            st_id = conn.execute("SELECT id FROM static_research WHERE legacy_record_key=?", (key,)).fetchone()[0]
            conn.execute(
                """INSERT INTO research_checks(static_research_id,check_type,outcome,basis,source_json,raw_json)
                   VALUES(?,'replenishment','先锋','旧核验','[]','{}')""",
                (st_id,),
            )
            if with_dynamic:
                conn.execute(
                    """INSERT INTO dynamic_research(
                           first_open_event_id,plan_id,legacy_record_key,version,is_current,
                           research_status,confirmation_status,source_record_id,evidence_snapshot_json,raw_json,rule_set_id
                       ) VALUES(?,?,?,1,1,'source_record','pending_user_confirmation',?,'[]','{}',?)""",
                    (fo_id, plan_id, key, sr_id, dyn_rule_id),
                )
            return key

        k_old = add_static(s_old, "000001", "旧票", "2024-03-04", "2024-03-05", "2024-03-06", "人工智能")
        k_cross = add_static(s_cross, "000002", "跨年票", "2024-12-26", "2024-12-31", "2025-01-02", "算力", with_dynamic=True)
        k_new = add_static(s_new, "000003", "新年票", "2025-01-02", "2025-01-03", "2025-01-06", "机器人")

        # Theme inputs: 2023 prior, 2024 normal, 2024 cross-year depended on by 2025, and 2025 normal.
        conn.executemany(
            "INSERT INTO research_theme_inputs VALUES(?,?,?,?,?,?)",
            [
                (s_high_old, "2023-12-28", "光伏", "旧2023高标", "[]", "{}"),
                (s_old, "2024-03-04", "人工智能", "旧2024候选", "[]", "{}"),
                (s_cross, "2024-12-26", "算力", "跨年候选", "[]", "{}"),
                (s_high_cross, "2024-12-25", "消费", "跨年高标", "[]", "{}"),
                (s_new, "2025-01-02", "机器人", "2025候选", "[]", "{}"),
            ],
        )
        conn.executemany(
            "INSERT INTO research_dependencies VALUES(?,?,?)",
            [
                (k_old, s_old, "2024-03-04"),
                (k_old, s_high_old, "2023-12-28"),
                (k_cross, s_cross, "2024-12-26"),
                (k_new, s_new, "2025-01-02"),
                (k_new, s_high_cross, "2024-12-25"),
                (k_new, s_cross, "2024-12-26"),
            ],
        )
        conn.executemany(
            "INSERT INTO issues(scope,severity,issue_kind,object_key,detail,impact,status) VALUES(?,?,?,?,?,?,?)",
            [
                ("source_update", "review", "facts_changed", k_old, "refreshed", "review", "open"),
                ("source_update", "review", "facts_changed", k_new, "refreshed", "review", "open"),
            ],
        )
        conn.commit()
    finally:
        conn.close()


class ResetStaticTest(unittest.TestCase):
    def test_preview_and_commit_protect_cross_year_and_dynamic(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _minimal_workspace(Path(tmp))
            _seed_reset_fixture(store)

            preview = reset_static(
                store,
                from_date="2024-01-01",
                to_date="2024-12-31",
                preview=True,
                include_prior_themes=True,
                publish=False,
            )
            self.assertEqual(preview["reset_records"], 1)
            self.assertEqual(len(preview["protected_records"]), 1)
            self.assertEqual(preview["protected_records"][0]["record_key"], "000002|2024-12-31")
            self.assertEqual(preview["deleted_theme_inputs"], 2)  # 2023-12-28 + 2024-03-04
            self.assertEqual(
                sorted((t["code"], t["first_board_date"]) for t in preview["protected_theme_inputs"]),
                [("000002", "2024-12-26"), ("000005", "2024-12-25")],
            )
            self.assertEqual(preview["deleted_issues"], 1)

            # Preview must not mutate database.
            conn = store.connect()
            try:
                old_row = conn.execute(
                    "SELECT research_status, main_theme FROM current_static_research WHERE legacy_record_key='000001|2024-03-05'"
                ).fetchone()
                self.assertEqual(old_row["research_status"], "formal_source_record")
                self.assertEqual(old_row["main_theme"], "人工智能")
            finally:
                conn.close()

            result = reset_static(
                store,
                from_date="2024-01-01",
                to_date="2024-12-31",
                preview=False,
                include_prior_themes=True,
                publish=False,
            )
            self.assertEqual(result["reset_records"], 1)
            self.assertEqual(result["deleted_theme_inputs"], 2)
            self.assertEqual(result["deleted_issues"], 1)

            conn = store.connect()
            try:
                old_row = conn.execute(
                    "SELECT * FROM current_static_research WHERE legacy_record_key='000001|2024-03-05'"
                ).fetchone()
                self.assertEqual(old_row["research_status"], "unresearched")
                self.assertIsNone(old_row["main_theme"])
                self.assertIsNone(old_row["replenishment_result"])
                self.assertIsNone(old_row["suppression_result"])
                self.assertEqual(old_row["evidence_snapshot_json"], "[]")
                raw = json.loads(old_row["raw_json"])
                self.assertNotIn("唯一主炒作属性", raw)
                self.assertNotIn("自动推导", raw)
                self.assertEqual(raw["底稿记录键"], "000001|2024-03-05")
                self.assertEqual(raw["首开日期"], "2024-03-06")

                # Protected cross-year and 2025 records remain untouched.
                cross_row = conn.execute(
                    "SELECT research_status, main_theme FROM current_static_research WHERE legacy_record_key='000002|2024-12-31'"
                ).fetchone()
                self.assertEqual(cross_row["main_theme"], "算力")
                new_row = conn.execute(
                    "SELECT research_status, main_theme FROM current_static_research WHERE legacy_record_key='000003|2025-01-03'"
                ).fetchone()
                self.assertEqual(new_row["main_theme"], "机器人")

                # Theme inputs retained: 2024-12-25, 2024-12-26, 2025-01-02.
                remaining_themes = sorted(
                    (r[0], r[1])
                    for r in conn.execute(
                        "SELECT s.code, t.first_board_date FROM research_theme_inputs t JOIN stocks s ON s.id=t.stock_id"
                    )
                )
                self.assertEqual(
                    remaining_themes,
                    [("000002", "2024-12-26"), ("000003", "2025-01-02"), ("000005", "2024-12-25")],
                )
                # Issues retained only for 2025.
                remaining_issues = [r[0] for r in conn.execute("SELECT object_key FROM issues")]
                self.assertEqual(remaining_issues, ["000003|2025-01-03"])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
