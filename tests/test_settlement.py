"""唯一亚盘结算函数 settle_asian_handicap 测试
覆盖 win/half_win/push/half_loss/loss/invalid/no_bet 与全部盘口类型。
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.odds_math import settle_asian_handicap, hit_to_pnl


class TestSettleAsianHandicapFixed(unittest.TestCase):
    """用户指定的8个固定用例(必须全部通过)"""

    def test_fixed_cases(self):
        cases = [
            # (direction, handicap, home, away, expected)
            ("home", "主让1.5", 1, 0, "loss"),       # 主让-1.5, 1:0, home → loss
            ("home", "主让1", 1, 0, "push"),          # 主让-1, 1:0, home → push
            ("home", "主让0.75", 1, 0, "half_win"),   # 主让-0.75, 1:0, home → half_win
            ("home", "主让0.25", 0, 0, "half_loss"),  # 主让-0.25, 0:0, home → half_loss
            ("home", "客让0.25", 0, 0, "half_win"),   # 主受让+0.25, 0:0, home → half_win
            ("away", "客让0.25", 0, 0, "half_loss"),  # 客让0.25, 平局, away → half_loss
            ("away", "客让0.75", 0, 1, "half_win"),   # 客让0.75, 客胜1球, away → half_win
            ("away", "客让1", 0, 1, "push"),          # 客让1, 客胜1球, away → push
        ]
        for direction, hdp, hs, as_, expected in cases:
            with self.subTest(direction=direction, handicap=hdp, score=f"{hs}:{as_}"):
                got = settle_asian_handicap(direction, hdp, hs, as_)
                self.assertEqual(got, expected,
                                 f"{direction} {hdp} {hs}:{as_} → {got}, 期望{expected}")


class TestSettleAsianHandicapCoverage(unittest.TestCase):
    """全盘口类型覆盖"""

    def test_no_bet_and_invalid(self):
        self.assertEqual(settle_asian_handicap("neutral", "主让0.5", 1, 0), "no_bet")
        self.assertEqual(settle_asian_handicap(None, "主让0.5", 1, 0), "no_bet")
        self.assertEqual(settle_asian_handicap("", "主让0.5", 1, 0), "no_bet")
        self.assertEqual(settle_asian_handicap("draw", "主让0.5", 1, 0), "invalid")

    def test_level_handicap(self):
        # 平手盘
        self.assertEqual(settle_asian_handicap("home", "平手", 1, 0), "win")
        self.assertEqual(settle_asian_handicap("home", "平手", 0, 1), "loss")
        self.assertEqual(settle_asian_handicap("home", "平手", 1, 1), "push")
        self.assertEqual(settle_asian_handicap("away", "平手", 0, 1), "win")
        self.assertEqual(settle_asian_handicap("away", "平手", 1, 1), "push")

    def test_half_ball_no_push(self):
        # 半球盘不可能走盘
        self.assertEqual(settle_asian_handicap("home", "主让0.5", 1, 0), "win")
        self.assertEqual(settle_asian_handicap("home", "主让0.5", 0, 0), "loss")
        self.assertEqual(settle_asian_handicap("home", "主让0.5", 1, 1), "loss")
        self.assertEqual(settle_asian_handicap("away", "客让0.5", 0, 1), "win")
        self.assertEqual(settle_asian_handicap("away", "客让0.5", 0, 0), "loss")

    def test_quarter_ball(self):
        # 0.25盘
        self.assertEqual(settle_asian_handicap("home", "主让0.25", 1, 0), "win")
        self.assertEqual(settle_asian_handicap("home", "主让0.25", 0, 0), "half_loss")
        self.assertEqual(settle_asian_handicap("away", "客让0.25", 0, 1), "win")
        # 0.75盘
        self.assertEqual(settle_asian_handicap("home", "主让0.75", 1, 0), "half_win")
        self.assertEqual(settle_asian_handicap("home", "主让0.75", 2, 0), "win")
        self.assertEqual(settle_asian_handicap("home", "主让0.75", 0, 0), "loss")

    def test_deep_handicap(self):
        # 1.25 / 1.5 / 2 盘
        self.assertEqual(settle_asian_handicap("home", "主让1.25", 2, 0), "win")       # margin=0.75全赢
        self.assertEqual(settle_asian_handicap("home", "主让1.25", 1, 0), "half_loss")  # margin=-0.25半输
        self.assertEqual(settle_asian_handicap("home", "主让1.5", 2, 0), "win")
        self.assertEqual(settle_asian_handicap("home", "主让1.5", 1, 0), "loss")
        self.assertEqual(settle_asian_handicap("home", "主让2", 2, 0), "push")
        self.assertEqual(settle_asian_handicap("home", "主让2", 3, 0), "win")
        self.assertEqual(settle_asian_handicap("away", "客让1.5", 0, 2), "win")
        self.assertEqual(settle_asian_handicap("away", "客让1.5", 0, 1), "loss")

    def test_away_symmetry(self):
        # away方向应与home方向对称
        # 客让0.5, 客胜2球 → away全赢
        self.assertEqual(settle_asian_handicap("away", "客让0.5", 0, 2), "win")
        # 客让0.25, 客胜1球 → away全赢 (margin away = 1-0.25=0.75>0.25)
        self.assertEqual(settle_asian_handicap("away", "客让0.25", 0, 1), "win")


class TestHitToPnl(unittest.TestCase):
    """PnL映射"""

    def test_pnl_map(self):
        self.assertEqual(hit_to_pnl("win"), 1.0)
        self.assertEqual(hit_to_pnl("half_win"), 0.5)
        self.assertEqual(hit_to_pnl("push"), 0.0)
        self.assertEqual(hit_to_pnl("half_loss"), -0.5)
        self.assertEqual(hit_to_pnl("loss"), -1.0)
        self.assertIsNone(hit_to_pnl("no_bet"))
        self.assertIsNone(hit_to_pnl("invalid"))
        self.assertIsNone(hit_to_pnl("unknown"))


if __name__ == "__main__":
    unittest.main()
