import sqlite3
import unittest
from .batch import _in_suppression_scope
from .derive import Resolver
from .suppression import current_day


class SuppressionDateTests(unittest.TestCase):
    def test_time_bound_capital_tags_require_round_activation(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE stocks (id INTEGER PRIMARY KEY, code TEXT)")
        conn.execute("CREATE TABLE daily_market (stock_id INT, trade_date TEXT, source_type TEXT, board_height INT)")
        conn.execute("CREATE TABLE current_static_research (main_theme TEXT, raw_json TEXT, evidence_snapshot_json TEXT, first_open_event_id INT, research_status TEXT)")
        conn.execute("CREATE TABLE first_open_events (id INT, launch_round_id INT)")
        conn.execute("CREATE TABLE launch_rounds (id INT, stock_id INT, first_board_date TEXT, focus_date TEXT)")
        conn.execute("CREATE TABLE research_theme_inputs (stock_id INT, first_board_date TEXT, main_theme TEXT, basis TEXT, sources_json TEXT, attribute_overrides_json TEXT)")
        conn.execute("INSERT INTO stocks VALUES (1, '000001'), (2, '000002')")
        conn.execute("INSERT INTO daily_market VALUES (1, '2025-11-10', 'kaipanla_limit_pool', 1), (2, '2025-11-10', 'kaipanla_limit_pool', 1)")
        conn.execute("INSERT INTO research_theme_inputs VALUES (1, '2025-11-10', '锂电', '纯产业', '[]', '{}')")
        conn.execute("INSERT INTO research_theme_inputs VALUES (2, '2025-11-10', '实控人变更', '当期易主公告', '[]', '{}')")
        rules = {"自动匹配": {"属性归并": {"实控人变更": "并购重组"}, "时效属性": ["并购重组", "实控人变更", "股权转让"]}}
        resolver = Resolver(conn, rules, {})
        resolver.rounds[(1, "2025-11-10")] = (1, "2025-11-10")
        resolver.rounds[(2, "2025-11-10")] = (2, "2025-11-10")
        stale_member = {"stock_id": 1, "code": "000001", "attributes": {"tags": ["锂电", "并购重组", "股权转让"], "sources": []}}
        active_member = {"stock_id": 2, "code": "000002", "attributes": {"tags": ["实控人变更"], "sources": []}}
        self.assertNotIn("并购重组", resolver.attributes(stale_member, "2025-11-10")[0])
        self.assertIn("并购重组", resolver.attributes(active_member, "2025-11-10")[0])
        conn.close()
    def test_old_hit_does_not_survive_current_day(self):
        days = [{"日期":"2025-12-12","更高一字票":[{"命中":True}]},
                {"日期":"2025-12-25","更高一字票":[]}]
        self.assertEqual(current_day(days,"2025-12-25"),[days[1]])

    def test_current_hit_still_applies(self):
        day = {"日期":"2025-10-29","更高一字票":[{"命中":True}]}
        self.assertTrue(current_day([day],"2025-10-29")[0]["更高一字票"][0]["命中"])

    def test_missing_current_day_cannot_fall_back_to_history(self):
        with self.assertRaises(ValueError):
            current_day([{"日期":"2025-12-12"}],"2025-12-25")

    def test_next_first_open_does_not_reuse_prior_event(self):
        days = [{"日期":"2025-12-25"},{"日期":"2026-01-07"}]
        self.assertEqual(current_day(days,"2026-01-07"),[days[1]])

    def test_duplicate_current_day_is_rejected(self):
        with self.assertRaises(ValueError):
            current_day([{"日期":"2025-12-25"}]*2,"2025-12-25")

    def test_same_height_20cm_suppresses_mainboard_10cm_without_bse(self):
        self.assertTrue(_in_suppression_scope("603716", 2, "301293", 2))
        self.assertTrue(_in_suppression_scope("000892", 2, "300766", 2))
        self.assertTrue(_in_suppression_scope("002551", 2, "688108", 2))
        self.assertFalse(_in_suppression_scope("603716", 2, "000516", 2))
        self.assertFalse(_in_suppression_scope("603716", 2, "832522", 2))
        self.assertFalse(_in_suppression_scope("603716", 2, "920116", 2))
        self.assertTrue(_in_suppression_scope("603716", 2, "832522", 3))
