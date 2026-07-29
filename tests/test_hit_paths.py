"""hit/hit_result读取路径测试
验证: 命中率分母排除push/no_bet/invalid; 收益按hit_result(half_win+0.5/half_loss-0.5);
push计入ROI投注分母; invalid/no_bet排除投注分母。
"""
import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHitPaths(unittest.TestCase):
    """使用临时DB验证hit/hit_result统计口径"""

    def setUp(self):
        import utils.database as db_mod
        from config.settings import MODEL_VERSION
        self.MV = MODEL_VERSION
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_hit.db")
        self._orig = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db = db_mod
        self._seed()

    def tearDown(self):
        self.db.DB_PATH = self._orig
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def _seed(self):
        conn = self.db.get_connection()
        cur = conn.cursor()
        # 6条: win, half_win, push, half_loss, loss, no_bet
        rows = [
            ("H1", "home", 1, "win"),
            ("H2", "home", 1, "half_win"),
            ("H3", "home", 2, "push"),
            ("H4", "home", 0, "half_loss"),
            ("H5", "home", 0, "loss"),
            ("H6", "neutral", 2, "no_bet"),
        ]
        for mid, rec, hit, hr in rows:
            cur.execute("""INSERT INTO prediction_history
                (match_id, league, home_team, away_team, kickoff, recommend, level,
                 hit, hit_result, model_version, crown_index)
                VALUES (?, '测试', 'A', 'B', '2026-01-01', ?, 'A', ?, ?, ?, 80)""",
                        (mid, rec, hit, hr, self.MV))
        conn.commit()
        conn.close()

    def test_hit_stats_excludes_push_from_denominator(self):
        """命中率分母=已决胜负(hit IN 0,1)=4, 不含push/no_bet"""
        stats = self.db.get_hit_stats()
        # win+half_win=2命中, half_loss+loss=2未中, decided=4
        self.assertEqual(stats["hit"], 2)
        self.assertEqual(stats["miss"], 2)
        self.assertEqual(stats["total"], 4)  # decided, 不含push/no_bet
        self.assertEqual(stats["hit_rate"], 50.0)  # 2/4
        self.assertEqual(stats["push_count"], 1)
        self.assertEqual(stats["no_bet_count"], 1)

    def test_recommendation_pnl_half_win_half_loss(self):
        """收益: half_win=+0.5, half_loss=-0.5, 非+1/-1"""
        rp = self.db.get_recommendation_pnl()
        # win(+1)+half_win(+0.5)+push(0)+half_loss(-0.5)+loss(-1) = 0.0
        self.assertAlmostEqual(rp["total_pnl"], 0.0, places=3)
        # 投注额=5(含push, 排除no_bet)
        self.assertEqual(rp["bet_count"], 5)
        self.assertEqual(rp["distribution"]["win"], 1)
        self.assertEqual(rp["distribution"]["half_win"], 1)
        self.assertEqual(rp["distribution"]["push"], 1)
        self.assertEqual(rp["distribution"]["half_loss"], 1)
        self.assertEqual(rp["distribution"]["loss"], 1)
        self.assertEqual(rp["distribution"]["no_bet"], 1)

    def test_push_in_roi_denominator(self):
        """push计入ROI投注分母"""
        rp = self.db.get_recommendation_pnl()
        # bet_count含push=5; 若排除push会是4
        self.assertEqual(rp["bet_count"], 5)
        # ROI = 0.0/5 = 0.0
        self.assertEqual(rp["roi"], 0.0)

    def test_no_bet_invalid_excluded_from_stake(self):
        """no_bet/invalid不计入投注分母"""
        rp = self.db.get_recommendation_pnl()
        # no_bet有1条但不计入bet_count(5而非6)
        self.assertEqual(rp["bet_count"], 5)


if __name__ == "__main__":
    unittest.main()
