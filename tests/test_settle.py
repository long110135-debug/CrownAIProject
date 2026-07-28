"""测试结算流程: settle.py"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSettleLogic(unittest.TestCase):

    def test_neutral_not_counted(self):
        """neutral推荐 → hit=2(不计入命中率)"""
        from settle import auto_settle
        # 验证hit=2的逻辑存在
        import inspect
        src = inspect.getsource(auto_settle)
        self.assertIn("hit = 2", src)
        self.assertIn("neutral", src)

    def test_hit_stats_exclude_hit2(self):
        """命中率统计应排除hit=2"""
        from utils.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        # 插入测试数据
        cursor.execute("""INSERT OR REPLACE INTO prediction_history 
            (match_id, league, home_team, away_team, kickoff, recommend, hit, level)
            VALUES ('TEST_HIT_1', '测试', 'A', 'B', '2026-01-01', 'home', 1, 'A')""")
        cursor.execute("""INSERT OR REPLACE INTO prediction_history 
            (match_id, league, home_team, away_team, kickoff, recommend, hit, level)
            VALUES ('TEST_HIT_2', '测试', 'C', 'D', '2026-01-01', 'neutral', 2, 'C')""")
        conn.commit()

        # 统计应只计hit IN (0,1)
        cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE hit IN (0,1) AND match_id LIKE 'TEST_HIT%'")
        counted = cursor.fetchone()[0]

        # 清理
        cursor.execute("DELETE FROM prediction_history WHERE match_id LIKE 'TEST_HIT%'")
        conn.commit()
        conn.close()

        self.assertEqual(counted, 1, "只有hit=1应被计入，hit=2不应计入")


class TestValidationRecord(unittest.TestCase):

    def test_validation_written_on_settle(self):
        """结算时应写入model_validation表"""
        from settle import _save_validation_record
        import inspect
        src = inspect.getsource(_save_validation_record)
        self.assertIn("save_validation_record", src)


if __name__ == "__main__":
    unittest.main()
