"""测试影子对照实验: legacy vs consensus方向记录、结算、统计"""
import sys
import os
import unittest
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestShadowExperimentBase(unittest.TestCase):
    """基础测试: 使用临时DB"""

    def setUp(self):
        import utils.database as db_mod
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test_shadow.db")
        self._orig_path = db_mod.DB_PATH
        db_mod.DB_PATH = self.db_path
        db_mod.init_db()
        self.db_mod = db_mod

    def tearDown(self):
        self.db_mod.DB_PATH = self._orig_path
        for f in os.listdir(self.tmp_dir):
            os.remove(os.path.join(self.tmp_dir, f))
        os.rmdir(self.tmp_dir)


class TestShadowRecordSaving(TestShadowExperimentBase):
    """记录保存测试"""

    def test_legacy_recommend_unchanged(self):
        """save_experiment不影响prediction_history的recommend字段"""
        self.db_mod.save_prediction({
            'match_id': 'M001', 'league': '英超', 'home_team': 'A', 'away_team': 'B',
            'kickoff': '2026-07-28 20:00', 'crown_index': 78,
            'recommend': 'home', 'level': 'B', 'confidence': 78,
        })
        self.db_mod.save_experiment({
            'match_id': 'M001', 'model_version': 'v1',
            'legacy_recommend': 'home', 'consensus_recommend': 'away',
            'consensus_weights': {'strength': 0.25}, 'consensus_reason': 'test',
        })
        # prediction_history.recommend应保持不变
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT recommend FROM prediction_history WHERE match_id='M001'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 'home')

    def test_consensus_recommend_saved(self):
        """consensus_recommend正确保存到实验表"""
        self.db_mod.save_experiment({
            'match_id': 'M002', 'model_version': 'v1',
            'legacy_recommend': 'neutral', 'consensus_recommend': 'home',
            'consensus_weights': {'strength': 0.25, 'handicap': 0.30},
            'consensus_reason': 'handicap:home | market:home',
        })
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_recommend, consensus_recommend FROM recommendation_experiments WHERE match_id='M002'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 'neutral')
        self.assertEqual(row[1], 'home')

    def test_consensus_weights_snapshot_saved(self):
        """consensus_weights保存为JSON快照"""
        weights = {'strength': 0.25, 'handicap': 0.30, 'squad': 0.15, 'market': 0.20, 'ai_referee': 0.10}
        self.db_mod.save_experiment({
            'match_id': 'M003', 'model_version': 'v1',
            'legacy_recommend': 'home', 'consensus_recommend': 'home',
            'consensus_weights': weights, 'consensus_reason': 'test',
        })
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT consensus_weights FROM recommendation_experiments WHERE match_id='M003'")
        row = cur.fetchone()
        conn.close()
        saved_weights = json.loads(row[0])
        self.assertEqual(saved_weights, weights)

    def test_upsert_does_not_overwrite_settled(self):
        """重复save_experiment更新分析字段但不覆盖已结算字段"""
        self.db_mod.save_experiment({
            'match_id': 'M004', 'model_version': 'v1',
            'legacy_recommend': 'home', 'consensus_recommend': 'away',
            'consensus_weights': {}, 'consensus_reason': 'first',
        })
        # 结算
        self.db_mod.settle_experiment('M004', 'win', 'loss', 1.0, -1.0)
        # 重复保存(模拟重复analyze)
        self.db_mod.save_experiment({
            'match_id': 'M004', 'model_version': 'v2',
            'legacy_recommend': 'away', 'consensus_recommend': 'home',
            'consensus_weights': {}, 'consensus_reason': 'second',
        })
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_recommend, consensus_recommend, legacy_hit, consensus_hit, legacy_pnl FROM recommendation_experiments WHERE match_id='M004'")
        row = cur.fetchone()
        conn.close()
        # 分析字段被更新
        self.assertEqual(row[0], 'away')
        self.assertEqual(row[1], 'home')
        # 结算字段保持不变
        self.assertEqual(row[2], 'win')
        self.assertEqual(row[3], 'loss')
        self.assertEqual(row[4], 1.0)


