"""测试观察期统计: 临时DB+固定样本，验证所有指标计算正确"""
import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestObservationStats(unittest.TestCase):
    """使用临时DB和固定样本验证统计逻辑"""

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_observe.db")
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db_mod = db_mod
        self._seed_data()

    def tearDown(self):
        self.db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def _seed_data(self):
        """写入固定样本数据"""
        conn = self.db_mod.get_connection()
        cursor = conn.cursor()

        # 3条prediction: 1条A级已结算命中, 1条B级已结算未命中, 1条C级未结算
        cursor.execute("""INSERT INTO prediction_history 
            (match_id, league, home_team, away_team, kickoff, crown_index, level, hit,
             model_version, model_weights, ai_decision, odds_home_water, odds_away_water,
             asian_live, recommend, clv_handicap, data_completeness)
            VALUES ('M001', '英超', '阿森纳', '切尔西', '2026-07-28 20:00', 82, 'A', 1,
             'CrownAI_1.3', '{"strength":0.25}', 'approve', 0.92, 0.95,
             '主让0.5', 'home', 0.25, 90)""")
        cursor.execute("""INSERT INTO prediction_history 
            (match_id, league, home_team, away_team, kickoff, crown_index, level, hit,
             model_version, model_weights, ai_decision, odds_home_water, odds_away_water,
             asian_live, recommend, clv_handicap, data_completeness)
            VALUES ('M002', '西甲', '巴萨', '皇马', '2026-07-28 22:00', 76, 'B', 0,
             'CrownAI_1.3', '{"strength":0.25}', 'downgrade', 0.88, 1.00,
             '主让0.25', 'home', -0.25, 85)""")
        cursor.execute("""INSERT INTO prediction_history 
            (match_id, league, home_team, away_team, kickoff, crown_index, level, hit,
             model_version, model_weights, ai_decision, odds_home_water, odds_away_water,
             asian_live, recommend, clv_handicap, data_completeness)
            VALUES ('M003', '德甲', '拜仁', '多特', '2026-07-29 20:00', 65, 'C', -1,
             'CrownAI_1.3', '{"strength":0.25}', 'approve', 0.90, 0.95,
             '主让1', 'neutral', NULL, 70)""")

        # 1条旧记录(NULL字段)
        cursor.execute("""INSERT INTO prediction_history 
            (match_id, league, home_team, away_team, kickoff, crown_index, level, hit,
             asian_live, recommend)
            VALUES ('M004', '英超', '利物浦', '曼联', '2026-07-20 20:00', 58, NULL, -1,
             '主让0.75', 'neutral')""")

        # closing_odds for M001
        cursor.execute("""INSERT INTO closing_odds 
            (match_id, closing_time, handicap, handicap_value, home_water, away_water, source)
            VALUES ('M001', '2026-07-28 19:30:00', '主让0.5', 0.5, 0.90, 0.97, 'close')""")

        # match_result for M001, M002
        cursor.execute("""INSERT INTO match_result 
            (match_id, home_score, away_score, winner, handicap_result)
            VALUES ('M001', 2, 0, 'home', 'home_cover')""")
        cursor.execute("""INSERT INTO match_result 
            (match_id, home_score, away_score, winner, handicap_result)
            VALUES ('M002', 1, 1, 'draw', 'away_cover')""")

        conn.commit()
        conn.close()

    def test_collect_observation_runs(self):
        """collect_observation不崩溃"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        self.assertIn("run_health", data)
        self.assertIn("sample_stats", data)
        self.assertIn("null_tracking", data)

    def test_sample_stats_correct(self):
        """样本统计数值正确"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        s = data["sample_stats"]
        self.assertEqual(s["total_recommendations"], 4)
        self.assertEqual(s["settled"], 2)  # M001 hit=1, M002 hit=0
        self.assertEqual(s["unsettled"], 2)  # M003, M004 hit=-1
        self.assertEqual(s["has_closing_data"], 1)  # 只有M001有closing

    def test_settlement_breakdown(self):
        """结算分布正确"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        sb = data["settlement_breakdown"]
        self.assertEqual(sb["win"], 1)  # M001 home_cover
        self.assertEqual(sb["loss"], 1)  # M002 away_cover
        self.assertEqual(sb["total"], 2)

    def test_clv_distribution(self):
        """CLV分布正确"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        clv = data["clv_distribution"]
        self.assertEqual(clv["positive"], 1)  # M001 clv=0.25
        self.assertEqual(clv["negative"], 1)  # M002 clv=-0.25
        self.assertEqual(clv["null"], 2)  # M003, M004

    def test_by_handicap_type(self):
        """盘口类型分类正确"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        ht = data["by_handicap_type"]
        self.assertEqual(ht["integer"], 1)  # M003 主让1
        self.assertEqual(ht["quarter_025"], 1)  # M002 主让0.25
        self.assertEqual(ht["half_050"], 1)  # M001 主让0.5
        self.assertEqual(ht["quarter_075"], 1)  # M004 主让0.75

    def test_null_tracking(self):
        """NULL追踪: 旧记录单独统计"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        nt = data["null_tracking"]
        self.assertEqual(nt["total_records"], 4)
        self.assertEqual(nt["null_model_version"], 1)  # M004
        self.assertEqual(nt["null_model_weights"], 1)  # M004
        self.assertEqual(nt["null_ai_decision"], 1)  # M004
        self.assertEqual(nt["null_odds_water"], 1)  # M004

    def test_neutral_analysis(self):
        """Neutral分析"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        na = data["neutral_analysis"]
        self.assertEqual(na["total_neutral"], 2)  # M003, M004

    def test_by_level(self):
        """按等级统计"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        levels = {lv["level"]: lv for lv in data["by_level"]}
        self.assertIn("A", levels)
        self.assertEqual(levels["A"]["total"], 1)
        self.assertEqual(levels["A"]["hit"], 1)

    def test_by_league(self):
        """按联赛统计"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        leagues = {lg["league"]: lg for lg in data["by_league"]}
        self.assertIn("英超", leagues)
        self.assertEqual(leagues["英超"]["total"], 2)  # M001 + M004

    def test_near_threshold(self):
        """距门槛1~3分: 无(本样本中无72-75分记录)"""
        from pipeline.observation import collect_observation
        data = collect_observation()
        self.assertEqual(len(data["near_threshold"]), 0)

    def test_print_observation_no_crash(self):
        """终端输出不崩溃"""
        from pipeline.observation import collect_observation, print_observation
        data = collect_observation()
        print_observation(data)  # 不崩溃即可

    def test_generate_html(self):
        """HTML报表生成"""
        from pipeline.observation import collect_observation, generate_observation_html
        data = collect_observation()
        path = generate_observation_html(data, output_dir=self.tmp_dir)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            content = f.read()
        self.assertIn("观察期统计", content)
        self.assertIn("NULL追踪", content)

    def test_read_only_no_writes(self):
        """observe不修改数据库"""
        from pipeline.observation import collect_observation
        conn = self.db_mod.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prediction_history")
        before = cursor.fetchone()[0]
        conn.close()

        collect_observation()

        conn = self.db_mod.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prediction_history")
        after = cursor.fetchone()[0]
        conn.close()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
