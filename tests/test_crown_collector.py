"""测试crown_odds_collector标准化: 联赛名转换、日期格式、match_id生成"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.crown_odds_collector import (
    normalize_league, normalize_date, build_match_id, CROWN_LEAGUE_MAP
)


class TestLeagueNormalization(unittest.TestCase):

    def test_swedish(self):
        self.assertEqual(normalize_league("瑞典超级联赛"), "瑞超")

    def test_finnish(self):
        self.assertEqual(normalize_league("芬兰超级联赛"), "芬超")

    def test_english(self):
        self.assertEqual(normalize_league("英格兰超级联赛"), "英超")

    def test_spanish(self):
        self.assertEqual(normalize_league("西班牙甲组联赛"), "西甲")

    def test_german(self):
        self.assertEqual(normalize_league("德国甲组联赛"), "德甲")

    def test_italian(self):
        self.assertEqual(normalize_league("意大利甲组联赛"), "意甲")

    def test_unknown_passthrough(self):
        """未知联赛名原样返回"""
        self.assertEqual(normalize_league("未知联赛"), "未知联赛")

    def test_all_mappings_non_empty(self):
        """所有映射值非空"""
        for crown_name, short_name in CROWN_LEAGUE_MAP.items():
            self.assertTrue(short_name, f"{crown_name} 映射为空")


class TestDateNormalization(unittest.TestCase):

    def test_chinese_date(self):
        """'07月28日' → '2026-07-28'"""
        result = normalize_date("07月28日")
        self.assertRegex(result, r"^\d{4}-07-28$")

    def test_single_digit(self):
        """'1月5日' → '2026-01-05'"""
        result = normalize_date("1月5日")
        self.assertRegex(result, r"^\d{4}-01-05$")

    def test_iso_passthrough(self):
        """已是ISO格式的日期原样返回"""
        self.assertEqual(normalize_date("2026-07-28"), "2026-07-28")

    def test_empty(self):
        self.assertEqual(normalize_date(""), "")


class TestMatchIdGeneration(unittest.TestCase):

    def test_standard_format(self):
        """match_id = CROWN_{短名}_{主队}_{客队}_{ISO日期}"""
        mid = build_match_id("瑞典超级联赛", "卡尔马", "马尔默", "07月28日")
        self.assertTrue(mid.startswith("CROWN_瑞超_卡尔马_马尔默_"))
        self.assertIn("-07-28", mid)

    def test_consistency(self):
        """相同输入产生相同match_id"""
        mid1 = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "08月15日")
        self.assertEqual(mid1, mid2)

    def test_different_dates_different_ids(self):
        """不同日期产生不同match_id(防延期重赛冲突)"""
        mid1 = build_match_id("英超", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("英超", "阿森纳", "切尔西", "08月16日")
        self.assertNotEqual(mid1, mid2)

    def test_different_leagues_different_ids(self):
        """不同联赛同队名产生不同match_id"""
        mid1 = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("西班牙甲组联赛", "阿森纳", "切尔西", "08月15日")
        self.assertNotEqual(mid1, mid2)


if __name__ == "__main__":
    unittest.main()
