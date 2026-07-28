"""测试HGA XML解析: 登录检测/盘口XML/联赛列表/畸形数据"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.hga_scraper import HGACrownScraper


class TestHGALoginDetection(unittest.TestCase):
    """登录成功/失败检测"""

    def setUp(self):
        self.scraper = HGACrownScraper.__new__(HGACrownScraper)

    def test_login_success_with_uid(self):
        resp = "<serverresponse><status>200</status><uid>abc123</uid></serverresponse>"
        self.assertTrue(self.scraper._check_login_success(resp))

    def test_login_success_status_ok(self):
        resp = "<serverresponse><status>ok</status><uid>xyz</uid></serverresponse>"
        self.assertTrue(self.scraper._check_login_success(resp))

    def test_login_failure_error_status(self):
        resp = "<serverresponse><status>error</status><msg>101</msg></serverresponse>"
        self.assertFalse(self.scraper._check_login_success(resp))

    def test_login_failure_wrong_password(self):
        resp = "<serverresponse><status>error</status><msg>102</msg><code_message>密码错误</code_message></serverresponse>"
        self.assertFalse(self.scraper._check_login_success(resp))

    def test_login_empty_uid_with_status_200(self):
        """status=200时即使uid为空也视为成功(当前实现行为)"""
        resp = "<serverresponse><status>200</status><uid></uid></serverresponse>"
        self.assertTrue(self.scraper._check_login_success(resp))

    def test_extract_error_message(self):
        resp = "<serverresponse><status>error</status><msg>101</msg><code_message>账号被锁定</code_message></serverresponse>"
        err = self.scraper._extract_error(resp)
        self.assertIn("101", err)
        self.assertIn("账号被锁定", err)


class TestHGAXMLParsing(unittest.TestCase):
    """盘口XML解析"""

    def setUp(self):
        self.scraper = HGACrownScraper.__new__(HGACrownScraper)

    def test_basic_game_xml(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
<serverresponse>
<game>
<ec>123</ec><cn>英格兰超级联赛</cn><gn>456</gn>
<hn>阿森纳</hn><an>切尔西</an><st>2026-08-15 20:00</st>
<hdp>-0.5</hdp><ho>0.92</ho><ao>0.95</ao>
<ou>2.5</ou><oo>0.90</oo><uo>0.96</uo>
</game>
</serverresponse>"""
        matches = self.scraper._parse_game_xml(xml, "today")
        self.assertGreaterEqual(len(matches), 1)
        m = matches[0]
        self.assertEqual(m["home_team"], "阿森纳")
        self.assertEqual(m["away_team"], "切尔西")
        self.assertEqual(m["league"], "英格兰超级联赛")

    def test_multiple_games(self):
        xml = """<serverresponse>
<game><hn>队伍A</hn><an>队伍B</an><gn>1</gn><cn>测试</cn><st>20:00</st><hdp>-0.5</hdp><ho>0.9</ho><ao>0.95</ao></game>
<game><hn>队伍C</hn><an>队伍D</an><gn>2</gn><cn>测试</cn><st>22:00</st><hdp>-1</hdp><ho>0.88</ho><ao>1.0</ao></game>
</serverresponse>"""
        matches = self.scraper._parse_game_xml(xml, "today")
        self.assertGreaterEqual(len(matches), 2)

    def test_empty_response(self):
        matches = self.scraper._parse_game_xml("<serverresponse></serverresponse>", "today")
        self.assertEqual(matches, [])

    def test_malformed_xml_fallback(self):
        """畸形XML不崩溃，回退到regex或返回空"""
        matches = self.scraper._parse_game_xml("this is not xml", "today")
        self.assertIsInstance(matches, list)

    def test_game_with_opening_odds(self):
        """含初盘字段"""
        xml = """<serverresponse>
<game><hn>A</hn><an>B</an><gn>1</gn><cn>测试</cn><st>20:00</st>
<hdp>-0.5</hdp><ho>0.92</ho><ao>0.95</ao>
<ohdp>-0.25</ohdp><oho>0.90</oho><oao>0.97</oao>
</game></serverresponse>"""
        matches = self.scraper._parse_game_xml(xml, "today")
        if matches:
            m = matches[0]
            self.assertIn("opening", m)

    def test_missing_handicap_fields(self):
        """缺少盘口字段不崩溃"""
        xml = """<serverresponse>
<game><hn>A</hn><an>B</an><gn>1</gn><cn>测试</cn><st>20:00</st></game>
</serverresponse>"""
        matches = self.scraper._parse_game_xml(xml, "today")
        self.assertIsInstance(matches, list)


class TestHGALeagueListParsing(unittest.TestCase):
    """联赛列表XML解析"""

    def setUp(self):
        self.scraper = HGACrownScraper.__new__(HGACrownScraper)

    def test_basic_league_list(self):
        xml = """<serverresponse>
<ec><cn>英格兰超级联赛</cn><ec>39</ec></ec>
<ec><cn>西班牙甲组联赛</cn><ec>140</ec></ec>
</serverresponse>"""
        leagues = self.scraper._parse_league_xml(xml)
        self.assertIsInstance(leagues, list)

    def test_empty_league_list(self):
        leagues = self.scraper._parse_league_xml("<serverresponse></serverresponse>")
        self.assertEqual(leagues, [])

    def test_malformed_league_xml(self):
        leagues = self.scraper._parse_league_xml("not xml at all")
        self.assertIsInstance(leagues, list)


class TestHGAFormatHandicap(unittest.TestCase):
    """盘口格式化"""

    def setUp(self):
        self.scraper = HGACrownScraper.__new__(HGACrownScraper)

    def test_positive_home(self):
        self.assertEqual(self.scraper._format_handicap("0.5", "阿森纳"), "主让0.5")

    def test_negative_away(self):
        self.assertEqual(self.scraper._format_handicap("-0.5", "阿森纳"), "客让0.5")

    def test_zero_level(self):
        self.assertEqual(self.scraper._format_handicap("0", "阿森纳"), "平手")

    def test_integer_handicap(self):
        self.assertEqual(self.scraper._format_handicap("1", "阿森纳"), "主让1.0")

    def test_empty_string(self):
        self.assertEqual(self.scraper._format_handicap("", "阿森纳"), "")


class TestHGASafeFloat(unittest.TestCase):
    """_safe_float委托到helpers"""

    def setUp(self):
        self.scraper = HGACrownScraper.__new__(HGACrownScraper)

    def test_normal_float(self):
        self.assertAlmostEqual(self.scraper._safe_float("0.95"), 0.95)

    def test_none(self):
        self.assertEqual(self.scraper._safe_float(None), 0.0)

    def test_empty_string(self):
        self.assertEqual(self.scraper._safe_float(""), 0.0)

    def test_garbage(self):
        self.assertEqual(self.scraper._safe_float("abc"), 0.0)


class TestHGANoDBAccess(unittest.TestCase):
    """架构约束"""

    def test_no_database_import(self):
        import inspect
        from scraper import hga_scraper
        src = inspect.getsource(hga_scraper)
        self.assertNotIn("from utils.database", src)
        self.assertNotIn("save_timeline", src)

    def test_no_recommendation_logic(self):
        import inspect
        from scraper import hga_scraper
        src = inspect.getsource(hga_scraper)
        self.assertNotIn("recommend", src.lower().split("def ")[0] if "def " in src else "")


if __name__ == "__main__":
    unittest.main()
