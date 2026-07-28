"""测试handicap_model盘口解析与odds_math完全一致"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.odds_math import handicap_to_number
from models.handicap_model import HandicapModel


class TestHandicapModelParsing(unittest.TestCase):
    """验证handicap_model使用的解析结果与odds_math完全一致"""

    def setUp(self):
        self.model = HandicapModel()

    def _assert_consistent(self, text):
        """模型内部解析必须与odds_math完全一致"""
        expected = handicap_to_number(text)
        actual = self.model._handicap_to_number(text)
        self.assertEqual(actual, expected,
                        f"输入 '{text}': model={actual}, odds_math={expected}")

    # === 负号前缀 ===
    def test_negative_05(self):
        self._assert_consistent("-0.5")

    def test_positive_05(self):
        self._assert_consistent("+0.5")

    def test_negative_025(self):
        self._assert_consistent("-0.25")

    def test_positive_075(self):
        self._assert_consistent("+0.75")

    # === 中文格式 ===
    def test_home_half(self):
        self._assert_consistent("主让半球")

    def test_away_half(self):
        self._assert_consistent("客让半球")

    def test_home_05(self):
        self._assert_consistent("主让0.5")

    def test_away_05(self):
        self._assert_consistent("客让0.5")

    def test_shou_05(self):
        """受让0.5 = 客让0.5"""
        self._assert_consistent("受让0.5")

    def test_ping_shou(self):
        """平手"""
        self._assert_consistent("平手")

    def test_ping_ban(self):
        """平/半 = 0.25"""
        self._assert_consistent("平/半")

    def test_ban_yi(self):
        """半/一 = 0.75"""
        self._assert_consistent("半/一")

    # === 边界情况 ===
    def test_none(self):
        self._assert_consistent(None)

    def test_empty_string(self):
        self._assert_consistent("")

    def test_garbage_text(self):
        self._assert_consistent("abcxyz")

    def test_integer(self):
        self._assert_consistent("主让1")

    def test_deep_handicap(self):
        self._assert_consistent("主让2.5")

    def test_away_deep(self):
        self._assert_consistent("客让1.5")

    # === handicap_diff 一致性 ===
    def test_diff_consistent(self):
        """_handicap_diff也应与odds_math一致"""
        diff = self.model._handicap_diff("主让0.5", "主让0.75")
        expected = handicap_to_number("主让0.75") - handicap_to_number("主让0.5")
        self.assertAlmostEqual(diff, expected)

    def test_diff_downgrade(self):
        diff = self._model_diff("主让1", "主让0.5")
        self.assertLess(diff, 0)

    def _model_diff(self, open_hdp, curr_hdp):
        return self.model._handicap_diff(open_hdp, curr_hdp)


if __name__ == "__main__":
    unittest.main()
