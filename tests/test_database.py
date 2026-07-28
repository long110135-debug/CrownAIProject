"""测试数据库操作: 唯一ID、追加写入、重复防护"""
import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDatabaseIntegrity(unittest.TestCase):

    def test_prediction_unique_match_id(self):
        """同一match_id的预测应覆盖而非重复"""
        from utils.database import get_connection, save_prediction
        test_id = "TEST_UNIQUE_001"

        save_prediction({"match_id": test_id, "league": "测试", "home_team": "A",
                        "away_team": "B", "kickoff": "2026-01-01", "crown_index": 50,
                        "recommend": "home", "level": "C", "confidence": 50})
        save_prediction({"match_id": test_id, "league": "测试", "home_team": "A",
                        "away_team": "B", "kickoff": "2026-01-01", "crown_index": 75,
                        "recommend": "away", "level": "B", "confidence": 75})

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE match_id = ?", (test_id,))
        count = cursor.fetchone()[0]
        # 清理
        cursor.execute("DELETE FROM prediction_history WHERE match_id = ?", (test_id,))
        conn.commit()
        conn.close()

        self.assertEqual(count, 1, "同一match_id应只有1条记录(INSERT OR REPLACE)")

    def test_timeline_append_not_overwrite(self):
        """时间线必须追加，不能覆盖"""
        from utils.database import get_connection, save_timeline_record, get_timeline
        test_id = "TEST_TIMELINE_APPEND"

        save_timeline_record(test_id, {"handicap": "主让0.5", "home_water": 0.95, "away_water": 0.90})
        save_timeline_record(test_id, {"handicap": "主让0.75", "home_water": 0.90, "away_water": 0.95})

        timeline = get_timeline(test_id)

        # 清理
        conn = get_connection()
        conn.execute("DELETE FROM odds_timeline WHERE match_id = ?", (test_id,))
        conn.commit()
        conn.close()

        self.assertEqual(len(timeline), 2, "时间线应追加而非覆盖")
        self.assertEqual(timeline[0]["handicap"], "主让0.5")
        self.assertEqual(timeline[1]["handicap"], "主让0.75")

    def test_match_id_format(self):
        """match_id格式: CROWN_{league}_{home}_{away}_{date}"""
        from scraper.crown_odds_collector import build_match_id
        mid = build_match_id("瑞典超级联赛", "卡尔马", "马尔默", "07月28日")
        self.assertTrue(mid.startswith("CROWN_瑞超_"))
        self.assertIn("2026-07-28", mid)


class TestTaskLock(unittest.TestCase):

    def test_lock_acquire_release(self):
        from utils.task_lock import acquire_lock, release_lock
        self.assertTrue(acquire_lock("test_lock_001"))
        self.assertFalse(acquire_lock("test_lock_001"))  # 重复获取失败
        release_lock("test_lock_001")
        self.assertTrue(acquire_lock("test_lock_001"))  # 释放后可再获取
        release_lock("test_lock_001")

    def test_mutex_track_analyze(self):
        """track和analyze互斥"""
        from utils.task_lock import acquire_lock, release_lock
        # 清理可能残留的锁(前次pipeline运行遗留)
        release_lock("track")
        release_lock("analyze")
        self.assertTrue(acquire_lock("track"))
        self.assertFalse(acquire_lock("analyze"))  # 互斥
        release_lock("track")
        self.assertTrue(acquire_lock("analyze"))
        release_lock("analyze")


if __name__ == "__main__":
    unittest.main()
