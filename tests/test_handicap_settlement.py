"""测试亚盘结算逻辑: 赢盘/输盘/走盘/半赢半输"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.odds_math import handicap_to_number


class TestHandicapSettlement(unittest.TestCase):
    """亚盘输赢结算"""

    def _settle(self, handicap_str, home_goals, away_goals):
        """模拟让球结算: 返回 home_cover / away_cover / push"""
        hdp = handicap_to_number(handicap_str)
        adjusted_home = home_goals - hdp
        if adjusted_home > away_goals:
            return "home_cover"
        elif adjusted_home < away_goals:
            return "away_cover"
        else:
            return "push"

    # === 基本赢盘/输盘 ===

    def test_home_cover_basic(self):
        """主让0.5, 主队赢1球 → 赢盘"""
        self.assertEqual(self._settle("主让0.5", 1, 0), "home_cover")

    def test_home_cover_big_win(self):
        """主让1, 主队赢3球 → 赢盘"""
        self.assertEqual(self._settle("主让1", 3, 0), "home_cover")

    def test_away_cover_basic(self):
        """主让0.5, 客队赢 → 输盘"""
        self.assertEqual(self._settle("主让0.5", 0, 1), "away_cover")

    def test_away_cover_draw(self):
        """主让0.5, 平局 → 输盘(主队让不起)"""
        self.assertEqual(self._settle("主让0.5", 1, 1), "away_cover")

    # === 走盘 ===

    def test_push_integer_handicap(self):
        """主让1, 主队恰好赢1球 → 走盘"""
        self.assertEqual(self._settle("主让1", 1, 0), "push")

    def test_push_level(self):
        """平手, 平局 → 走盘"""
        self.assertEqual(self._settle("平手", 1, 1), "push")

    def test_push_away_handicap(self):
        """客让1, 客队恰好赢1球 → 走盘"""
        self.assertEqual(self._settle("客让1", 0, 1), "push")

    # === 半球盘(无走盘可能) ===

    def test_half_ball_no_push(self):
        """主让0.5, 任何比分都不会走盘"""
        results = set()
        for hg in range(5):
            for ag in range(5):
                r = self._settle("主让0.5", hg, ag)
                results.add(r)
        self.assertNotIn("push", results)

    # === 半赢半输(quarter ball) ===

    def test_quarter_ball_home(self):
        """主让0.25(平手/半球), 主队赢1球 → 全赢"""
        # 0.25盘: 主队赢 → 全赢
        self.assertEqual(self._settle("主让0.25", 1, 0), "home_cover")

    def test_quarter_ball_push_scenario(self):
        """主让0.25, 平局 → 半输(简化为away_cover)"""
        # 0.25盘平局: 一半走盘一半输 → 简化为away_cover
        self.assertEqual(self._settle("主让0.25", 0, 0), "away_cover")

    # === 客让盘 ===

    def test_away_handicap_cover(self):
        """客让0.5, 客队赢1球 → 客队赢盘(away_cover)"""
        self.assertEqual(self._settle("客让0.5", 0, 1), "away_cover")

    def test_away_handicap_home_cover(self):
        """客让0.5, 主队赢 → 主队赢盘(home_cover)"""
        self.assertEqual(self._settle("客让0.5", 1, 0), "home_cover")

    # === 深盘 ===

    def test_deep_handicap_cover(self):
        """主让2.5, 主队赢3球 → 赢盘"""
        self.assertEqual(self._settle("主让2.5", 3, 0), "home_cover")

    def test_deep_handicap_fail(self):
        """主让2.5, 主队只赢2球 → 输盘"""
        self.assertEqual(self._settle("主让2.5", 2, 0), "away_cover")


class TestHandicapToNumber(unittest.TestCase):
    """盘口文字转数值"""

    def test_home_handicap(self):
        self.assertEqual(handicap_to_number("主让0.5"), 0.5)
        self.assertEqual(handicap_to_number("主让1"), 1.0)
        self.assertEqual(handicap_to_number("主让2.5"), 2.5)

    def test_away_handicap(self):
        self.assertEqual(handicap_to_number("客让0.5"), -0.5)
        self.assertEqual(handicap_to_number("客让1"), -1.0)

    def test_level(self):
        self.assertEqual(handicap_to_number("平手"), 0.0)

    def test_empty(self):
        self.assertEqual(handicap_to_number(""), 0.0)
        self.assertEqual(handicap_to_number(None), 0.0)

    def test_numeric_format(self):
        self.assertEqual(handicap_to_number("-0.5"), -0.5)
        self.assertEqual(handicap_to_number("+0.5"), 0.5)


if __name__ == "__main__":
    unittest.main()
