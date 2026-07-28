"""测试odds_tracker: 时间线记录、收盘锁定"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOddsTracker(unittest.TestCase):

    def test_timeline_append(self):
        """时间线追加写入"""
        from utils.database import save_timeline_record, get_timeline, get_connection
        test_id = "TEST_TRACKER_001"

        save_timeline_record(test_id, {"handicap": "主让0.5", "home_water": 0.95, "away_water": 0.90})
        save_timeline_record(test_id, {"handicap": "主让0.75", "home_water": 0.90, "away_water": 0.95})

        tl = get_timeline(test_id)
        self.assertEqual(len(tl), 2)

        # 清理
        conn = get_connection()
        conn.execute("DELETE FROM odds_timeline WHERE match_id = ?", (test_id,))
        conn.commit()
        conn.close()

    def test_detect_changes_uses_odds_math(self):
        """变化检测应委托给odds_math"""
        import inspect
        from pipeline.odds_tracker import _compare_timeline_records
        src = inspect.getsource(_compare_timeline_records)
        self.assertIn("compute_change", src)
        self.assertNotIn("升盘", src.split("compute_change")[0])  # 判断逻辑不在本地

    def test_closing_odds_lock(self):
        """收盘锁定写入closing_odds表"""
        from utils.database import save_closing_odds, get_closing_odds, get_connection
        test_id = "TEST_CLOSING_001"

        save_closing_odds(test_id, {"handicap": "主让1", "home_water": 0.85, "away_water": 1.05})
        closing = get_closing_odds(test_id)
        self.assertIsNotNone(closing)
        self.assertEqual(closing["handicap"], "主让1")

        # 清理
        conn = get_connection()
        conn.execute("DELETE FROM closing_odds WHERE match_id = ?", (test_id,))
        conn.execute("DELETE FROM odds_timeline WHERE match_id = ?", (test_id,))
        conn.commit()
        conn.close()


if __name__ == "__main__":
    unittest.main()
