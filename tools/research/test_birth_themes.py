import unittest

from research.birth_themes import birth_fields


class BirthThemesTests(unittest.TestCase):
    def high(self, code, theme, status="4板晋级"):
        return {"code": code, "name": code, "board_height": 4, "status": status,
                "confirmed_main_theme": theme, "source": "data/day/zt_pool.json"}

    def test_all_directions_without_candidate_intersection(self):
        result = birth_fields("2025-01-02", [self.high("1", "金融概念"),
            self.high("2", "机器人"), self.high("3", "算力", "4板断板")], lambda s: s)
        self.assertEqual(set(result["出生当日补涨题材"]), {"金融概念", "机器人", "算力"})
        self.assertEqual(len(result["出生当日补涨高标"]), 3)

    def test_aliases_deduplicate_themes_but_keep_highs(self):
        result = birth_fields("2025-01-02", [self.high("1", "数字经济"),
            self.high("2", "金融概念")], lambda s: "金融概念" if s == "数字经济" else s)
        self.assertEqual(result["出生当日补涨题材"], ["金融概念"])
        self.assertEqual(len(result["出生当日补涨高标"]), 2)

    def test_no_highs_is_explicit_empty_list(self):
        result = birth_fields("2025-01-02", [], lambda s: s)
        self.assertEqual(result["出生当日补涨题材"], [])
        self.assertEqual(result["补涨题材日期"], "2025-01-02")

    def test_unknown_theme_is_not_silently_omitted(self):
        with self.assertRaises(ValueError):
            birth_fields("2025-01-02", [self.high("1", None)], lambda s: s)


if __name__ == "__main__":
    unittest.main()
