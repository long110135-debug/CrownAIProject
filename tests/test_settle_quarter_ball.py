"""测试四分之一盘精确结算: half_win / half_loss"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from settle import _calc_handicap_result


class TestQuarterBallSettlement(unittest.TestCase):
    """四分之一盘(0.25/0.75/1.25)的半赢半输"""

    def _settle(self, handicap_str, home_goals, away_goals):
        pred = {"asian_live": handicap_str, "asian_open": handicap_str}
        return _calc_handicap_result(pred, home_goals, away_goals)

    # === 主让0.25(平手/半球) ===

    def test_025_home_win_full(self):
        """主让0.25, 主队赢1球 → 全赢"""
        self.assertEqual(self._settle("主让0.25", 1, 0), "home_cover")

    def test_025_draw_half_loss(self):
        """主让0.25, 平局 → 半输(一半走盘一半输)"""
        self.assertEqual(self._settle("主让0.25", 0, 0), "half_loss")

    def test_025_away_win_full(self):
        """主让0.25, 客队赢 → 全输"""
        self.assertEqual(self._settle("主让0.25", 0, 1), "away_cover")

    # === 主让0.75(半球/一球) ===

    def test_075_home_win_2_full(self):
        """主让0.75, 主队赢2球 → 全赢"""
        self.assertEqual(self._settle("主让0.75", 2, 0), "home_cover")

    def test_075_home_win_1_half_win(self):
        """主让0.75, 主队赢1球 → 半赢(一半赢一半走)"""
        self.assertEqual(self._settle("主让0.75", 1, 0), "half_win")

    def test_075_draw_full_loss(self):
        """主让0.75, 平局 → 全输"""
        self.assertEqual(self._settle("主让0.75", 0, 0), "away_cover")

    # === 主让1.25(一球/球半) ===

    def test_125_home_win_2_full(self):
        """主让1.25, 主队赢2球 → 全赢"""
        self.assertEqual(self._settle("主让1.25", 2, 0), "home_cover")

    def test_125_home_win_1_half_loss(self):
        """主让1.25, 主队赢1球 → 半输(一半走一半输)"""
        self.assertEqual(self._settle("主让1.25", 1, 0), "half_loss")

    def test_125_draw_full_loss(self):
        """主让1.25, 平局 → 全输"""
        self.assertEqual(self._settle("主让1.25", 0, 0), "away_cover")

    # === 客让0.25 ===

    def test_away_025_away_win_full(self):
        """客让0.25, 客队赢1球 → 客队全赢(away_cover)"""
        self.assertEqual(self._settle("客让0.25", 0, 1), "away_cover")

    def test_away_025_draw_half_win(self):
        """客让0.25, 平局 → 主队半赢(一半走一半赢)"""
        self.assertEqual(self._settle("客让0.25", 0, 0), "half_win")

    # === 对比: 半球盘无半赢半输 ===

    def test_050_no_half(self):
        """主让0.5, 任何比分都不产生half_win/half_loss"""
        for hg in range(4):
            for ag in range(4):
                result = self._settle("主让0.5", hg, ag)
                self.assertNotIn(result, ("half_win", "half_loss"),
                               f"主让0.5 {hg}-{ag} 不应有半赢半输, 得到{result}")

    # === 对比: 整数盘有走盘 ===

    def test_100_push(self):
        """主让1, 主队恰好赢1球 → 走盘"""
        self.assertEqual(self._settle("主让1", 1, 0), "push")

    def test_100_no_half(self):
        """主让1, 不产生half_win/half_loss"""
        for hg in range(4):
            for ag in range(4):
                result = self._settle("主让1", hg, ag)
                self.assertNotIn(result, ("half_win", "half_loss"))


if __name__ == "__main__":
    unittest.main()
