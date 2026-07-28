"""测试odds_math: 升盘/降盘/CLV判断的唯一实现"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.odds_math import handicap_to_number, number_to_handicap, compute_change, calc_clv


class TestComputeChange(unittest.TestCase):

    def test_upgrade(self):
        """主让0.5→主让0.75 = 升盘"""
        c = compute_change("主让0.5", "主让0.75", 0.95, 0.90, 0.90, 0.95)
        self.assertEqual(c["change_type"], "升盘")
        self.assertEqual(c["signal"], "home_support")
        self.assertGreater(c["significance"], 0)

    def test_downgrade(self):
        """主让0.75→主让0.5 = 降盘"""
        c = compute_change("主让0.75", "主让0.5", 0.90, 0.95, 0.95, 0.90)
        self.assertEqual(c["change_type"], "降盘")
        self.assertEqual(c["signal"], "away_support")

    def test_water_anomaly(self):
        """盘口不变但水位大幅变化 = 水位异动"""
        c = compute_change("主让0.5", "主让0.5", 0.95, 0.85, 0.90, 1.00)
        self.assertEqual(c["change_type"], "水位异动")
        self.assertEqual(c["signal"], "home_support")

    def test_no_change(self):
        """完全不变"""
        c = compute_change("主让0.5", "主让0.5", 0.95, 0.95, 0.90, 0.90)
        self.assertEqual(c["change_type"], "不变")
        self.assertEqual(c["signal"], "neutral")


class TestCalcCLV(unittest.TestCase):

    def test_positive_clv(self):
        """推荐时主让0.75, 收盘主让0.5 → 正CLV(推荐时盘口更深)"""
        clv = calc_clv("主让0.75", "主让0.5", 0.90, 0.95)
        self.assertGreater(clv["clv_handicap"], 0)
        self.assertTrue(clv["positive"])

    def test_negative_clv(self):
        """推荐时主让0.5, 收盘主让0.75 → 负CLV"""
        clv = calc_clv("主让0.5", "主让0.75", 0.95, 0.90)
        self.assertLess(clv["clv_handicap"], 0)
        self.assertFalse(clv["positive"])

    def test_zero_clv(self):
        """盘口相同 → CLV=0"""
        clv = calc_clv("主让0.5", "主让0.5", 0.95, 0.95)
        self.assertEqual(clv["clv_handicap"], 0)


class TestNumberToHandicap(unittest.TestCase):

    def test_positive(self):
        self.assertEqual(number_to_handicap(0.5), "主让0.5")

    def test_negative(self):
        self.assertEqual(number_to_handicap(-1.0), "客让1.0")

    def test_zero(self):
        self.assertEqual(number_to_handicap(0), "平手")


if __name__ == "__main__":
    unittest.main()
