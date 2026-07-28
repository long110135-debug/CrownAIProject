"""测试全新数据库初始化: init_db() + save_prediction() 不崩"""
import sys
import os
import unittest
import tempfile
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestFreshDbInit(unittest.TestCase):
    """在临时目录创建全新数据库，验证schema完整"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_fresh.db")
        # 临时替换DB_PATH
        import utils.database as db_mod
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path

    def tearDown(self):
        import utils.database as db_mod
        db_mod.DB_PATH = self._orig_path
        # 清理临时文件
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def test_init_db_creates_all_columns(self):
        """init_db()后prediction_history应包含全部列"""
        import utils.database as db_mod
        db_mod.init_db()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(prediction_history)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        required = {
            "match_id", "league", "home_team", "away_team", "kickoff",
            "asian_open", "asian_live", "crown_index",
            "strength_score", "handicap_score", "market_score", "squad_score", "ai_score",
            "data_completeness", "recommend", "level", "confidence",
            "predicted_at", "settled_at",
            "clv_handicap", "clv_water", "closing_handicap", "closing_home_water", "closing_away_water",
            "model_version", "model_weights", "ai_decision", "odds_home_water", "odds_away_water",
        }
        missing = required - columns
        self.assertEqual(missing, set(), f"缺少列: {missing}")

    def test_save_prediction_on_fresh_db(self):
        """全新DB上save_prediction()不报错"""
        import utils.database as db_mod
        db_mod.init_db()

        # 不应抛异常
        db_mod.save_prediction({
            "match_id": "FRESH_TEST_001",
            "league": "测试",
            "home_team": "A",
            "away_team": "B",
            "kickoff": "2026-01-01 20:00",
            "asian_open": "主让0.5",
            "asian_live": "主让0.75",
            "crown_index": 78.5,
            "strength_score": 75,
            "handicap_score": 80,
            "market_score": 70,
            "squad_score": 65,
            "ai_score": 60,
            "data_completeness": 85,
            "recommend": "home",
            "level": "B",
            "confidence": 78.5,
            "model_version": "CrownAI_1.3",
            "model_weights": {"strength": 0.25, "handicap": 0.30},
            "ai_decision": "approve",
            "odds_home_water": 0.92,
            "odds_away_water": 0.95,
        })

    def test_read_back_snapshot_fields(self):
        """写入后能正确读回5个快照字段"""
        import utils.database as db_mod
        db_mod.init_db()

        db_mod.save_prediction({
            "match_id": "FRESH_TEST_002",
            "league": "测试",
            "home_team": "C",
            "away_team": "D",
            "kickoff": "2026-01-01 20:00",
            "crown_index": 80,
            "recommend": "away",
            "level": "A",
            "confidence": 80,
            "model_version": "CrownAI_1.3",
            "model_weights": {"strength": 0.25, "handicap": 0.30, "squad": 0.15, "market": 0.20, "ai_referee": 0.10},
            "ai_decision": "downgrade",
            "odds_home_water": 0.88,
            "odds_away_water": 1.02,
        })

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prediction_history WHERE match_id = 'FRESH_TEST_002'")
        row = dict(cursor.fetchone())
        conn.close()

        self.assertEqual(row["model_version"], "CrownAI_1.3")
        self.assertIn("strength", row["model_weights"])
        self.assertEqual(row["ai_decision"], "downgrade")
        self.assertAlmostEqual(row["odds_home_water"], 0.88)
        self.assertAlmostEqual(row["odds_away_water"], 1.02)

    def test_null_compatibility(self):
        """旧记录(5列为NULL)读取不崩"""
        import utils.database as db_mod
        db_mod.init_db()

        # 模拟旧记录: 不传5个新字段
        db_mod.save_prediction({
            "match_id": "FRESH_TEST_003",
            "league": "测试",
            "home_team": "E",
            "away_team": "F",
            "kickoff": "2026-01-01 20:00",
            "crown_index": 50,
            "recommend": "neutral",
            "level": "C",
            "confidence": 50,
        })

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT model_version, model_weights, ai_decision, odds_home_water, odds_away_water FROM prediction_history WHERE match_id = 'FRESH_TEST_003'")
        row = dict(cursor.fetchone())
        conn.close()

        # 新列应为NULL或默认值，不应报错
        self.assertIsNone(row["odds_home_water"])
        self.assertIsNone(row["odds_away_water"])


if __name__ == "__main__":
    unittest.main()
