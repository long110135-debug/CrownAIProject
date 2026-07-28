"""测试市场模型: 诱热检测/方向/水位信号/无数据"""
import sys
import os
import unittest
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.market_model import MarketModel


class TestMarketModelOutput(unittest.TestCase):
    """输出格式"""

    def setUp(self):
        self.model = MarketModel()
        self.match_data = {
            "odds": {"home_odds": 0.92, "away_odds": 0.95, "current_handicap": "主让0.5",
                     "change_type": "不变"},
            "market_data": {},
        }

    def test_output_has_required_fields(self):
        result = self.model.analyze(self.match_data)
        for field in ("model", "score", "direction", "confidence", "reasoning", "details"):
            self.assertIn(field, result)

    def test_model_name(self):
        result = self.model.analyze(self.match_data)
        self.assertEqual(result["model"], "market")

    def test_details_structure(self):
        result = self.model.analyze(self.match_data)
        self.assertIn("heat", result["details"])
        self.assertIn("trap", result["details"])
        self.assertIn("flow", result["details"])


class TestMarketModelTrapDetection(unittest.TestCase):
    """诱热检测"""

    def setUp(self):
        self.model = MarketModel()

    def test_high_water_trap(self):
        """让球方水位>1.0 → 诱热信号"""
        result = self.model.analyze({
            "odds": {"home_odds": 1.10, "away_odds": 0.80, "current_handicap": "主让1",
                     "change_type": "不变"},
            "market_data": {"heat_ratio": {"home": 0.72, "away": 0.28}},
        })
        trap = result["details"]["trap"]
        self.assertTrue(trap["is_trap"])
        self.assertGreater(trap["trap_risk"], 0)

    def test_heat_no_upgrade_trap(self):
        """热度高但盘口不升 + 高水 → 诱热(trap_risk>=40)"""
        result = self.model.analyze({
            "odds": {"home_odds": 1.05, "away_odds": 0.85, "current_handicap": "主让0.5",
                     "change_type": "不变"},
            "market_data": {"heat_ratio": {"home": 0.75, "away": 0.25}},
        })
        trap = result["details"]["trap"]
        self.assertTrue(trap["is_trap"])

    def test_no_trap_normal(self):
        """正常盘口 → 无诱热"""
        result = self.model.analyze({
            "odds": {"home_odds": 0.90, "away_odds": 0.95, "current_handicap": "主让0.5",
                     "change_type": "升盘"},
            "market_data": {},
        })
        trap = result["details"]["trap"]
        self.assertFalse(trap["is_trap"])

    def test_trap_reverses_direction(self):
        """诱热时方向取反(热门方是home → 方向给away)"""
        result = self.model.analyze({
            "odds": {"home_odds": 1.15, "away_odds": 0.75, "current_handicap": "主让1",
                     "change_type": "不变"},
            "market_data": {"heat_ratio": {"home": 0.80, "away": 0.20}},
        })
        self.assertEqual(result["direction"], "away")


class TestMarketModelFlow(unittest.TestCase):
    """资金流向"""

    def setUp(self):
        self.model = MarketModel()

    def test_home_low_water_flow(self):
        """主队低水 → 资金流向主队"""
        result = self.model.analyze({
            "odds": {"home_odds": 0.80, "away_odds": 1.05, "current_handicap": "主让0.5",
                     "change_type": "不变"},
            "market_data": {},
        })
        flow = result["details"]["flow"]
        self.assertEqual(flow["flow_direction"], "home")

    def test_away_low_water_flow(self):
        """客队低水 → 资金流向客队"""
        result = self.model.analyze({
            "odds": {"home_odds": 1.05, "away_odds": 0.80, "current_handicap": "平手",
                     "change_type": "不变"},
            "market_data": {},
        })
        flow = result["details"]["flow"]
        self.assertEqual(flow["flow_direction"], "away")

    def test_balanced_water(self):
        """水位接近 → 均衡"""
        result = self.model.analyze({
            "odds": {"home_odds": 0.93, "away_odds": 0.94, "current_handicap": "主让0.5",
                     "change_type": "不变"},
            "market_data": {},
        })
        flow = result["details"]["flow"]
        self.assertEqual(flow["flow_direction"], "balanced")


class TestMarketModelNoData(unittest.TestCase):
    """无数据"""

    def setUp(self):
        self.model = MarketModel()

    def test_no_odds(self):
        result = self.model.analyze({"odds": {}, "market_data": {}})
        self.assertEqual(result["direction"], "neutral")
        self.assertEqual(result["score"], 0)
        self.assertTrue(result["details"].get("no_data"))

    def test_missing_odds_key(self):
        result = self.model.analyze({})
        self.assertEqual(result["direction"], "neutral")


class TestMarketModelConstraints(unittest.TestCase):
    """架构约束"""

    def setUp(self):
        self.model = MarketModel()

    def test_weight_from_config(self):
        self.assertEqual(self.model.weight, 0.20)

    def test_no_db_access(self):
        src = inspect.getsource(MarketModel)
        self.assertNotIn("get_connection", src)
        self.assertNotIn("from utils.database", src)


if __name__ == "__main__":
    unittest.main()
