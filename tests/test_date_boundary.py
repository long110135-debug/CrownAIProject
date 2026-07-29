"""测试normalize_date跨年边界 + parse_match_time + infer_year"""
import sys
import os
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.helpers import normalize_date, parse_match_time, infer_year


class TestInferYear(unittest.TestCase):
    """半年边界规则"""

    def test_dec_31_sees_jan_as_next_year(self):
        """2026-12-31解析01月 → 2027"""
        ref = datetime(2026, 12, 31)
        self.assertEqual(infer_year(1, ref), 2027)

    def test_jan_1_sees_dec_as_prev_year(self):
        """2027-01-01解析12月 → 2026"""
        ref = datetime(2027, 1, 1)
        self.assertEqual(infer_year(12, ref), 2026)

    def test_july_sees_july_same_year(self):
        """2026-07-15解析07月 → 2026"""
        ref = datetime(2026, 7, 15)
        self.assertEqual(infer_year(7, ref), 2026)

    def test_jan_sees_feb_same_year(self):
        """2026-01-10解析02月 → 2026(差1个月，不跨年)"""
        ref = datetime(2026, 1, 10)
        self.assertEqual(infer_year(2, ref), 2026)

    def test_july_sees_jan_next_year(self):
        """2026-07-15解析01月 → 2027(差-6，刚好不跨)"""
        ref = datetime(2026, 7, 15)
        self.assertEqual(infer_year(1, ref), 2027)

    def test_july_sees_aug_same_year(self):
        """2026-07-15解析08月 → 2026"""
        ref = datetime(2026, 7, 15)
        self.assertEqual(infer_year(8, ref), 2026)

    def test_aug_sees_jan_next_year(self):
        """2026-08-01解析01月 → 2027(差-7，跨年)"""
        ref = datetime(2026, 8, 1)
        self.assertEqual(infer_year(1, ref), 2027)

    def test_feb_sees_dec_prev_year(self):
        """2026-02-01解析12月 → 2025(差10>6，上一年)"""
        ref = datetime(2026, 2, 1)
        self.assertEqual(infer_year(12, ref), 2025)


class TestNormalizeDateBoundary(unittest.TestCase):
    """normalize_date跨年边界"""

    def test_dec31_jan01(self):
        """2026-12-31解析'01月01日' → 2027-01-01"""
        ref = datetime(2026, 12, 31)
        self.assertEqual(normalize_date("01月01日", ref), "2027-01-01")

    def test_jan01_dec31(self):
        """2027-01-01解析'12月31日' → 2026-12-31"""
        ref = datetime(2027, 1, 1)
        self.assertEqual(normalize_date("12月31日", ref), "2026-12-31")

    def test_normal_same_year(self):
        """2026-07-15解析'07月20日' → 2026-07-20"""
        ref = datetime(2026, 7, 15)
        self.assertEqual(normalize_date("07月20日", ref), "2026-07-20")

    def test_jan_sees_feb(self):
        """2026-01-10解析'02月01日' → 2026-02-01"""
        ref = datetime(2026, 1, 10)
        self.assertEqual(normalize_date("02月01日", ref), "2026-02-01")

    def test_leap_year_feb29(self):
        """闰年2月29日合法"""
        ref = datetime(2028, 1, 15)  # 2028是闰年
        self.assertEqual(normalize_date("02月29日", ref), "2028-02-29")

    def test_non_leap_feb29_safe_fail(self):
        """非闰年2月29日安全失败，返回原字符串"""
        ref = datetime(2026, 1, 15)  # 2026不是闰年
        self.assertEqual(normalize_date("02月29日", ref), "02月29日")

    def test_iso_passthrough(self):
        """ISO格式原样返回"""
        self.assertEqual(normalize_date("2026-07-28"), "2026-07-28")

    def test_empty_string(self):
        self.assertEqual(normalize_date(""), "")

    def test_garbage(self):
        self.assertEqual(normalize_date("unknown"), "unknown")

    def test_single_digit(self):
        """单位数月日"""
        ref = datetime(2026, 7, 1)
        self.assertEqual(normalize_date("7月5日", ref), "2026-07-05")


class TestParseMatchTimeBoundary(unittest.TestCase):
    """parse_match_time跨年(返回aware datetime: 中文→Shanghai, ISO→UTC)"""

    def test_dec31_jan01_with_time(self):
        from utils.timeutil import SHANGHAI
        ref = datetime(2026, 12, 31)
        result = parse_match_time("01月01日 20:00", ref)
        self.assertEqual(result, datetime(2027, 1, 1, 20, 0, tzinfo=SHANGHAI))

    def test_jan01_dec31_with_time(self):
        from utils.timeutil import SHANGHAI
        ref = datetime(2027, 1, 1)
        result = parse_match_time("12月31日 22:30", ref)
        self.assertEqual(result, datetime(2026, 12, 31, 22, 30, tzinfo=SHANGHAI))

    def test_iso_format(self):
        from utils.timeutil import UTC
        result = parse_match_time("2026-07-28 15:00")
        self.assertEqual(result, datetime(2026, 7, 28, 15, 0, tzinfo=UTC))

    def test_none_input(self):
        self.assertIsNone(parse_match_time(None))

    def test_empty_input(self):
        self.assertIsNone(parse_match_time(""))

    def test_invalid_date(self):
        """非法日期安全返回None"""
        ref = datetime(2026, 1, 15)
        self.assertIsNone(parse_match_time("02月30日 20:00", ref))


class TestMatchIdConsistency(unittest.TestCase):
    """确认所有match_id路径使用相同normalize_date"""

    def test_collector_uses_helpers(self):
        """crown_odds_collector.normalize_date委托到helpers"""
        from scraper.crown_odds_collector import normalize_date as collector_normalize
        from utils.helpers import normalize_date as helpers_normalize
        # 两者应产生相同结果
        self.assertEqual(collector_normalize("07月28日"), helpers_normalize("07月28日"))
        self.assertEqual(collector_normalize("2026-07-28"), helpers_normalize("2026-07-28"))


if __name__ == "__main__":
    unittest.main()
