"""测试daily_run端到端: sync→track→analyze完整流程(使用临时DB)"""
import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDailyRunEndToEnd(unittest.TestCase):
    """端到端流程测试(不依赖外部API，验证内部编排逻辑)"""

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_e2e.db")
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()

    def tearDown(self):
        import utils.database as db_mod
        db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def test_analyze_matches_empty_db(self):
        """空数据库analyze不崩溃，返回0"""
        from pipeline.daily_run import analyze_matches
        result = analyze_matches(hours_ahead=24)
        self.assertEqual(result["analyzed"], 0)
        self.assertEqual(result["level_a"], 0)

    def test_analyze_with_match_and_odds(self):
        """有比赛+盘口数据时analyze正常输出"""
        import utils.database as db_mod
        from pipeline.daily_run import analyze_matches
        from datetime import datetime, timedelta

        # 写入一场6小时内开赛的比赛
        kickoff = (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M")
        match_id = "CROWN_英超_阿森纳_切尔西_2026-07-28"
        db_mod.save_match({
            "match_id": match_id, "league": "英超", "league_tier": 1,
            "home_team": "阿森纳", "away_team": "切尔西",
            "match_time": kickoff, "status": "pending",
        })

        # 写入2条盘口时间线(满足L2过滤)
        db_mod.save_timeline_record(match_id, {
            "handicap": "主让0.5", "home_water": 0.92, "away_water": 0.95,
        }, phase="early", source="test")
        db_mod.save_timeline_record(match_id, {
            "handicap": "主让0.75", "home_water": 0.88, "away_water": 1.00,
        }, phase="early", source="test")

        result = analyze_matches(hours_ahead=6)
        self.assertEqual(result["analyzed"], 1)
        self.assertIn(result["level_a"] + result["level_b"] + result["level_c"], (0, 1))

    def test_analyze_l2_filter_rejects_no_odds(self):
        """无盘口数据的比赛被L2过滤"""
        import utils.database as db_mod
        from pipeline.daily_run import analyze_matches
        from datetime import datetime, timedelta

        kickoff = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        db_mod.save_match({
            "match_id": "CROWN_英超_无盘口_队_2026-07-28", "league": "英超", "league_tier": 1,
            "home_team": "无盘口", "away_team": "队",
            "match_time": kickoff, "status": "pending",
        })
        # 不写时间线 → L2应过滤

        result = analyze_matches(hours_ahead=6)
        self.assertEqual(result["analyzed"], 0)
        self.assertGreater(result["l2_rejected"], 0)

    def test_prediction_written_after_analyze(self):
        """analyze后prediction_history有记录"""
        import utils.database as db_mod
        from pipeline.daily_run import analyze_matches
        from datetime import datetime, timedelta

        kickoff = (datetime.now() + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")
        match_id = "CROWN_西甲_巴萨_皇马_2026-07-28"
        db_mod.save_match({
            "match_id": match_id, "league": "西甲", "league_tier": 1,
            "home_team": "巴萨", "away_team": "皇马",
            "match_time": kickoff, "status": "pending",
        })
        db_mod.save_timeline_record(match_id, {
            "handicap": "主让0.25", "home_water": 0.95, "away_water": 0.92,
        }, phase="early", source="test")
        db_mod.save_timeline_record(match_id, {
            "handicap": "主让0.25", "home_water": 0.93, "away_water": 0.94,
        }, phase="early", source="test")

        analyze_matches(hours_ahead=6)

        conn = db_mod.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE match_id = ?", (match_id,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)

    def test_funnel_written(self):
        """analyze后filter_funnel有记录"""
        import utils.database as db_mod
        from pipeline.daily_run import analyze_matches
        from datetime import datetime, timedelta

        kickoff = (datetime.now() + timedelta(hours=5)).strftime("%Y-%m-%d %H:%M")
        db_mod.save_match({
            "match_id": "CROWN_德甲_拜仁_多特_2026-07-28", "league": "德甲", "league_tier": 1,
            "home_team": "拜仁", "away_team": "多特",
            "match_time": kickoff, "status": "pending",
        })
        db_mod.save_timeline_record("CROWN_德甲_拜仁_多特_2026-07-28", {
            "handicap": "主让1", "home_water": 0.90, "away_water": 0.95,
        }, phase="early", source="test")
        db_mod.save_timeline_record("CROWN_德甲_拜仁_多特_2026-07-28", {
            "handicap": "主让1", "home_water": 0.88, "away_water": 0.97,
        }, phase="early", source="test")

        analyze_matches(hours_ahead=6)

        conn = db_mod.get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT COUNT(*) FROM filter_funnel WHERE log_date = ?", (today,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertGreaterEqual(count, 1)


class TestDailyRunFunctionSignatures(unittest.TestCase):
    """验证daily_run导出的函数签名正确"""

    def test_all_functions_callable(self):
        from pipeline.daily_run import (
            sync_today, track_odds, analyze_matches,
            close_odds, settle_matches, generate_reports, run_full
        )
        self.assertTrue(callable(sync_today))
        self.assertTrue(callable(track_odds))
        self.assertTrue(callable(analyze_matches))
        self.assertTrue(callable(close_odds))
        self.assertTrue(callable(settle_matches))
        self.assertTrue(callable(generate_reports))
        self.assertTrue(callable(run_full))


if __name__ == "__main__":
    unittest.main()
