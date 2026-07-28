"""测试盘口变化画像分类"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.odds_profile import _classify_pattern


class TestPatternClassification(unittest.TestCase):

    def test_continuous_upgrade(self):
        """持续升盘"""
        self.assertEqual(_classify_pattern([0.25, 0.25, 0.25], 0.75), "持续升盘")

    def test_continuous_downgrade(self):
        """持续降盘"""
        self.assertEqual(_classify_pattern([-0.25, -0.25], -0.5), "持续降盘")

    def test_stable(self):
        """稳定"""
        self.assertEqual(_classify_pattern([0, 0, 0], 0), "稳定")

    def test_upgrade_then_fallback(self):
        """升后回落"""
        self.assertEqual(_classify_pattern([0.25, -0.25], 0), "升后回落")

    def test_downgrade_then_recovery(self):
        """降后回升"""
        self.assertEqual(_classify_pattern([-0.25, 0.25], 0), "降后回升")

    def test_oscillation(self):
        """震荡"""
        self.assertEqual(_classify_pattern([0.25, -0.25, 0.25, -0.25], 0), "震荡")

    def test_single_step(self):
        """单步变化"""
        result = _classify_pattern([0.5], 0.5)
        self.assertIn(result, ("持续升盘", "持续降盘"))


if __name__ == "__main__":
    unittest.main()
