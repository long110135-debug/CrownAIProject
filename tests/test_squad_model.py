"""测试阵容模型: 完整度计算/缺阵扣分/疲劳/轮换/无数据"""
import sys
import os
import unittest
import inspect

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.squad_model import SquadModel


class TestSquadModelOutput(unittest.TestCase):
    """输出格式"""

    def setUp(self):
        self.model = SquadModel()
        self.match_data = {
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": ["球员1"], "fatigue_days": 5},
            "away_squad": {"missing_players": [], "fatigue_days": 7},
        }

    def test_output_has_required_fields(self):
        result = self.model.analyze(self.match_data)
        for field in ("model", "score", "direction", "confidence", "reasoning", "details"):
            self.assertIn(field, result)

    def test_model_name(self):
        result = self.model.analyze(self.match_data)
        self.assertEqual(result["model"], "squad")

    def test_details_structure(self):
        result = self.model.analyze(self.match_data)
        self.assertIn("home_integrity", result["details"])
        self.assertIn("away_integrity", result["details"])


class TestSquadModelIntegrity(unittest.TestCase):
    """完整度计算"""

    def setUp(self):
        self.model = SquadModel()

    def test_healthy_squad_high_integrity(self):
        """无缺阵+充分休息 → 高完整度"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "key_absences": [], "fatigue_days": 7},
            "away_squad": {"missing_players": [], "key_absences": [], "fatigue_days": 7},
        })
        self.assertGreater(result["details"]["home_integrity"], 45)

    def test_missing_players_deducts(self):
        """缺阵球员扣分(每人-3)"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": ["P1", "P2", "P3"], "fatigue_days": 5},
            "away_squad": {"missing_players": [], "fatigue_days": 5},
        })
        # 主队缺3人 → integrity = 50 - 9 = 41
        self.assertLess(result["details"]["home_integrity"], 45)
        self.assertGreater(result["details"]["away_integrity"], result["details"]["home_integrity"])

    def test_key_absences_heavy_deduction(self):
        """关键球员缺席扣分更重(每人-6)"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "key_absences": ["核心1", "核心2"], "fatigue_days": 5},
            "away_squad": {"missing_players": [], "key_absences": [], "fatigue_days": 5},
        })
        # 主队2个核心缺阵 → integrity = 50 - 12 = 38
        self.assertLessEqual(result["details"]["home_integrity"], 38)

    def test_fatigue_extreme(self):
        """极度疲劳(<=2天休息)扣6分"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "fatigue_days": 2},
            "away_squad": {"missing_players": [], "fatigue_days": 7},
        })
        self.assertLess(result["details"]["home_integrity"], result["details"]["away_integrity"])

    def test_fatigue_moderate(self):
        """较疲劳(<=3天)扣3分"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "fatigue_days": 3},
            "away_squad": {"missing_players": [], "fatigue_days": 7},
        })
        diff = result["details"]["away_integrity"] - result["details"]["home_integrity"]
        self.assertAlmostEqual(diff, 3.0, places=0)

    def test_rotation_high(self):
        """高轮换风险扣8分"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "rotation_risk": "高", "fatigue_days": 5},
            "away_squad": {"missing_players": [], "rotation_risk": "", "fatigue_days": 5},
        })
        diff = result["details"]["away_integrity"] - result["details"]["home_integrity"]
        self.assertAlmostEqual(diff, 8.0, places=0)


class TestSquadModelDirection(unittest.TestCase):
    """方向判断"""

    def setUp(self):
        self.model = SquadModel()

    def test_home_much_healthier(self):
        """主队阵容远优于客队 → home"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "fatigue_days": 7},
            "away_squad": {"missing_players": ["P1", "P2", "P3", "P4"], "key_absences": ["K1"],
                          "rotation_risk": "高", "fatigue_days": 2},
        })
        self.assertEqual(result["direction"], "home")

    def test_away_much_healthier(self):
        """客队阵容远优于主队 → away"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": ["P1", "P2", "P3", "P4"], "key_absences": ["K1"],
                          "rotation_risk": "高", "fatigue_days": 2},
            "away_squad": {"missing_players": [], "fatigue_days": 7},
        })
        self.assertEqual(result["direction"], "away")

    def test_both_healthy_neutral(self):
        """双方都健康 → neutral"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": [], "fatigue_days": 5},
            "away_squad": {"missing_players": [], "fatigue_days": 5},
        })
        self.assertEqual(result["direction"], "neutral")


class TestSquadModelNoData(unittest.TestCase):
    """无数据"""

    def setUp(self):
        self.model = SquadModel()

    def test_empty_squads(self):
        """双方都无数据 → neutral, 默认完整度40"""
        result = self.model.analyze({"home_team": "A", "away_team": "B",
                                     "home_squad": {}, "away_squad": {}})
        self.assertEqual(result["direction"], "neutral")
        self.assertEqual(result["details"]["home_integrity"], 40)

    def test_missing_squad_keys(self):
        """完全无squad字段"""
        result = self.model.analyze({"home_team": "A", "away_team": "B"})
        self.assertEqual(result["direction"], "neutral")

    def test_missing_players_as_int(self):
        """missing_players为整数也兼容"""
        result = self.model.analyze({
            "home_team": "A", "away_team": "B",
            "home_squad": {"missing_players": 3, "fatigue_days": 5},
            "away_squad": {"missing_players": 0, "fatigue_days": 5},
        })
        self.assertLess(result["details"]["home_integrity"], result["details"]["away_integrity"])


class TestSquadModelConstraints(unittest.TestCase):
    """架构约束"""

    def setUp(self):
        self.model = SquadModel()

    def test_weight_from_config(self):
        self.assertEqual(self.model.weight, 0.15)

    def test_no_db_access(self):
        src = inspect.getsource(SquadModel)
        self.assertNotIn("get_connection", src)
        self.assertNotIn("from utils.database", src)


if __name__ == "__main__":
    unittest.main()
