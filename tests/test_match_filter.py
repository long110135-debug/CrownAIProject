"""测试三层过滤机制"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.match_filter import (
    filter_matches, filter_by_data_quality, filter_by_recommendation_quality,
    _calc_model_agreement, DATA_REQUIREMENTS, RECOMMEND_REQUIREMENTS,
)


class TestLayer1LeagueFilter(unittest.TestCase):
    """L1: 赛事过滤"""

    def test_allowed_league_passes(self):
        matches = [{"league": "英超", "home_team": "A", "away_team": "B"}]
        result = filter_matches(matches)
        self.assertEqual(len(result), 1)

    def test_unknown_league_filtered(self):
        matches = [{"league": "未知联赛XYZ", "home_team": "A", "away_team": "B"}]
        result = filter_matches(matches)
        self.assertEqual(len(result), 0)

    def test_youth_team_filtered(self):
        matches = [{"league": "英超", "home_team": "阿森纳U21", "away_team": "B"}]
        result = filter_matches(matches)
        self.assertEqual(len(result), 0)

    def test_nordic_league_passes(self):
        matches = [{"league": "瑞超", "home_team": "A", "away_team": "B"}]
        result = filter_matches(matches)
        self.assertEqual(len(result), 1)


class TestLayer2DataQuality(unittest.TestCase):
    """L2: 数据过滤"""

    def test_no_timeline_fails(self):
        """无时间线记录 → 不通过"""
        result = filter_by_data_quality("NONEXIST_MATCH_ID", {"home_team": "A", "away_team": "B"})
        self.assertFalse(result["pass"])
        self.assertIn("盘口时间线", result["reasons"][0])

    def test_quality_score_range(self):
        """质量分在0-100范围"""
        result = filter_by_data_quality("NONEXIST", {})
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 100)


class TestLayer3Recommendation(unittest.TestCase):
    """L3: 推荐过滤"""

    def _make_analysis(self, crown_index=80, completeness=85, agreement_dirs=None):
        if agreement_dirs is None:
            agreement_dirs = ["home", "home", "home", "neutral"]
        model_results = {}
        for i, name in enumerate(["strength", "handicap", "squad", "market"]):
            model_results[name] = {
                "score": 75, "direction": agreement_dirs[i], "confidence": 70
            }
        model_results["ai_referee"] = {"score": 70, "direction": "neutral", "confidence": 60}
        return {
            "match_id": "TEST",
            "crown_index": crown_index,
            "data_completeness": completeness,
            "model_results": model_results,
        }

    def test_high_quality_passes(self):
        """高指数+高完整度+高一致性 → 通过"""
        analysis = self._make_analysis(crown_index=82, completeness=90)
        result = filter_by_recommendation_quality(analysis)
        self.assertTrue(result["pass"])

    def test_low_index_fails(self):
        """指数<75 → 不通过"""
        analysis = self._make_analysis(crown_index=60)
        result = filter_by_recommendation_quality(analysis)
        self.assertFalse(result["pass"])
        self.assertTrue(any("皇冠指数" in r for r in result["reasons"]))

    def test_low_completeness_fails(self):
        """完整度<80% → 不通过"""
        analysis = self._make_analysis(completeness=50)
        result = filter_by_recommendation_quality(analysis)
        self.assertFalse(result["pass"])

    def test_low_agreement_fails(self):
        """模型一致性<60% → 不通过"""
        analysis = self._make_analysis(agreement_dirs=["home", "away", "draw", "neutral"])
        result = filter_by_recommendation_quality(analysis)
        self.assertFalse(result["pass"])


class TestModelAgreement(unittest.TestCase):
    """模型一致性计算"""

    def test_all_same(self):
        results = {
            "strength": {"direction": "home"},
            "handicap": {"direction": "home"},
            "squad": {"direction": "home"},
            "market": {"direction": "home"},
        }
        self.assertEqual(_calc_model_agreement(results), 1.0)

    def test_all_neutral(self):
        results = {
            "strength": {"direction": "neutral"},
            "handicap": {"direction": "neutral"},
        }
        self.assertEqual(_calc_model_agreement(results), 0.0)

    def test_split(self):
        results = {
            "strength": {"direction": "home"},
            "handicap": {"direction": "away"},
            "squad": {"direction": "home"},
            "market": {"direction": "away"},
        }
        self.assertEqual(_calc_model_agreement(results), 0.5)


if __name__ == "__main__":
    unittest.main()