class TestShadowSettlement(TestShadowExperimentBase):
    """结算测试"""

    def _setup_experiment(self, match_id, legacy, consensus):
        self.db_mod.save_experiment({
            'match_id': match_id, 'model_version': 'v1',
            'legacy_recommend': legacy, 'consensus_recommend': consensus,
            'consensus_weights': {}, 'consensus_reason': 'test',
        })

    def test_shadow_settlement_win(self):
        """方向正确 → win (+1)"""
        self._setup_experiment('W1', 'home', 'home')
        self.db_mod.settle_experiment('W1', 'win', 'win', 1.0, 1.0)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_hit, consensus_hit, legacy_pnl, consensus_pnl FROM recommendation_experiments WHERE match_id='W1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 'win')
        self.assertEqual(row[2], 1.0)

    def test_shadow_settlement_half_win(self):
        """半赢 → half_win (+0.5)"""
        self._setup_experiment('HW1', 'home', 'home')
        self.db_mod.settle_experiment('HW1', 'half_win', 'half_win', 0.5, 0.5)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_pnl, consensus_pnl FROM recommendation_experiments WHERE match_id='HW1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 0.5)

    def test_shadow_settlement_push(self):
        """走盘 → push (0)"""
        self._setup_experiment('P1', 'home', 'home')
        self.db_mod.settle_experiment('P1', 'push', 'push', 0.0, 0.0)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_pnl FROM recommendation_experiments WHERE match_id='P1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 0.0)

    def test_shadow_settlement_half_loss(self):
        """半输 → half_loss (-0.5)"""
        self._setup_experiment('HL1', 'home', 'home')
        self.db_mod.settle_experiment('HL1', 'half_loss', 'half_loss', -0.5, -0.5)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_pnl FROM recommendation_experiments WHERE match_id='HL1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], -0.5)

    def test_shadow_settlement_loss(self):
        """方向错误 → loss (-1)"""
        self._setup_experiment('L1', 'home', 'away')
        self.db_mod.settle_experiment('L1', 'loss', 'win', -1.0, 1.0)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_hit, consensus_hit, legacy_pnl, consensus_pnl FROM recommendation_experiments WHERE match_id='L1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 'loss')
        self.assertEqual(row[1], 'win')
        self.assertEqual(row[2], -1.0)
        self.assertEqual(row[3], 1.0)

    def test_shadow_settlement_idempotent(self):
        """重复结算不覆盖"""
        self._setup_experiment('IDEM1', 'home', 'home')
        self.db_mod.settle_experiment('IDEM1', 'win', 'win', 1.0, 1.0)
        # 重复结算
        self.db_mod.settle_experiment('IDEM1', 'loss', 'loss', -1.0, -1.0)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_hit, legacy_pnl FROM recommendation_experiments WHERE match_id='IDEM1'")
        row = cur.fetchone()
        conn.close()
        # 应保持第一次结算结果
        self.assertEqual(row[0], 'win')
        self.assertEqual(row[1], 1.0)

    def test_neutral_excluded_from_hit_rate(self):
        """neutral → no_bet, PnL=None, 不进入命中率分母"""
        self._setup_experiment('NB1', 'neutral', 'home')
        self.db_mod.settle_experiment('NB1', 'no_bet', 'win', None, 1.0)
        conn = self.db_mod.get_connection()
        cur = conn.cursor()
        cur.execute("SELECT legacy_hit, legacy_pnl, consensus_hit, consensus_pnl FROM recommendation_experiments WHERE match_id='NB1'")
        row = cur.fetchone()
        conn.close()
        self.assertEqual(row[0], 'no_bet')
        self.assertIsNone(row[1])  # PnL=None
        self.assertEqual(row[2], 'win')
        self.assertEqual(row[3], 1.0)


class TestDirectionToHit(unittest.TestCase):
    """_direction_to_hit结算逻辑"""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from settle import _direction_to_hit
        self.fn = _direction_to_hit

    def test_home_wins(self):
        self.assertEqual(self.fn('home', 'home', ''), 'win')

    def test_home_loses(self):
        self.assertEqual(self.fn('home', 'away', ''), 'loss')

    def test_neutral_no_bet(self):
        self.assertEqual(self.fn('neutral', 'home', ''), 'no_bet')

    def test_empty_no_bet(self):
        self.assertEqual(self.fn('', 'home', ''), 'no_bet')

    def test_draw_invalid(self):
        self.assertEqual(self.fn('draw', 'home', ''), 'invalid')

    def test_home_draw_home_cover(self):
        self.assertEqual(self.fn('home', 'draw', 'home_cover'), 'win')

    def test_home_draw_away_cover(self):
        self.assertEqual(self.fn('home', 'draw', 'away_cover'), 'loss')

    def test_home_draw_push(self):
        self.assertEqual(self.fn('home', 'draw', 'push'), 'push')

    def test_away_wins(self):
        self.assertEqual(self.fn('away', 'away', ''), 'win')

    def test_away_loses(self):
        self.assertEqual(self.fn('away', 'home', ''), 'loss')


