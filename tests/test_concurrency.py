"""测试任务并发锁: 互斥关系、busy_timeout、重复写入防护"""
import sys
import os
import unittest
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.task_lock import acquire_lock, release_lock, TaskLock, LockConflictError


class TestMutexRelationships(unittest.TestCase):
    """验证互斥关系覆盖所有写冲突"""

    def setUp(self):
        # 清理残留锁
        for name in ("track", "analyze", "settle", "sync", "close", "report"):
            release_lock(name)

    def tearDown(self):
        for name in ("track", "analyze", "settle", "sync", "close", "report"):
            release_lock(name)

    def test_track_blocks_analyze(self):
        """track持锁时analyze不能获取"""
        self.assertTrue(acquire_lock("track"))
        self.assertFalse(acquire_lock("analyze"))
        release_lock("track")

    def test_track_blocks_settle(self):
        """track持锁时settle不能获取"""
        self.assertTrue(acquire_lock("track"))
        self.assertFalse(acquire_lock("settle"))
        release_lock("track")

    def test_analyze_blocks_settle(self):
        """analyze持锁时settle不能获取"""
        self.assertTrue(acquire_lock("analyze"))
        self.assertFalse(acquire_lock("settle"))
        release_lock("analyze")

    def test_settle_blocks_track(self):
        """settle持锁时track不能获取"""
        self.assertTrue(acquire_lock("settle"))
        self.assertFalse(acquire_lock("track"))
        release_lock("settle")

    def test_settle_blocks_analyze(self):
        """settle持锁时analyze不能获取"""
        self.assertTrue(acquire_lock("settle"))
        self.assertFalse(acquire_lock("analyze"))
        release_lock("settle")

    def test_sync_independent(self):
        """sync与track/analyze/settle不互斥(只写matches表)"""
        self.assertTrue(acquire_lock("track"))
        self.assertTrue(acquire_lock("sync"))  # 不冲突
        release_lock("sync")
        release_lock("track")

    def test_release_allows_reacquire(self):
        """释放后可重新获取"""
        self.assertTrue(acquire_lock("track"))
        release_lock("track")
        self.assertTrue(acquire_lock("track"))
        release_lock("track")


class TestConcurrentWriters(unittest.TestCase):
    """模拟两个写任务同时运行"""

    def setUp(self):
        release_lock("track")
        release_lock("analyze")
        release_lock("settle")

    def tearDown(self):
        release_lock("track")
        release_lock("analyze")
        release_lock("settle")

    def test_concurrent_track_analyze_one_wins(self):
        """并发获取track和analyze，只有一个成功"""
        results = {}

        def try_track():
            results["track"] = acquire_lock("track")

        def try_analyze():
            results["analyze"] = acquire_lock("analyze")

        t1 = threading.Thread(target=try_track)
        t2 = threading.Thread(target=try_analyze)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # 恰好一个成功一个失败
        self.assertNotEqual(results["track"], results["analyze"],
                           "track和analyze不应同时获取锁")

    def test_context_manager_raises_on_conflict(self):
        """TaskLock上下文管理器在冲突时抛LockConflictError"""
        self.assertTrue(acquire_lock("track"))
        with self.assertRaises(LockConflictError):
            with TaskLock("analyze"):
                pass  # 不应到达这里
        release_lock("track")

    def test_no_duplicate_closing_odds(self):
        """closing_odds有UNIQUE(match_id)，并发INSERT OR REPLACE不会重复"""
        import sqlite3
        import tempfile
        tmp = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(tmp, timeout=10)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("""CREATE TABLE closing_odds (
            match_id TEXT UNIQUE NOT NULL, handicap TEXT, home_water REAL
        )""")
        conn.commit()

        errors = []

        def writer(n):
            try:
                c = sqlite3.connect(tmp, timeout=10)
                c.execute("PRAGMA busy_timeout=5000")
                for i in range(10):
                    c.execute("INSERT OR REPLACE INTO closing_odds VALUES (?, ?, ?)",
                             (f"MATCH_{n}", f"主让0.5", 0.95))
                    c.commit()
                c.close()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 验证无错误且无重复
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM closing_odds")
        count = cursor.fetchone()[0]
        conn.close()
        os.remove(tmp)

        self.assertEqual(errors, [], f"并发写入出错: {errors}")
        self.assertEqual(count, 3, "每个match_id应只有1条(UNIQUE约束)")


class TestBusyTimeout(unittest.TestCase):
    """验证busy_timeout防止立即失败"""

    def test_connection_has_busy_timeout(self):
        """get_connection应设置busy_timeout"""
        from utils.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]
        conn.close()
        self.assertGreaterEqual(timeout, 5000)


if __name__ == "__main__":
    unittest.main()
