"""测试调度器: 命令分发、锁集成"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestSchedulerCommands(unittest.TestCase):

    def test_all_commands_exist(self):
        """7个命令都应存在"""
        from scheduler import cmd_sync, cmd_track, cmd_analyze, cmd_close, cmd_settle, cmd_report, cmd_watchdog
        commands = [cmd_sync, cmd_track, cmd_analyze, cmd_close, cmd_settle, cmd_report, cmd_watchdog]
        self.assertEqual(len(commands), 7)

    def test_track_uses_lock(self):
        """track应使用TaskLock"""
        import inspect
        from scheduler import cmd_track
        src = inspect.getsource(cmd_track)
        self.assertIn("TaskLock", src)

    def test_analyze_uses_lock(self):
        """analyze应使用TaskLock"""
        import inspect
        from scheduler import cmd_analyze
        src = inspect.getsource(cmd_analyze)
        self.assertIn("TaskLock", src)

    def test_scheduler_no_business_logic(self):
        """scheduler不应包含模型分析逻辑"""
        import inspect
        import scheduler
        src = inspect.getsource(scheduler)
        self.assertNotIn("StrengthModel", src)
        self.assertNotIn("calc_crown_index", src)
        self.assertNotIn("HandicapModel", src)


class TestDailyRunIsSoleEntry(unittest.TestCase):

    def test_main_calls_daily_run(self):
        """main.py应调用daily_run"""
        import inspect
        import main
        src = inspect.getsource(main)
        self.assertIn("daily_run", src)
        self.assertNotIn("StrengthModel", src)

    def test_daily_run_has_all_functions(self):
        """daily_run应包含所有业务函数"""
        from pipeline.daily_run import (
            sync_today, track_odds, analyze_matches,
            close_odds, settle_matches, generate_reports, run_full
        )
        self.assertTrue(callable(sync_today))
        self.assertTrue(callable(run_full))


if __name__ == "__main__":
    unittest.main()
