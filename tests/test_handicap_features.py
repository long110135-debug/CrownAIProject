"""标准化盘口特征接口 + 数据质量门控测试
验证: 特征字段完整; 数据质量不足时水位特征为None;
非Asian Handicap/unknown格式被门控排除; 同公司同线才计算水位动态。
"""
import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestHandicapFeatures(unittest.TestCase):

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_feat.db")
        self._orig = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db = db_mod

    def tearDown(self):
        self.db.DB_PATH = self._orig
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def _seed_match(self, match_id="M1"):
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("""INSERT INTO matches (match_id, league, home_team, away_team, match_time, status)
                       VALUES (?, '测试', 'A', 'B', '2026-12-31 20:00', 'pending')""", (match_id,))
        conn.commit()
        conn.close()

    def _write_primary(self, match_id, handicap, hw, aw, t, fmt="decimal", bm="Bet365"):
        from utils.odds_math import handicap_to_number
        from pipeline.odds_series import make_series_key, get_primary_bookmaker
        conn = self.db.get_connection()
        cur = conn.cursor()
        hv = handicap_to_number(handicap)
        primary = get_primary_bookmaker(match_id)
        eff = primary or bm
        is_primary = 1 if bm == eff else 0
        sk = make_series_key(match_id, bm, "asian_handicap", hv)
        cur.execute("""INSERT INTO odds_timeline
            (match_id, phase, record_time, handicap, handicap_value, home_water, away_water,
             source, bookmaker, market_type, odds_format, home_water_normalized, away_water_normalized,
             is_primary_series, series_key)
            VALUES (?, 'early', ?, ?, ?, ?, ?, ?, ?, 'asian_handicap', ?, ?, ?, ?, ?)""",
                    (match_id, t, handicap, hv, hw, aw, f"api-football({bm})", bm, fmt, hw, aw, is_primary, sk))
        conn.commit()
        conn.close()

    def test_feature_fields_complete(self):
        """特征接口返回全部标准字段"""
        from pipeline.handicap_features import extract_handicap_features
        self._seed_match()
        self._write_primary("M1", "客让0.25", 0.32, 1.30, "2026-12-30 10:00:00")
        self._write_primary("M1", "客让0.25", 0.35, 0.90, "2026-12-30 12:00:00")
        f = extract_handicap_features("M1")
        for key in ["opening_handicap", "current_handicap", "line_change",
                    "favorite_side", "underdog_side", "favorite_open_water",
                    "favorite_current_water", "favorite_water_change",
                    "underdog_open_water", "underdog_current_water", "underdog_water_change",
                    "bookmaker", "snapshot_count", "data_quality", "prematch_minutes"]:
            self.assertIn(key, f)
        # 客让0.25 → away是让球方(热门)
        self.assertEqual(f["favorite_side"], "away")
        self.assertEqual(f["underdog_side"], "home")
        self.assertEqual(f["bookmaker"], "Bet365")
        self.assertEqual(f["snapshot_count"], 2)

    def test_water_features_computed_when_stable(self):
        """稳定主序列(同公司同线≥2)时计算水位动态"""
        from pipeline.handicap_features import extract_handicap_features
        self._seed_match()
        self._write_primary("M1", "客让0.25", 0.32, 1.30, "2026-12-30 10:00:00")
        self._write_primary("M1", "客让0.25", 0.35, 0.90, "2026-12-30 12:00:00")
        f = extract_handicap_features("M1")
        self.assertTrue(f["data_quality"]["usable"])
        # away(让球方)水位 1.30 → 0.90
        self.assertIsNotNone(f["favorite_water_change"])
        self.assertAlmostEqual(f["favorite_water_change"], 0.90 - 1.30, places=3)

    def test_water_features_none_when_insufficient(self):
        """快照不足时水位特征为None(不计算)"""
        from pipeline.handicap_features import extract_handicap_features
        self._seed_match()
        self._write_primary("M1", "客让0.25", 0.32, 1.30, "2026-12-30 10:00:00")  # 仅1条
        f = extract_handicap_features("M1")
        self.assertFalse(f["data_quality"]["usable"])
        self.assertTrue(f["data_quality"]["insufficient_snapshots"])
        self.assertIsNone(f["favorite_water_change"])

    def test_water_features_none_when_line_changed(self):
        """盘口线变化时水位特征为None(不同线不比水位)"""
        from pipeline.handicap_features import extract_handicap_features
        self._seed_match()
        self._write_primary("M1", "客让0.25", 0.32, 1.30, "2026-12-30 10:00:00")
        self._write_primary("M1", "客让0.5", 0.30, 1.95, "2026-12-30 12:00:00")  # 线变
        f = extract_handicap_features("M1")
        self.assertTrue(f["data_quality"]["line_changed"])
        self.assertFalse(f["data_quality"]["usable"])
        self.assertIsNone(f["favorite_water_change"])
        # line_change 仍记录
        self.assertAlmostEqual(f["line_change"], -0.5 - (-0.25), places=3)

    def test_unknown_format_gated(self):
        """unknown odds format 被门控排除"""
        from pipeline.handicap_features import extract_handicap_features
        self._seed_match()
        self._write_primary("M1", "客让0.25", 0.32, 1.30, "2026-12-30 10:00:00", fmt="")
        self._write_primary("M1", "客让0.25", 0.35, 0.90, "2026-12-30 12:00:00", fmt="")
        f = extract_handicap_features("M1")
        self.assertTrue(f["data_quality"]["unknown_format"])
        self.assertFalse(f["data_quality"]["usable"])


if __name__ == "__main__":
    unittest.main()
