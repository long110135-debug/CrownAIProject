"""盘口字符串解析参数化测试
覆盖数据库中实际出现的每一种格式 + 中文术语 + 解析失败检测。
主队让球统一为正数，客队让球统一为负数。
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.odds_math import handicap_to_number, parse_handicap_strict


# 数据库 odds_timeline/prediction_history 实际出现的格式 → 期望主队视角数值
DB_FORMATS = [
    # x/y 分数格式(此前解析错误的关键修复)
    ("-0/0.5", -0.25),
    ("+0/0.5", 0.25),
    ("-1/1.5", -1.25),
    ("+1/1.5", 1.25),
    ("-1.5/2", -1.75),
    ("-0.5/1", -0.75),
    ("+0.5/1", 0.75),
    # 中文方向前缀
    ("客让0.25", -0.25),
    ("客让0.5", -0.5),
    ("客让1.0", -1.0),
    ("主让1.75", 1.75),
    ("主让2.75", 2.75),
    ("主让3.25", 3.25),
    # 平手/纯数字/符号
    ("平手", 0.0),
    ("0", 0.0),
    ("-0.5", -0.5),
    ("-1", -1.0),
    ("-1.5", -1.5),
    ("-2", -2.0),
    ("+0.5", 0.5),
    ("+1", 1.0),
]

# 中文术语(DB未出现但需支持)
CN_TERMS = [
    ("半球", 0.5),
    ("平半", 0.25),
    ("半一", 0.75),
    ("一球", 1.0),
    ("球半", 1.5),
    ("两球", 2.0),
    ("主让半球", 0.5),
    ("客让半球", -0.5),
    ("受半球", -0.5),
    ("主让平半", 0.25),
    ("客让平半", -0.25),
    ("受平半", -0.25),
    ("主让球半", 1.5),
    ("客让球半", -1.5),
]

# 解析失败(应返回None, 不得静默归0)
UNPARSEABLE = ["", None, "abc", "未知盘口", "盘口", "x/y"]


class TestHandicapParseDBFormats(unittest.TestCase):
    """数据库实际出现的每一种格式都必须正确解析"""

    def test_db_formats(self):
        for s, expected in DB_FORMATS:
            with self.subTest(format=s):
                got = handicap_to_number(s)
                self.assertAlmostEqual(got, expected, places=3,
                                       msg=f"{s} → {got}, 期望{expected}")

    def test_chinese_terms(self):
        for s, expected in CN_TERMS:
            with self.subTest(format=s):
                got = handicap_to_number(s)
                self.assertAlmostEqual(got, expected, places=3,
                                       msg=f"{s} → {got}, 期望{expected}")

    def test_fraction_is_average(self):
        # x/y 格式必须取两数均值, 不能只取第一个
        self.assertAlmostEqual(handicap_to_number("-0/0.5"), -0.25)
        self.assertAlmostEqual(handicap_to_number("-1/1.5"), -1.25)
        self.assertAlmostEqual(handicap_to_number("+0.5/1"), 0.75)


class TestHandicapParseStrict(unittest.TestCase):
    """严格解析: 失败返回None, 不静默归0"""

    def test_unparseable_returns_none(self):
        for s in UNPARSEABLE:
            with self.subTest(format=repr(s)):
                self.assertIsNone(parse_handicap_strict(s),
                                  f"{repr(s)} 应返回None")

    def test_valid_returns_float(self):
        self.assertEqual(parse_handicap_strict("平手"), 0.0)
        self.assertEqual(parse_handicap_strict("-0/0.5"), -0.25)
        self.assertEqual(parse_handicap_strict("客让0.25"), -0.25)

    def test_empty_not_silent_zero(self):
        # 空字符串不应被当作平手(0), 应可检测为缺失
        self.assertIsNone(parse_handicap_strict(""))
        # 但向后兼容的 handicap_to_number 仍返回0.0
        self.assertEqual(handicap_to_number(""), 0.0)


class TestHandicapHomePerspective(unittest.TestCase):
    """主队让球为正, 客队让球为负"""

    def test_home_giving_positive(self):
        self.assertGreater(handicap_to_number("主让0.5"), 0)
        self.assertGreater(handicap_to_number("+1"), 0)
        self.assertGreater(handicap_to_number("0.5"), 0)

    def test_away_giving_negative(self):
        self.assertLess(handicap_to_number("客让0.5"), 0)
        self.assertLess(handicap_to_number("-1"), 0)
        self.assertLess(handicap_to_number("受0.5"), 0)

    def test_symmetry(self):
        self.assertAlmostEqual(handicap_to_number("主让0.5"),
                               -handicap_to_number("客让0.5"))


if __name__ == "__main__":
    unittest.main()
