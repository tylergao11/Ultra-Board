import unittest
from .suppression import current_day


class SuppressionDateTests(unittest.TestCase):
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
