"""测试daily_run集成: mock网络，验证完整sync→track→analyze流程"""
import sys
import os
import unittest
import tempfile
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestDailyRunIntegration(unittest.TestCase):
    """使用临时DB + mock网络，验证完整流水线"""

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_integration.db")
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db_mod = db_mod

    def tearDown(self):
        self.db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def _seed_match(self, match_id="CROWN_英超_阿森纳_切尔西_2026-07-28",
                    league="英超", home="阿森纳", away="切尔西", hours_ahead=3):
        """写入一场待分析比赛+盘口时间线"""
        kickoff = (datetime.now() + timedelta(hours=hours_ahead)).strftime("%Y-%m-%d %H:%M")
        self.db_mod.save_match({
            "match_id": match_id, "league": league, "league_tier": 1,
            "home_team": home, "away_team": away,
            "match_time": kickoff, "status": "pending",
        })
        # 写入2条时间线满足L2
        self.db_mod.save_timeline_record(match_id, {
            "handicap": "主让0.5", "home_water": 0.92, "away_water": 0.95,
        }, phase="early", source="test")
        self.db_mod.save_timeline_record(match_id, {
            "handicap": "主让0.75", "home_water": 0.88, "away_water": 1.00,
        }, phase="early", source="test")
        return match_id

    # === 核心流程测试 ===

    def test_analyze_writes_prediction(self):
        """analyze后prediction_history有记录"""
        from pipeline.daily_run import analyze_matches
        mid = self._seed_match()

        result = analyze_matches(hours_ahead=6)
        self.assertEqual(result["analyzed"], 1)

        conn = self.db_mod.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE match_id = ?", (mid,))
        self.assertEqual(cursor.fetchone()[0], 1)
        conn.close()

    def test_analyze_writes_funnel(self):
        """analyze后filter_funnel有当日记录"""
        from pipeline.daily_run import analyze_matches
        self._seed_match()
        analyze_matches(hours_ahead=6)

        conn = self.db_mod.get_connection()
        cursor = conn.cursor()
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("SELECT COUNT(*) FROM filter_funnel WHERE log_date = ?", (today,))
        self.assertGreaterEqual(cursor.fetchone()[0], 1)
        conn.close()

    def test_duplicate_match_no_duplicate_prediction(self):
        """同一比赛重复analyze不产生重复推荐(INSERT OR REPLACE)"""
        from pipeline.daily_run import analyze_matches
        mid = self._seed_match()

        analyze_matches(hours_ahead=6)
        analyze_matches(hours_ahead=6)  # 第二次

        conn = self.db_mod.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE match_id = ?", (mid,))
        count = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(count, 1, "重复运行不应产生多条prediction")

    def test_l2_rejects_no_timeline(self):
        """无时间线的比赛被L2过滤"""
        from pipeline.daily_run import analyze_matches
        kickoff = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
        self.db_mod.save_match({
            "match_id": "CROWN_英超_无盘口_队_2026-07-28", "league": "英超", "league_tier": 1,
            "home_team": "无盘口", "away_team": "队",
            "match_time": kickoff, "status": "pending",
        })
        result = analyze_matches(hours_ahead=6)
        self.assertEqual(result["analyzed"], 0)
        self.assertGreater(result["l2_rejected"], 0)

    def test_multiple_matches_all_analyzed(self):
        """多场比赛全部被分析"""
        from pipeline.daily_run import analyze_matches
        self._seed_match("CROWN_英超_A_B_2026-07-28", home="A", away="B")
        self._seed_match("CROWN_西甲_C_D_2026-07-28", league="西甲", home="C", away="D")
        self._seed_match("CROWN_德甲_E_F_2026-07-28", league="德甲", home="E", away="F")

        result = analyze_matches(hours_ahead=6)
        self.assertEqual(result["analyzed"], 3)

    # === sync mock测试(不访问真实网络) ===

    @patch("scraper.apifootball_data.APIFootballClient")
    def test_sync_today_mock(self, mock_client_cls):
        """sync_today使用mock API，不访问网络"""
        from pipeline.daily_run import sync_today

        mock_client = MagicMock()
        mock_client.api_key = "fake_key"
        mock_client._request.return_value = {
            "results": 1,
            "response": [{
                "fixture": {"id": 999, "date": "2026-07-28T20:00:00+00:00"},
                "teams": {"home": {"name": "Arsenal"}, "away": {"name": "Chelsea"}},
            }]
        }
        mock_client_cls.return_value = mock_client

        count = sync_today()
        # 可能为0(队名映射不到中文)或>0，关键是不崩溃
        self.assertIsInstance(count, int)

    # === track mock测试 ===

    @patch("scraper.apifootball_odds.fetch_odds_for_fixture")
    @patch("scraper.apifootball_data.APIFootballClient")
    def test_track_odds_mock(self, mock_client_cls, mock_fetch):
        """track_odds使用mock，不访问网络"""
        from pipeline.daily_run import track_odds

        # 先seed一场pending比赛
        kickoff = (datetime.now() + timedelta(hours=4)).strftime("%Y-%m-%d %H:%M")
        self.db_mod.save_match({
            "match_id": "CROWN_英超_测试1_测试2_2026-07-28", "league": "英超", "league_tier": 1,
            "home_team": "测试1", "away_team": "测试2",
            "match_time": kickoff, "status": "pending",
        })

        mock_client = MagicMock()
        mock_client.api_key = "fake"
        mock_client_cls.return_value = mock_client
        mock_fetch.return_value = {"handicap": "主让0.5", "home_water": 0.92, "away_water": 0.95, "bookmaker": "Bet365"}

        # track_odds内部会调_resolve_fixture_id，需要mock
        with patch("pipeline.daily_run._resolve_fixture_id", return_value=999):
            count = track_odds()

        self.assertIsInstance(count, int)

    # === 入口等价性测试 ===

    def test_main_and_scheduler_call_same_daily_run(self):
        """main.py和scheduler.py都调用daily_run的同一函数"""
        import inspect
        import main
        import scheduler

        main_src = inspect.getsource(main)
        scheduler_src = inspect.getsource(scheduler)

        # 两者都引用daily_run
        self.assertIn("daily_run", main_src)
        self.assertIn("daily_run", scheduler_src)

        # scheduler不包含模型实例化(业务逻辑不在scheduler)
        self.assertNotIn("StrengthModel", scheduler_src)
        self.assertNotIn("HandicapModel", scheduler_src)
        self.assertNotIn("calc_crown_index", scheduler_src)

    def test_scheduler_uses_task_lock(self):
        """scheduler的track/analyze/settle/close都使用TaskLock"""
        import inspect
        import scheduler
        src = inspect.getsource(scheduler)
        self.assertIn("TaskLock", src)
        # 至少4个命令使用锁
        self.assertGreaterEqual(src.count("TaskLock("), 4)

    # === 输出字段完整性 ===

    def test_prediction_has_snapshot_fields(self):
        """prediction记录包含推荐时快照字段"""
        from pipeline.daily_run import analyze_matches
        mid = self._seed_match()
        analyze_matches(hours_ahead=6)

        conn = self.db_mod.get_connection()
        conn.row_factory = None
        cursor = conn.cursor()
        cursor.execute("""SELECT model_version, model_weights, ai_decision, 
                         odds_home_water, odds_away_water 
                         FROM prediction_history WHERE match_id = ?""", (mid,))
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        # model_version应为非空字符串
        self.assertIsInstance(row[0], str)
        # model_weights应为JSON字符串
        self.assertIsInstance(row[1], str)
        # odds_home_water应为数值(可能为None如果odds为空)
        # 这里我们seed了timeline，所以应该有值


class TestDailyRunNoNetworkAccess(unittest.TestCase):
    """验证daily_run不直接导入网络库"""

    def test_no_requests_import(self):
        """daily_run不直接import requests"""
        import inspect
        import pipeline.daily_run as dr
        src = inspect.getsource(dr)
        # 不应有顶层import requests
        lines = [l for l in src.split('\n') if l.strip().startswith('import requests')]
        self.assertEqual(lines, [])

    def test_no_playwright_import(self):
        """daily_run不直接import playwright"""
        import inspect
        import pipeline.daily_run as dr
        src = inspect.getsource(dr)
        lines = [l for l in src.split('\n') if 'playwright' in l and not l.strip().startswith('#')]
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
