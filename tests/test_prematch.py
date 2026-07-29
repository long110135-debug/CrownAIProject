"""
临场二次分析(prematch_analyze)单元测试
"""
import unittest
import os
import sys
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import get_connection, init_db


class TestPrematchMigration(unittest.TestCase):
    """验证数据库迁移正确添加prematch列"""

    def test_prediction_history_has_prematch_columns(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(prediction_history)")
        cols = [r[1] for r in cur.fetchall()]
        conn.close()
        expected = ['prematch_at', 'prematch_handicap', 'prematch_home_water',
                    'prematch_away_water', 'prematch_crown_index', 'prematch_recommend',
                    'prematch_strength_score', 'prematch_handicap_score', 'prematch_market_score']
        for col in expected:
            self.assertIn(col, cols, f"缺少列: {col}")

    def test_experiments_has_prematch_columns(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(recommendation_experiments)")
        cols = [r[1] for r in cur.fetchall()]
        conn.close()
        expected = ['prematch_consensus', 'prematch_consensus_reason', 'prematch_at']
        for col in expected:
            self.assertIn(col, cols, f"缺少列: {col}")


class TestPrematchSaveFunctions(unittest.TestCase):
    """验证save_prematch_update和save_prematch_experiment"""

    def setUp(self):
        self.conn = get_connection()
        cur = self.conn.cursor()
        # 创建测试比赛和预测
        self.test_mid = f"TEST_prematch_{datetime.now().strftime('%H%M%S')}"
        cur.execute("""INSERT OR REPLACE INTO matches (match_id, league, home_team, away_team, match_time, status)
                       VALUES (?, '测试', 'TestHome', 'TestAway', ?, 'pending')""",
                    (self.test_mid, (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M')))
        cur.execute("""INSERT INTO prediction_history (match_id, league, home_team, away_team, kickoff, recommend, level)
                       VALUES (?, '测试', 'TestHome', 'TestAway', ?, 'neutral', 'C')
                       ON CONFLICT(match_id) DO NOTHING""",
                    (self.test_mid, (datetime.now() + timedelta(minutes=30)).strftime('%Y-%m-%d %H:%M')))
        cur.execute("""INSERT INTO recommendation_experiments (match_id, model_version, legacy_recommend, consensus_recommend)
                       VALUES (?, 'test', 'neutral', 'home')
                       ON CONFLICT DO NOTHING""", (self.test_mid,))
        self.conn.commit()
        self.conn.close()

    def tearDown(self):
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("DELETE FROM matches WHERE match_id = ?", (self.test_mid,))
        cur.execute("DELETE FROM prediction_history WHERE match_id = ?", (self.test_mid,))
        cur.execute("DELETE FROM recommendation_experiments WHERE match_id = ?", (self.test_mid,))
        conn.commit()
        conn.close()

    def test_save_prematch_update(self):
        from utils.database import save_prematch_update
        data = {
            'prematch_at': '2026-07-29 18:00:00',
            'prematch_handicap': '客让0.5',
            'prematch_home_water': 1.85,
            'prematch_away_water': 2.05,
            'prematch_crown_index': 72.5,
            'prematch_recommend': 'home',
            'prematch_strength_score': 55.0,
            'prematch_handicap_score': 68.0,
            'prematch_market_score': 71.0,
        }
        save_prematch_update(self.test_mid, data)

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT prematch_at, prematch_handicap, prematch_crown_index, prematch_recommend FROM prediction_history WHERE match_id = ?",
                    (self.test_mid,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row['prematch_at'], '2026-07-29 18:00:00')
        self.assertEqual(row['prematch_handicap'], '客让0.5')
        self.assertEqual(row['prematch_crown_index'], 72.5)
        self.assertEqual(row['prematch_recommend'], 'home')

    def test_save_prematch_update_does_not_touch_original(self):
        """prematch更新不覆盖首次分析字段"""
        from utils.database import save_prematch_update
        # 先记录原始值
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT recommend, crown_index FROM prediction_history WHERE match_id = ?", (self.test_mid,))
        orig = cur.fetchone()
        conn.close()

        save_prematch_update(self.test_mid, {
            'prematch_at': '2026-07-29 18:00:00',
            'prematch_recommend': 'away',
            'prematch_crown_index': 99.0,
        })

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT recommend, crown_index, prematch_recommend, prematch_crown_index FROM prediction_history WHERE match_id = ?",
                    (self.test_mid,))
        row = cur.fetchone()
        conn.close()
        # 原始字段不变
        self.assertEqual(row['recommend'], orig['recommend'])
        self.assertEqual(row['crown_index'], orig['crown_index'])
        # prematch字段已更新
        self.assertEqual(row['prematch_recommend'], 'away')
        self.assertEqual(row['prematch_crown_index'], 99.0)

    def test_save_prematch_experiment(self):
        from utils.database import save_prematch_experiment
        save_prematch_experiment(self.test_mid, 'away', 'test reason')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT prematch_consensus, prematch_consensus_reason, prematch_at FROM recommendation_experiments WHERE match_id = ?",
                    (self.test_mid,))
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row['prematch_consensus'], 'away')
        self.assertEqual(row['prematch_consensus_reason'], 'test reason')
        self.assertIsNotNone(row['prematch_at'])

    def test_prematch_experiment_skips_settled(self):
        """已结算的影子记录不被更新"""
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("UPDATE recommendation_experiments SET settled_at = '2026-07-29 02:00:00' WHERE match_id = ?",
                    (self.test_mid,))
        conn.commit()
        conn.close()

        from utils.database import save_prematch_experiment
        save_prematch_experiment(self.test_mid, 'draw', 'should not update')

        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT prematch_consensus FROM recommendation_experiments WHERE match_id = ?", (self.test_mid,))
        row = cur.fetchone()
        conn.close()
        self.assertIsNone(row['prematch_consensus'])


class TestPrematchWindowLogic(unittest.TestCase):
    """验证prematch_analyze的时间窗口和过滤逻辑"""

    @patch('pipeline.daily_run.get_connection')
    def test_no_candidates_returns_zero(self, mock_conn):
        """无候选比赛时返回0"""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.return_value.cursor.return_value = mock_cursor
        mock_conn.return_value.close = MagicMock()

        from pipeline.daily_run import prematch_analyze
        result = prematch_analyze()
        self.assertEqual(result['updated'], 0)
        self.assertEqual(result['matches'], [])

    def test_window_parameters(self):
        """窗口参数正确: 默认15~45分钟"""
        from pipeline.daily_run import prematch_analyze
        # 只验证函数签名接受参数(不实际执行)
        import inspect
        sig = inspect.signature(prematch_analyze)
        self.assertEqual(sig.parameters['window_min'].default, 45)
        self.assertEqual(sig.parameters['window_max'].default, 15)


class TestPrematchSchedulerIntegration(unittest.TestCase):
    """验证scheduler集成"""

    def test_prematch_in_commands(self):
        """scheduler.py包含prematch命令"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("scheduler",
                                                      os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scheduler.py"))
        mod = importlib.util.module_from_spec(spec)
        # 不执行__main__，只检查函数存在
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, 'cmd_prematch'))

    def test_prematch_uses_analyze_lock(self):
        """prematch使用analyze锁(与常规分析互斥)"""
        import inspect
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from scheduler import cmd_prematch
        source = inspect.getsource(cmd_prematch)
        self.assertIn('TaskLock("analyze")', source)


if __name__ == '__main__':
    unittest.main()
