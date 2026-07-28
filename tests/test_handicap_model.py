"""测试盘口模型"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.handicap_model import HandicapModel


class TestHandicapModel(unittest.TestCase):

    def setUp(self):
        self.model = HandicapModel()

    def test_output_format(self):
        """输出必须包含标准字段"""
        result = self.model.analyze({
            "odds": {"asian_handicap": "主让0.5", "home_odds": 0.92, "away_odds": 0.95,
                     "open_handicap": "主让0.5", "current_handicap": "主让0.5",
                     "change_type": "不变", "over_under": "", "over_odds": 0, "under_odds": 0}
        })
        self.assertIn("model", result)
        self.assertIn("score", result)
        self.assertIn("direction", result)
        self.assertIn("confidence", result)
        self.assertEqual(result["model"], "handicap")

    def test_no_data_returns_neutral(self):
        """无盘口数据 → neutral"""
        result = self.model.analyze({"odds": {}})
        self.assertEqual(result["direction"], "neutral")
        self.assertEqual(result["score"], 0)

    def test_upgrade_signal(self):
        """升盘 → home方向"""
        result = self.model.analyze({
            "odds": {"asian_handicap": "主让0.75", "home_odds": 0.90, "away_odds": 0.95,
                     "open_handicap": "主让0.5", "current_handicap": "主让0.75",
                     "change_type": "升盘", "over_under": "", "over_odds": 0, "under_odds": 0}
        })
        self.assertEqual(result["direction"], "home")

    def test_downgrade_signal(self):
        """降盘 → away方向"""
        result = self.model.analyze({
            "odds": {"asian_handicap": "主让0.25", "home_odds": 0.95, "away_odds": 0.90,
                     "open_handicap": "主让0.5", "current_handicap": "主让0.25",
                     "change_type": "降盘", "over_under": "", "over_odds": 0, "under_odds": 0}
        })
        self.assertEqual(result["direction"], "away")

    def test_weight_from_config(self):
        """权重从config读取"""
        self.assertEqual(self.model.weight, 0.30)

    def test_no_db_access(self):
        """模型不访问数据库"""
        import inspect
        src = inspect.getsource(HandicapModel)
        self.assertNotIn("get_connection", src)
        self.assertNotIn("from utils.database", src)


if __name__ == "__main__":
    unittest.main()
