"""测试crown_scraper._parse_matches: 文本解析逻辑(不需要浏览器)"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.crown_scraper import CrownOddsScraper


class TestParseMatchesBasic(unittest.TestCase):
    """基本解析"""

    def setUp(self):
        self.scraper = CrownOddsScraper.__new__(CrownOddsScraper)

    def test_single_match(self):
        text = "08月15日 20:00\n阿森纳\n切尔西"
        matches = self.scraper._parse_matches(text, "英格兰超级联赛")
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0]["home"], "阿森纳")
        self.assertEqual(matches[0]["away"], "切尔西")
        self.assertEqual(matches[0]["league"], "英格兰超级联赛")

    def test_multiple_matches(self):
        text = "08月15日 20:00\n阿森纳\n切尔西\n08月15日 22:00\n利物浦\n曼联"
        matches = self.scraper._parse_matches(text, "英格兰超级联赛")
        self.assertGreaterEqual(len(matches), 2)

    def test_match_has_date(self):
        text = "07月28日 15:00\n卡尔马\n马尔默"
        matches = self.scraper._parse_matches(text, "瑞典超级联赛")
        if matches:
            self.assertIn("07月28日", matches[0].get("date", ""))

    def test_match_has_time(self):
        text = "07月28日 15:00\n卡尔马\n马尔默"
        matches = self.scraper._parse_matches(text, "瑞典超级联赛")
        if matches:
            self.assertIn("15:00", matches[0].get("time", ""))


class TestParseMatchesEdgeCases(unittest.TestCase):
    """边界情况"""

    def setUp(self):
        self.scraper = CrownOddsScraper.__new__(CrownOddsScraper)

    def test_empty_text(self):
        self.assertEqual(self.scraper._parse_matches("", "英超"), [])

    def test_no_match_format(self):
        self.assertEqual(self.scraper._parse_matches("普通文字\n无比赛", "英超"), [])

    def test_whitespace_only(self):
        self.assertEqual(self.scraper._parse_matches("   \n  \n  ", "英超"), [])

    def test_date_without_teams(self):
        """有日期但无队名 → 不产生比赛"""
        text = "08月15日 20:00\n让球\n大/小"
        matches = self.scraper._parse_matches(text, "英超")
        # 不应产生有效比赛(无队名)
        for m in matches:
            self.assertTrue(m.get("home") and m.get("away"),
                          f"无效比赛不应有空队名: {m}")

    def test_single_digit_date(self):
        """两位数月/日(皇冠标准格式)"""
        text = "08月05日 09:00\n队伍A\n队伍B"
        matches = self.scraper._parse_matches(text, "测试联赛")
        self.assertGreaterEqual(len(matches), 1)


class TestParseMatchesWithOdds(unittest.TestCase):
    """带盘口数据的解析"""

    def setUp(self):
        self.scraper = CrownOddsScraper.__new__(CrownOddsScraper)

    def test_handicap_parsed(self):
        text = """08月15日 20:00
阿森纳
切尔西
让球
主让0.5
0.92
+0.5
0.95"""
        matches = self.scraper._parse_matches(text, "英格兰超级联赛")
        if matches:
            m = matches[0]
            self.assertIn("handicap", m)

    def test_over_under_parsed(self):
        text = """08月15日 20:00
阿森纳
切尔西
让球
主让0.5
0.92
+0.5
0.95
大/小
大
2.5
0.90
小
2.5
0.96"""
        matches = self.scraper._parse_matches(text, "英格兰超级联赛")
        if matches:
            m = matches[0]
            self.assertIn("over_line", m)


class TestParseMatchesNordic(unittest.TestCase):
    """北欧联赛解析"""

    def setUp(self):
        self.scraper = CrownOddsScraper.__new__(CrownOddsScraper)

    def test_swedish_league(self):
        text = "07月28日 19:00\nHammarby\nAIK"
        matches = self.scraper._parse_matches(text, "瑞典超级联赛")
        self.assertGreaterEqual(len(matches), 1)
        self.assertEqual(matches[0]["league"], "瑞典超级联赛")

    def test_finnish_league(self):
        text = "07月28日 18:30\nHJK\nIlves"
        matches = self.scraper._parse_matches(text, "芬兰超级联赛")
        self.assertGreaterEqual(len(matches), 1)


class TestCrownScraperNoDB(unittest.TestCase):
    """架构约束: 不访问数据库"""

    def test_no_database_import(self):
        import inspect
        from scraper import crown_scraper
        src = inspect.getsource(crown_scraper)
        self.assertNotIn("save_timeline_record", src)
        self.assertNotIn("save_odds_snapshot", src)
        self.assertNotIn("from utils.database", src)

    def test_no_odds_math_import(self):
        """crown_scraper不做盘口判断(只解析原始文本)"""
        import inspect
        from scraper import crown_scraper
        src = inspect.getsource(crown_scraper)
        self.assertNotIn("compute_change", src)
        self.assertNotIn("calc_clv", src)


if __name__ == "__main__":
    unittest.main()
