"""
皇冠AI赛事研判系统 - 权重训练框架
基于历史预测数据，自动优化皇冠指数各维度权重
用法: python3 train_weights.py [--min-samples 100]
"""
import sys
import os
import json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.database import get_connection
from utils.logger import log
from config.settings import CROWN_INDEX_WEIGHTS


def get_settled_data(min_samples: int = 50) -> list:
    """获取已结算的预测数据"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT crown_index, strength_score, handicap_score, market_score,
               squad_score, ai_score, data_completeness, hit, level
        FROM prediction_history
        WHERE hit >= 0 AND data_completeness >= 60
        ORDER BY predicted_at DESC
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if len(rows) < min_samples:
        log.info(f"[训练] 样本不足: {len(rows)}/{min_samples}，暂不训练")
        return []
    return rows


def evaluate_weights(weights: dict, data: list) -> float:
    """
    评估一组权重的表现
    返回: 加权命中率 (A/B级推荐的命中率)
    """
    hits = 0
    total = 0

    for row in data:
        # 用新权重重新计算皇冠指数
        score = (
            (row['handicap_score'] or 50) * weights['handicap_change'] / 100 +
            (row['strength_score'] or 50) * weights['strength_match'] / 100 +
            (row['market_score'] or 50) * weights['market_anomaly'] / 100 +
            (row['squad_score'] or 50) * weights.get('squad', 10) / 100
        )

        # 只统计达到推荐阈值的
        if score >= 60 and row['data_completeness'] >= 80:
            total += 1
            if row['hit'] == 1:
                hits += 1

    if total == 0:
        return 0
    return hits / total


def grid_search_weights(data: list) -> dict:
    """
    网格搜索最优权重
    搜索空间: 盘口25-45, 实力15-30, 市场15-30, 阵容5-15
    """
    best_score = 0
    best_weights = CROWN_INDEX_WEIGHTS.copy()

    # 简化网格 (步长5)
    for hdp in range(25, 50, 5):
        for strn in range(15, 35, 5):
            for mkt in range(15, 35, 5):
                squad = 100 - hdp - strn - mkt
                if squad < 5 or squad > 20:
                    continue

                weights = {
                    'handicap_change': hdp,
                    'strength_match': strn,
                    'market_anomaly': mkt,
                    'squad': squad,
                }
                score = evaluate_weights(weights, data)
                if score > best_score:
                    best_score = score
                    best_weights = weights

    return best_weights, best_score


def train(min_samples: int = 50):
    """执行训练"""
    print(f"\n{'═'*50}")
    print(f"  皇冠AI 权重训练")
    print(f"{'═'*50}\n")

    data = get_settled_data(min_samples)
    if not data:
        print(f"  样本不足({min_samples}场)，需要更多已结算数据。")
        print(f"  当前权重保持不变。")
        return

    print(f"  样本数: {len(data)}场")
    print(f"  当前权重: {CROWN_INDEX_WEIGHTS}")

    # 当前权重表现
    current_score = evaluate_weights(CROWN_INDEX_WEIGHTS, data)
    print(f"  当前命中率: {current_score*100:.1f}%")

    # 网格搜索
    print(f"\n  搜索最优权重...")
    best_weights, best_score = grid_search_weights(data)

    print(f"\n  最优权重: {best_weights}")
    print(f"  最优命中率: {best_score*100:.1f}%")

    if best_score > current_score + 0.02:  # 至少提升2个百分点
        print(f"\n  ✓ 提升 {(best_score-current_score)*100:.1f}个百分点")
        print(f"  建议更新权重:")
        print(f"    盘口: {CROWN_INDEX_WEIGHTS['handicap_change']} → {best_weights['handicap_change']}")
        print(f"    实力: {CROWN_INDEX_WEIGHTS['strength_match']} → {best_weights['strength_match']}")
        print(f"    市场: {CROWN_INDEX_WEIGHTS['market_anomaly']} → {best_weights['market_anomaly']}")

        # 保存到文件(不自动修改settings.py)
        output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'optimized_weights.json')
        with open(output_path, 'w') as f:
            json.dump({
                'weights': best_weights,
                'score': best_score,
                'samples': len(data),
                'current_weights': CROWN_INDEX_WEIGHTS,
                'current_score': current_score,
            }, f, indent=2)
        print(f"\n  已保存到: {output_path}")
        print(f"  确认后可手动更新 config/settings.py 中的 CROWN_INDEX_WEIGHTS")
    else:
        print(f"\n  当前权重已接近最优，无需调整。")

    print(f"\n{'═'*50}")


if __name__ == "__main__":
    min_s = 50
    if '--min-samples' in sys.argv:
        idx = sys.argv.index('--min-samples')
        if idx + 1 < len(sys.argv):
            min_s = int(sys.argv[idx + 1])
    train(min_s)
