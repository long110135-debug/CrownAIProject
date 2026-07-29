"""盘口序列管理测试
验证: 同bookmaker同盘口线可比水位; bookmaker切换禁止拼接;
handicap line切换只产生line_move; primary bookmaker固定不切换。
"""
import sys
import os
import unittest
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestOddsSeries(unittest.TestCase):

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_series.db")
        self._orig = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db = db_mod

    def tearDown(self):
        self.db.DB_PATH = self._orig
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)

    def _write(self, match_id, bookmaker, handicap, hw, aw, t):
        """写入一条带bookmaker的盘口记录(直接插库模拟不同公司/时间)"""
        from utils.odds_math import handicap_to_number
        from pipeline.odds_series import make_series_key, get_primary_bookmaker
        conn = self.db.get_connection()
        cur = conn.cursor()
        hv = handicap_to_number(handicap)
        primary = get_primary_bookmaker(match_id)
        eff = primary or bookmaker
        is_primary = 1 if bookmaker == eff else 0
        sk = make_series_key(match_id, bookmaker, "asian_handicap", hv)
        cur.execute("""INSERT INTO odds_timeline
            (match_id, phase, record_time, handicap, handicap_value, home_water, away_water,
             source, bookmaker, market_type, odds_format, home_water_normalized, away_water_normalized,
             is_primary_series, series_key, captured_at_utc)
            VALUES (?, 'early', ?, ?, ?, ?, ?, ?, ?, 'asian_handicap', 'decimal', ?, ?, ?, ?, ?)""",
                    (match_id, t, handicap, hv, hw, aw, f"api-football({bookmaker})",
                     bookmaker, hw, aw, is_primary, sk, t))
        conn.commit()
        conn.close()

    def test_series_key_format(self):
        from pipeline.odds_series import make_series_key
        sk = make_series_key("M1", "Bet365", "asian_handicap", -0.25)
        self.assertEqual(sk, "M1|Bet365|asian_handicap|-0.25")

    def test_primary_bookmaker_is_first(self):
        """primary bookmaker = 最早有效记录的公司, 固定不切换"""
        from pipeline.odds_series import get_primary_bookmaker
        self._write("M1", "Bet365", "客让0.25", 0.32, 1.30, "2026-01-01 10:00:00")
        self._write("M1", "Marathonbet", "平手", 1.38, 2.62, "2026-01-01 11:00:00")
        # primary 仍是 Bet365(最早), 不因后续Marathonbet切换
        self.assertEqual(get_primary_bookmaker("M1"), "Bet365")

    def test_is_primary_series_flag(self):
        """非primary公司记录 is_primary_series=0"""
        self._write("M1", "Bet365", "客让0.25", 0.32, 1.30, "2026-01-01 10:00:00")
        self._write("M1", "Marathonbet", "平手", 1.38, 2.62, "2026-01-01 11:00:00")
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT bookmaker, is_primary_series FROM odds_timeline WHERE match_id='M1' ORDER BY record_time")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        self.assertEqual(rows[0]["is_primary_series"], 1)  # Bet365 primary
        self.assertEqual(rows[1]["is_primary_series"], 0)  # Marathonbet 非primary

    def test_line_move_detected_within_primary(self):
        """同一primary公司盘口线变化 → line_move"""
        from pipeline.odds_series import detect_line_moves
        self._write("M1", "Bet365", "客让0.25", 0.32, 1.30, "2026-01-01 10:00:00")
        self._write("M1", "Bet365", "客让0.5", 0.30, 1.95, "2026-01-01 12:00:00")
        moves = detect_line_moves("M1")
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0]["from_value"], -0.25)
        self.assertEqual(moves[0]["to_value"], -0.5)
        self.assertEqual(moves[0]["direction"], "降盘")

    def test_bookmaker_switch_not_line_move(self):
        """bookmaker切换造成的盘口差异不算line_move(只统计primary序列内)"""
        from pipeline.odds_series import detect_line_moves
        # Bet365 客让0.25, 然后切到Marathonbet 平手 — 不是真实line_move
        self._write("M1", "Bet365", "客让0.25", 0.32, 1.30, "2026-01-01 10:00:00")
        self._write("M1", "Marathonbet", "平手", 1.38, 2.62, "2026-01-01 11:00:00")
        moves = detect_line_moves("M1")
        # primary序列只有Bet365一条, 无line_move
        self.assertEqual(len(moves), 0)

    def test_same_bookmaker_same_line_water_comparable(self):
        """同bookmaker同盘口线的多条记录series_key相同(可比水位)"""
        self._write("M1", "Bet365", "客让0.25", 0.32, 1.30, "2026-01-01 10:00:00")
        self._write("M1", "Bet365", "客让0.25", 0.35, 0.90, "2026-01-01 11:00:00")
        conn = self.db.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT series_key FROM odds_timeline WHERE match_id='M1'")
        keys = [r[0] for r in cur.fetchall()]
        conn.close()
        # 同公司同线 → 同一series_key
        self.assertEqual(len(keys), 1)


if __name__ == "__main__":
    unittest.main()
