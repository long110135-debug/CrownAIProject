"""测试实力模型: 输出格式/方向判断/无数据降级/权重/不访问DB"""
import sys
import os
import unittest
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.strength_model import StrengthModel


class TestStrengthModelOutput(unittest.TestCase):
    """输出格式必须符合标准"""

    def setUp(self):
        self.model = StrengthModel()
        self.match_data = {
            "home_team": "阿森纳", "away_team": "切尔西", "league": "英超",
            "home_stats": {"rank": 2, "played": 20, "wins": 14, "goals_for": 45, "goals_against": 15,
                          "xg": 2.1, "xga": 0.8, "home_wins": 9, "recent_form": "WWWDW"},
            "away_stats": {"rank": 8, "played": 20, "wins": 8, "goals_for": 25, "goals_against": 28,
                          "xg": 1.2, "xga": 1.4, "away_wins": 3, "recent_form": "LDWLL"},
        }

    def test_output_has_required_fields(self):
        result = self.model.analyze(self.match_data)
        for field in ("model", "score", "direction", "confidence", "reasoning", "details"):
            self.assertIn(field, result)

    def test_model_name(self):
        result = self.model.analyze(self.match_data)
        self.assertEqual(result["model"], "strength")

    def test_score_range(self):
        result = self.model.analyze(self.match_data)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)

    def test_direction_valid(self):
        result = self.model.analyze(self.match_data)
        self.assertIn(result["direction"], ("home", "away", "draw", "neutral"))

    def test_confidence_range(self):
        result = self.model.analyze(self.match_data)
        self.assertGreaterEqual(result["confidence"], 0)
        self.assertLessEqual(result["confidence"], 100)


class TestStrengthModelDirection(unittest.TestCase):
    """方向判断逻辑"""

    def setUp(self):
        self.model = StrengthModel()

    def test_strong_home_favorite(self):
        """排名差距大 → home方向"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_stats": {"rank": 1, "played": 20, "wins": 18, "goals_for": 60, "goals_against": 10,
                          "home_wins": 10, "recent_form": "WWWWW"},
            "away_stats": {"rank": 18, "played": 20, "wins": 3, "goals_for": 12, "goals_against": 50,
                          "away_wins": 1, "recent_form": "LLLLL"},
        })
        self.assertEqual(result["direction"], "home")
        self.assertGreater(result["score"], 50)

    def test_strong_away_favorite(self):
        """客队明显更强 → away方向"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_stats": {"rank": 18, "played": 20, "wins": 3, "goals_for": 12, "goals_against": 50,
                          "home_wins": 1, "recent_form": "LLLLL"},
            "away_stats": {"rank": 1, "played": 20, "wins": 18, "goals_for": 60, "goals_against": 10,
                          "away_wins": 10, "recent_form": "WWWWW"},
        })
        self.assertEqual(result["direction"], "away")
        self.assertLess(result["score"], 50)

    def test_even_match(self):
        """实力接近 → draw方向"""
        stats = {"rank": 10, "played": 20, "wins": 8, "goals_for": 25, "goals_against": 25,
                "home_wins": 5, "away_wins": 4, "recent_form": "WDWLD"}
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_stats": stats.copy(), "away_stats": stats.copy(),
        })
        self.assertEqual(result["direction"], "draw")


class TestStrengthModelNoData(unittest.TestCase):
    """无数据降级"""

    def setUp(self):
        self.model = StrengthModel()

    def test_no_home_stats(self):
        result = self.model.analyze({"home_team": "A", "away_team": "B", "home_stats": None, "away_stats": {"rank": 5}})
        self.assertEqual(result["direction"], "neutral")
        self.assertEqual(result["score"], 50.0)
        self.assertTrue(result["details"].get("data_missing"))

    def test_no_away_stats(self):
        result = self.model.analyze({"home_team": "A", "away_team": "B", "home_stats": {"rank": 5}, "away_stats": None})
        self.assertEqual(result["direction"], "neutral")

    def test_empty_stats(self):
        result = self.model.analyze({"home_team": "A", "away_team": "B", "home_stats": {}, "away_stats": {}})
        self.assertEqual(result["direction"], "neutral")

    def test_missing_keys_entirely(self):
        result = self.model.analyze({"home_team": "A", "away_team": "B"})
        self.assertEqual(result["direction"], "neutral")


class TestStrengthModelConstraints(unittest.TestCase):
    """架构约束"""

    def setUp(self):
        self.model = StrengthModel()

    def test_weight_from_config(self):
        self.assertEqual(self.model.weight, 0.25)

    def test_no_db_access(self):
        src = inspect.getsource(StrengthModel)
        self.assertNotIn("get_connection", src)
        self.assertNotIn("get_team_stats", src)
        self.assertNotIn("from utils.database", src)

    def test_details_contain_power(self):
        model = StrengthModel()
        result = model.analyze({
            "home_team": "A", "away_team": "B",
            "home_stats": {"rank": 3, "played": 10, "wins": 7, "goals_for": 20, "goals_against": 8},
            "away_stats": {"rank": 12, "played": 10, "wins": 3, "goals_for": 8, "goals_against": 18},
        })
        self.assertIn("home_power", result["details"])
        self.assertIn("away_power", result["details"])
        self.assertIn("power_diff", result["details"])


if __name__ == "__main__":
    unittest.main()
