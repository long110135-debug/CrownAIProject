"""测试close/track/settle互斥 + closing_odds防旧覆盖 + SQLite并发写重试"""
import sys
import os
import unittest
import threading
import time
import sqlite3
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.task_lock import acquire_lock, release_lock, TaskLock, LockConflictError


class TestCloseTrackMutex(unittest.TestCase):
    """close与track互斥(共写closing_odds)"""

    def setUp(self):
        for name in ("track", "close", "settle", "analyze"):
            release_lock(name)

    def tearDown(self):
        for name in ("track", "close", "settle", "analyze"):
            release_lock(name)

    def test_close_blocks_track(self):
        """close持锁时track不能获取"""
        self.assertTrue(acquire_lock("close"))
        self.assertFalse(acquire_lock("track"))
        release_lock("close")

    def test_track_blocks_close(self):
        """track持锁时close不能获取"""
        self.assertTrue(acquire_lock("track"))
        self.assertFalse(acquire_lock("close"))
        release_lock("track")

    def test_concurrent_close_track_one_wins(self):
        """并发获取close和track，只有一个成功"""
        results = {}

        def try_close():
            results["close"] = acquire_lock("close")

        def try_track():
            results["track"] = acquire_lock("track")

        t1 = threading.Thread(target=try_close)
        t2 = threading.Thread(target=try_track)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertNotEqual(results["close"], results["track"],
                           "close和track不应同时获取锁")


class TestCloseSettleMutex(unittest.TestCase):
    """close与settle互斥(settle读closing_odds时不能被close更新)"""

    def setUp(self):
        for name in ("track", "close", "settle", "analyze"):
            release_lock(name)

    def tearDown(self):
        for name in ("track", "close", "settle", "analyze"):
            release_lock(name)

    def test_close_blocks_settle(self):
        """close持锁时settle不能获取"""
        self.assertTrue(acquire_lock("close"))
        self.assertFalse(acquire_lock("settle"))
        release_lock("close")

    def test_settle_blocks_close(self):
        """settle持锁时close不能获取"""
        self.assertTrue(acquire_lock("settle"))
        self.assertFalse(acquire_lock("close"))
        release_lock("settle")


class TestClosingOddsNewerNotOverwritten(unittest.TestCase):
    """closing_odds防旧数据覆盖: 较旧快照不能覆盖较新收盘记录"""

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_closing.db")
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()

    def tearDown(self):
        import utils.database as db_mod
        db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def test_newer_snapshot_not_overwritten(self):
        """先写一条closing，再用更早的时间戳尝试覆盖 → 不应覆盖"""
        import utils.database as db_mod

        # 第一次写入(正常)
        db_mod.save_closing_odds("MATCH_CLOSE_001", {
            "handicap": "主让0.5", "home_water": 0.92, "away_water": 0.95,
        }, source="close_first")

        # 验证写入成功
        result = db_mod.get_closing_odds("MATCH_CLOSE_001")
        self.assertIsNotNone(result)
        self.assertEqual(result["handicap"], "主让0.5")
        first_time = result["closing_time"]

        # 等待1秒确保时间戳不同
        time.sleep(1.1)

        # 第二次写入(更新的时间戳，应覆盖)
        db_mod.save_closing_odds("MATCH_CLOSE_001", {
            "handicap": "主让0.75", "home_water": 0.88, "away_water": 1.00,
        }, source="close_second")

        result2 = db_mod.get_closing_odds("MATCH_CLOSE_001")
        self.assertEqual(result2["handicap"], "主让0.75")
        self.assertGreater(result2["closing_time"], first_time)

    def test_older_cannot_overwrite(self):
        """模拟: 已有较新记录，用旧时间戳不能覆盖"""
        import utils.database as db_mod

        # 手动插入一条"未来"时间的记录
        conn = db_mod.get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO closing_odds
            (match_id, closing_time, handicap, handicap_value, home_water, away_water, source)
            VALUES (?, '2099-12-31 23:59:59', '主让1', 1.0, 0.85, 1.05, 'future')
        """, ("MATCH_FUTURE_001",))
        conn.commit()
        conn.close()

        # 尝试用当前时间覆盖(比2099年旧) → 不应覆盖
        db_mod.save_closing_odds("MATCH_FUTURE_001", {
            "handicap": "主让0.5", "home_water": 0.92, "away_water": 0.95,
        }, source="stale_track")

        result = db_mod.get_closing_odds("MATCH_FUTURE_001")
        self.assertEqual(result["handicap"], "主让1", "旧快照不应覆盖新记录")
        self.assertEqual(result["source"], "future")


class TestTwoConcurrentOddsWriters(unittest.TestCase):
    """模拟daemon和track同时写odds_timeline"""

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_concurrent.db")
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()

    def tearDown(self):
        import utils.database as db_mod
        db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def test_concurrent_writes_no_crash(self):
        """两个线程同时写odds_timeline，不应崩溃"""
        import utils.database as db_mod
        errors = []

        def writer(source, count):
            try:
                for i in range(count):
                    db_mod.save_timeline_record(
                        f"CONCURRENT_MATCH_{source}",
                        {"handicap": f"主让0.5", "home_water": 0.95, "away_water": 0.90},
                        phase="early",
                        source=source,
                    )
            except Exception as e:
                errors.append(f"{source}: {e}")

        t1 = threading.Thread(target=writer, args=("daemon", 20))
        t2 = threading.Thread(target=writer, args=("track", 20))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(errors, [], f"并发写入出错: {errors}")

        # 验证数据完整
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM odds_timeline WHERE source='daemon'")
        daemon_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM odds_timeline WHERE source='track'")
        track_count = cursor.fetchone()[0]
        conn.close()

        self.assertEqual(daemon_count, 20)
        self.assertEqual(track_count, 20)


class TestDatabaseLockedRetry(unittest.TestCase):
    """验证_retry_on_locked的行为"""

    def test_retry_success_after_transient_lock(self):
        """前两次locked，第三次成功 → 最终成功"""
        import utils.database as db_mod
        call_count = [0]

        def flaky_write():
            call_count[0] += 1
            if call_count[0] <= 2:
                raise sqlite3.OperationalError("database is locked")
            return "success"

        result = db_mod._retry_on_locked(flaky_write)
        self.assertEqual(result, "success")
        self.assertEqual(call_count[0], 3)

    def test_retry_exhausted_raises(self):
        """3次都locked → 抛异常"""
        import utils.database as db_mod

        def always_locked():
            raise sqlite3.OperationalError("database is locked")

        with self.assertRaises(sqlite3.OperationalError):
            db_mod._retry_on_locked(always_locked)

    def test_non_locked_error_not_retried(self):
        """非locked错误立即抛出，不重试"""
        import utils.database as db_mod
        call_count = [0]

        def other_error():
            call_count[0] += 1
            raise sqlite3.OperationalError("no such table: foo")

        with self.assertRaises(sqlite3.OperationalError):
            db_mod._retry_on_locked(other_error)
        self.assertEqual(call_count[0], 1, "非locked错误不应重试")


if __name__ == "__main__":
    unittest.main()
