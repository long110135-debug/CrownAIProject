"""测试推荐引擎"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.recommender import generate_recommendation, rank_recommendations


class TestRecommender(unittest.TestCase):

    def _make_analysis(self, crown_index=80, completeness=85):
        return {
            "match_id": "TEST",
            "home_team": "A", "away_team": "B",
            "league": "英超", "match_time": "2026-01-01 20:00",
            "crown_index": crown_index,
            "crown_rating": "A",
            "data_completeness": completeness,
            "odds": {"current_handicap": "主让0.5", "asian_handicap": "主让0.5"},
            "model_results": {
                "strength": {"score": 80, "direction": "home", "confidence": 75},
                "handicap": {"score": 82, "direction": "home", "confidence": 80},
                "squad": {"score": 70, "direction": "home", "confidence": 60},
                "market": {"score": 75, "direction": "home", "confidence": 70},
                "ai_referee": {"score": 70, "direction": "home", "confidence": 65,
                              "details": {"decision": "approve"}},
            },
        }

    def test_output_has_required_fields(self):
        rec = generate_recommendation(self._make_analysis())
        for field in ["match_id", "level", "direction", "crown_index", "confidence"]:
            self.assertIn(field, rec)

    def test_rank_partitions(self):
        """rank_recommendations应正确分组A/B/C"""
        recs = [
            {"level": "A", "crown_index": 85, "risk_level": "低"},
            {"level": "B", "crown_index": 70, "risk_level": "低"},
            {"level": "C", "crown_index": 50, "risk_level": "低"},
        ]
        ranked = rank_recommendations(recs)
        self.assertEqual(ranked["a_count"], 1)
        self.assertEqual(ranked["b_count"], 1)
        self.assertEqual(ranked["c_count"], 1)


if __name__ == "__main__":
    unittest.main()
