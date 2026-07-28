"""测试AI裁判: 纯裁决，不生成方向"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.ai_referee import AIRefereeModel


class TestAIReferee(unittest.TestCase):

    def setUp(self):
        self.ai = AIRefereeModel()

    def _make_input(self, dirs=None):
        if dirs is None:
            dirs = ["home", "home", "home", "neutral"]
        model_results = {}
        for i, name in enumerate(["strength", "handicap", "squad", "market"]):
            model_results[name] = {"score": 75, "direction": dirs[i], "confidence": 70}
        return {"model_results": model_results, "data_completeness": 85}

    def test_approve_when_consistent(self):
        """模型一致 → approve"""
        result = self.ai.analyze(self._make_input(["home", "home", "home", "home"]))
        self.assertEqual(result["details"]["decision"], "approve")

    def test_reject_when_conflicted(self):
        """严重冲突 → reject"""
        result = self.ai.analyze(self._make_input(["home", "away", "away", "home"]))
        self.assertIn(result["details"]["decision"], ("downgrade", "reject"))

    def test_reject_no_data(self):
        """无数据 → reject"""
        result = self.ai.analyze({"model_results": {}})
        self.assertEqual(result["details"]["decision"], "reject")

    def test_direction_inherited_not_generated(self):
        """方向继承多数票，不自己生成"""
        result = self.ai.analyze(self._make_input(["away", "away", "away", "neutral"]))
        self.assertEqual(result["direction"], "away")

    def test_does_not_access_db(self):
        """不访问数据库"""
        import inspect
        src = inspect.getsource(AIRefereeModel)
        self.assertNotIn("get_connection", src)
        self.assertNotIn("get_team_stats", src)

    def test_weight_from_config(self):
        self.assertEqual(self.ai.weight, 0.10)


if __name__ == "__main__":
    unittest.main()
