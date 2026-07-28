"""测试已有数据库迁移: 旧版prediction_history补齐5列"""
import sys
import os
import unittest
import tempfile
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExistingDbMigration(unittest.TestCase):
    """模拟旧版DB(缺5列)，验证迁移补齐且可重复执行"""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_migrate.db")
        # 创建旧版schema(缺少5列)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE prediction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT UNIQUE,
                league TEXT,
                home_team TEXT,
                away_team TEXT,
                kickoff TEXT,
                asian_open TEXT,
                asian_live TEXT,
                crown_index REAL,
                strength_score REAL,
                handicap_score REAL,
                market_score REAL,
                squad_score REAL,
                ai_score REAL,
                data_completeness REAL DEFAULT 0,
                recommend TEXT,
                level TEXT,
                confidence REAL,
                result TEXT DEFAULT '',
                result_score TEXT DEFAULT '',
                hit INTEGER DEFAULT -1,
                error_reason TEXT DEFAULT '',
                predicted_at TEXT,
                settled_at TEXT
            )
        """)
        # 插入一条旧数据
        conn.execute("""
            INSERT INTO prediction_history (match_id, league, home_team, away_team, kickoff, crown_index, recommend, level)
            VALUES ('OLD_RECORD_001', '英超', '阿森纳', '切尔西', '2026-01-01', 75.0, 'home', 'B')
        """)
        conn.commit()
        conn.close()

        # 替换DB_PATH
        import utils.database as db_mod
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path

    def tearDown(self):
        import utils.database as db_mod
        db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def test_migration_adds_missing_columns(self):
        """迁移后5列全部存在"""
        import utils.database as db_mod
        db_mod.init_db()

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(prediction_history)")
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()

        for col in ["model_version", "model_weights", "ai_decision", "odds_home_water", "odds_away_water"]:
            self.assertIn(col, columns, f"迁移后仍缺少列: {col}")

    def test_migration_idempotent(self):
        """重复执行迁移不报错"""
        import utils.database as db_mod
        db_mod.init_db()
        db_mod.init_db()  # 第二次
        db_mod.init_db()  # 第三次

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(prediction_history)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()

        # 不应有重复列
        self.assertEqual(len(columns), len(set(columns)), "存在重复列")

    def test_old_data_preserved(self):
        """迁移后旧数据不丢失"""
        import utils.database as db_mod
        db_mod.init_db()

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prediction_history WHERE match_id = 'OLD_RECORD_001'")
        row = dict(cursor.fetchone())
        conn.close()

        self.assertEqual(row["league"], "英超")
        self.assertEqual(row["home_team"], "阿森纳")
        self.assertAlmostEqual(row["crown_index"], 75.0)
        # 新列应为NULL
        self.assertIsNone(row["model_version"])
        self.assertIsNone(row["odds_home_water"])

    def test_save_prediction_after_migration(self):
        """迁移后save_prediction()正常工作"""
        import utils.database as db_mod
        db_mod.init_db()

        db_mod.save_prediction({
            "match_id": "NEW_AFTER_MIGRATE",
            "league": "西甲",
            "home_team": "巴萨",
            "away_team": "皇马",
            "kickoff": "2026-02-01",
            "crown_index": 82,
            "recommend": "home",
            "level": "A",
            "confidence": 82,
            "model_version": "CrownAI_1.3",
            "model_weights": {"strength": 0.25},
            "ai_decision": "approve",
            "odds_home_water": 0.90,
            "odds_away_water": 0.95,
        })

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT model_version, ai_decision, odds_home_water FROM prediction_history WHERE match_id = 'NEW_AFTER_MIGRATE'")
        row = dict(cursor.fetchone())
        conn.close()

        self.assertEqual(row["model_version"], "CrownAI_1.3")
        self.assertEqual(row["ai_decision"], "approve")
        self.assertAlmostEqual(row["odds_home_water"], 0.90)


if __name__ == "__main__":
    unittest.main()
