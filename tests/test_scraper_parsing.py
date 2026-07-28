"""测试crown_scraper解析逻辑和HGA XML解析(不需要浏览器)"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.crown_scraper import CrownOddsScraper


class TestCrownScraperParseMatches(unittest.TestCase):
    """测试_parse_matches文本解析(不需要浏览器)"""

    def setUp(self):
        # 创建一个不连接浏览器的实例
        self.scraper = CrownOddsScraper.__new__(CrownOddsScraper)

    def test_parse_basic_match(self):
        """解析基本比赛行"""
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
0.96
独赢
主
1.85
客
4.20
和
3.40"""
        matches = self.scraper._parse_matches(text, "英格兰超级联赛")
        self.assertGreaterEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["home"], "阿森纳")
        self.assertEqual(m["away"], "切尔西")
        self.assertEqual(m["league"], "英格兰超级联赛")

    def test_parse_multiple_matches(self):
        """解析多场比赛"""
        text = """08月15日 20:00
阿森纳
切尔西
08月15日 22:00
利物浦
曼联"""
        matches = self.scraper._parse_matches(text, "英格兰超级联赛")
        self.assertGreaterEqual(len(matches), 2)

    def test_parse_empty_text(self):
        """空文本不崩溃"""
        matches = self.scraper._parse_matches("", "英超")
        self.assertEqual(matches, [])

    def test_parse_no_matches_in_text(self):
        """无比赛格式的文本"""
        matches = self.scraper._parse_matches("这是一段普通文字\n没有比赛信息", "英超")
        self.assertEqual(matches, [])

    def test_match_has_date_field(self):
        """解析结果包含日期"""
        text = """07月28日 15:00
卡尔马
马尔默"""
        matches = self.scraper._parse_matches(text, "瑞典超级联赛")
        if matches:
            self.assertIn("date", matches[0])
            self.assertIn("07月28日", matches[0]["date"])


class TestHGAXMLParsing(unittest.TestCase):
    """测试HGA XML解析逻辑"""

    def test_parse_game_xml_basic(self):
        """基本XML解析"""
        from scraper.hga_scraper import HGACrownScraper
        scraper = HGACrownScraper.__new__(HGACrownScraper)

        xml = """<?xml version="1.0" encoding="UTF-8"?>
<serverresponse>
<game>
<ec>123</ec>
<cn>英格兰超级联赛</cn>
<gn>456</gn>
<hn>阿森纳</hn>
<an>切尔西</an>
<st>2026-08-15 20:00</st>
<hdp>-0.5</hdp>
<ho>0.92</ho>
<ao>0.95</ao>
<ou>2.5</ou>
<oo>0.90</oo>
<uo>0.96</uo>
</game>
</serverresponse>"""
        matches = scraper._parse_game_xml(xml, "today")
        self.assertGreaterEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["home_team"], "阿森纳")
        self.assertEqual(m["away_team"], "切尔西")

    def test_parse_game_xml_empty(self):
        """空XML"""
        from scraper.hga_scraper import HGACrownScraper
        scraper = HGACrownScraper.__new__(HGACrownScraper)
        matches = scraper._parse_game_xml("<serverresponse></serverresponse>", "today")
        self.assertEqual(matches, [])

    def test_parse_game_xml_malformed(self):
        """畸形XML不崩溃"""
        from scraper.hga_scraper import HGACrownScraper
        scraper = HGACrownScraper.__new__(HGACrownScraper)
        matches = scraper._parse_game_xml("this is not xml at all", "today")
        # 应该回退到regex解析或返回空
        self.assertIsInstance(matches, list)

    def test_check_login_success(self):
        """登录成功检测"""
        from scraper.hga_scraper import HGACrownScraper
        scraper = HGACrownScraper.__new__(HGACrownScraper)
        resp = "<serverresponse><status>200</status><uid>abc123</uid></serverresponse>"
        self.assertTrue(scraper._check_login_success(resp))

    def test_check_login_failure(self):
        """登录失败检测"""
        from scraper.hga_scraper import HGACrownScraper
        scraper = HGACrownScraper.__new__(HGACrownScraper)
        resp = "<serverresponse><status>error</status><msg>101</msg></serverresponse>"
        self.assertFalse(scraper._check_login_success(resp))

    def test_format_handicap(self):
        """盘口格式化: 正值→主让, 负值→客让, 0→平手"""
        from scraper.hga_scraper import HGACrownScraper
        scraper = HGACrownScraper.__new__(HGACrownScraper)
        self.assertEqual(scraper._format_handicap("0.5", "阿森纳"), "主让0.5")
        self.assertEqual(scraper._format_handicap("-0.5", "阿森纳"), "客让0.5")
        self.assertEqual(scraper._format_handicap("0", "阿森纳"), "平手")


class TestCrownScraperNoDBAccess(unittest.TestCase):
    """crown_scraper不访问数据库"""

    def test_no_database_import(self):
        import inspect
        from scraper import crown_scraper
        src = inspect.getsource(crown_scraper)
        self.assertNotIn("save_timeline_record", src)
        self.assertNotIn("save_odds_snapshot", src)
        self.assertNotIn("from utils.database", src)


if __name__ == "__main__":
    unittest.main()
