"""测试CLV端到端计算: 写入prediction+closing → 计算CLV → 验证值"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import (
    get_connection, save_prediction, save_closing_odds, calc_clv, update_prediction_clv
)


class TestCLVEndToEnd(unittest.TestCase):

    def setUp(self):
        self.test_id = "TEST_CLV_E2E_001"
        # 写入预测记录(推荐时盘口: 主让0.75, 主水0.90)
        save_prediction({
            "match_id": self.test_id, "league": "测试", "home_team": "A", "away_team": "B",
            "kickoff": "2026-01-01 20:00",
            "asian_open": "主让0.5", "asian_live": "主让0.75",
            "crown_index": 78, "recommend": "home", "level": "B", "confidence": 78,
            "strength_score": 75, "handicap_score": 80, "market_score": 70,
            "squad_score": 65, "ai_score": 60, "data_completeness": 85,
            "odds_home_water": 0.90, "odds_away_water": 0.95,
        })
        # 写入收盘盘口(收盘: 主让0.5, 主水0.95)
        save_closing_odds(self.test_id, {
            "handicap": "主让0.5", "home_water": 0.95, "away_water": 0.90,
        })

    def tearDown(self):
        conn = get_connection()
        conn.execute("DELETE FROM prediction_history WHERE match_id = ?", (self.test_id,))
        conn.execute("DELETE FROM closing_odds WHERE match_id = ?", (self.test_id,))
        conn.execute("DELETE FROM odds_timeline WHERE match_id = ?", (self.test_id,))
        conn.commit()
        conn.close()

    def test_clv_positive(self):
        """推荐时主让0.75, 收盘主让0.5 → 正CLV(推荐时盘口更深)"""
        clv = calc_clv(self.test_id)
        self.assertIsNotNone(clv)
        self.assertGreater(clv["clv_handicap"], 0)
        self.assertTrue(clv["positive_clv"])

    def test_clv_values_correct(self):
        """CLV = 0.75 - 0.5 = 0.25"""
        clv = calc_clv(self.test_id)
        self.assertAlmostEqual(clv["clv_handicap"], 0.25, places=2)

    def test_update_prediction_clv(self):
        """update_prediction_clv应写回prediction_history"""
        update_prediction_clv(self.test_id)
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT clv_handicap, clv_water FROM prediction_history WHERE match_id = ?",
                      (self.test_id,))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row["clv_handicap"])
        self.assertGreater(row["clv_handicap"], 0)

    def test_no_closing_returns_none(self):
        """无收盘数据 → None"""
        clv = calc_clv("NONEXIST_MATCH")
        self.assertIsNone(clv)


class TestCLVNegative(unittest.TestCase):

    def setUp(self):
        self.test_id = "TEST_CLV_NEG_001"
        # 推荐时主让0.5, 收盘升到主让0.75 → 负CLV
        save_prediction({
            "match_id": self.test_id, "league": "测试", "home_team": "C", "away_team": "D",
            "kickoff": "2026-01-01 20:00",
            "asian_open": "主让0.5", "asian_live": "主让0.5",
            "crown_index": 70, "recommend": "home", "level": "C", "confidence": 70,
            "odds_home_water": 0.95, "odds_away_water": 0.90,
        })
        save_closing_odds(self.test_id, {
            "handicap": "主让0.75", "home_water": 0.88, "away_water": 0.98,
        })

    def tearDown(self):
        conn = get_connection()
        conn.execute("DELETE FROM prediction_history WHERE match_id = ?", (self.test_id,))
        conn.execute("DELETE FROM closing_odds WHERE match_id = ?", (self.test_id,))
        conn.execute("DELETE FROM odds_timeline WHERE match_id = ?", (self.test_id,))
        conn.commit()
        conn.close()

    def test_clv_negative(self):
        """推荐时主让0.5, 收盘主让0.75 → 负CLV"""
        clv = calc_clv(self.test_id)
        self.assertIsNotNone(clv)
        self.assertLess(clv["clv_handicap"], 0)
        self.assertFalse(clv["positive_clv"])


if __name__ == "__main__":
    unittest.main()