class TestConsensusDirection(unittest.TestCase):
    """共识算法测试"""

    def setUp(self):
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from pipeline.recommender import _consensus_direction
        self.fn = _consensus_direction

    def test_strength_neutral_consensus_home(self):
        """Hearts vs Sturm: strength=neutral, handicap=home, market=home → consensus=home"""
        model_results = {
            'strength': {'direction': 'neutral', 'confidence': 20},
            'handicap': {'direction': 'home', 'confidence': 62},
            'market': {'direction': 'home', 'confidence': 64},
            'squad': {'direction': 'neutral', 'confidence': 35},
            'ai_referee': {'direction': 'home', 'confidence': 55},
        }
        self.assertEqual(self.fn(model_results), 'home')

    def test_consensus_tie_behavior(self):
        """平票时: home_weight >= away_weight → home"""
        model_results = {
            'strength': {'direction': 'home', 'confidence': 50},
            'handicap': {'direction': 'away', 'confidence': 50},
            'market': {'direction': 'neutral', 'confidence': 0},
            'squad': {'direction': 'neutral', 'confidence': 0},
            'ai_referee': {'direction': 'neutral', 'confidence': 0},
        }
        # strength(0.25*0.5=0.125) vs handicap(0.30*0.5=0.15) → away wins
        result = self.fn(model_results)
        self.assertEqual(result, 'away')

    def test_missing_model_weight_normalization(self):
        """模型缺失时: 不重新归一化，缺失模型不贡献票数"""
        model_results = {
            'strength': {'direction': 'home', 'confidence': 80},
            # handicap missing
            'market': {'direction': 'away', 'confidence': 80},
            'squad': {'direction': 'neutral', 'confidence': 0},
            'ai_referee': {'direction': 'neutral', 'confidence': 0},
        }
        # strength: 0.25*0.8=0.20 vs market: 0.20*0.8=0.16 → home
        result = self.fn(model_results)
        self.assertEqual(result, 'home')

    def test_all_neutral(self):
        """所有模型neutral → home(默认fallback, home_weight=away_weight=0)"""
        model_results = {
            'strength': {'direction': 'neutral', 'confidence': 20},
            'handicap': {'direction': 'neutral', 'confidence': 20},
            'market': {'direction': 'neutral', 'confidence': 20},
            'squad': {'direction': 'neutral', 'confidence': 20},
            'ai_referee': {'direction': 'neutral', 'confidence': 20},
        }
        result = self.fn(model_results)
        # 所有权重为0，fallback: home_weight >= away_weight → home
        self.assertEqual(result, 'home')

    def test_san_lorenzo_fixture(self):
        """San Lorenzo vs Gimnasia: strength=draw, handicap=home, market=home → consensus=home"""
        model_results = {
            'strength': {'direction': 'draw', 'confidence': 40},
            'handicap': {'direction': 'home', 'confidence': 62},
            'market': {'direction': 'home', 'confidence': 73},
            'squad': {'direction': 'neutral', 'confidence': 35},
            'ai_referee': {'direction': 'home', 'confidence': 55},
        }
        self.assertEqual(self.fn(model_results), 'home')

    def test_arsenal_fixture(self):
        """Arsenal vs Luton: strength=draw, handicap=home, market=home → consensus=home"""
        model_results = {
            'strength': {'direction': 'draw', 'confidence': 40},
            'handicap': {'direction': 'home', 'confidence': 80},
            'market': {'direction': 'home', 'confidence': 70},
            'squad': {'direction': 'neutral', 'confidence': 35},
            'ai_referee': {'direction': 'home', 'confidence': 60},
        }
        self.assertEqual(self.fn(model_results), 'home')


class TestObserveLegacyVsConsensus(TestShadowExperimentBase):
    """observe报表中的影子对照统计"""

    def test_observe_legacy_vs_consensus(self):
        """get_experiment_stats正确统计"""
        # 写入多条实验记录
        self.db_mod.save_experiment({
            'match_id': 'OBS1', 'model_version': 'v1',
            'legacy_recommend': 'neutral', 'consensus_recommend': 'home',
            'consensus_weights': {}, 'consensus_reason': '',
        })
        self.db_mod.save_experiment({
            'match_id': 'OBS2', 'model_version': 'v1',
            'legacy_recommend': 'home', 'consensus_recommend': 'home',
            'consensus_weights': {}, 'consensus_reason': '',
        })
        # 结算
        self.db_mod.settle_experiment('OBS1', 'no_bet', 'win', None, 1.0)
        self.db_mod.settle_experiment('OBS2', 'win', 'win', 1.0, 1.0)

        stats = self.db_mod.get_experiment_stats()
        self.assertEqual(stats['total'], 2)
        self.assertEqual(stats['settled'], 2)
        self.assertEqual(stats['agree'], 1)  # OBS2方向一致
        self.assertEqual(stats['disagree'], 1)  # OBS1方向不一致
        self.assertEqual(stats['legacy_pnl'], 1.0)  # 只有OBS2有PnL
        self.assertEqual(stats['consensus_pnl'], 2.0)  # OBS1+OBS2


if __name__ == "__main__":
    unittest.main()
