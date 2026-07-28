"""
皇冠AI赛事研判系统 - 皇冠指数评分
公式: 盘口变化35 + 水位变化25 + 实力匹配20 + 市场异常20 = 0-100
"""
from utils.logger import log
from config.settings import CROWN_INDEX_WEIGHTS


def calc_crown_index(model_results: dict, odds: dict) -> dict:
    """
    计算皇冠指数 (0-100)
    
    参数:
    - model_results: 各模型分析结果 {strength, handicap, squad, market, ai_referee}
    - odds: 盘口数据
    
    返回:
    {
        "crown_index": 88,
        "rating": "强信号",
        "breakdown": {
            "handicap_change": 32,  # 满分35
            "water_change": 22,     # 满分25
            "strength_match": 18,   # 满分20
            "market_anomaly": 16,   # 满分20
        }
    }
    """
    # === 1. 盘口变化分 (满分35) ===
    handicap_change_score = _score_handicap_change(model_results, odds)

    # === 2. 水位变化分 (满分25) ===
    water_change_score = _score_water_change(model_results, odds)

    # === 3. 实力匹配分 (满分20) ===
    strength_match_score = _score_strength_match(model_results)

    # === 4. 市场异常分 (满分20) ===
    market_anomaly_score = _score_market_anomaly(model_results)

    # 总分
    crown_index = (
        handicap_change_score +
        water_change_score +
        strength_match_score +
        market_anomaly_score
    )
    crown_index = max(0, min(100, round(crown_index, 1)))

    # 评级
    rating = _get_rating(crown_index)

    return {
        "crown_index": crown_index,
        "rating": rating,
        "breakdown": {
            "handicap_change": round(handicap_change_score, 1),
            "water_change": round(water_change_score, 1),
            "strength_match": round(strength_match_score, 1),
            "market_anomaly": round(market_anomaly_score, 1),
        },
    }


def _score_handicap_change(model_results: dict, odds: dict) -> float:
    """
    盘口变化评分 (0-35)
    升盘/降盘明确=高分，不变=中分，异常=低分
    """
    handicap_result = model_results.get("handicap", {})
    change_type = odds.get("change_type", "不变")

    if not handicap_result:
        return 10  # 无数据给基础分

    # 从盘口模型获取变化评分
    change_score = handicap_result.get("details", {}).get("change_score", 50)

    # 映射到0-35
    base = (change_score / 100) * 35

    # 盘口变化明确加分
    if change_type in ("升盘", "降盘"):
        base = max(base, 22)  # 至少22/35

    return min(base, 35)


def _score_water_change(model_results: dict, odds: dict) -> float:
    """
    水位变化评分 (0-25)
    水位方向明确=高分，均衡=中分
    """
    handicap_result = model_results.get("handicap", {})
    if not handicap_result:
        return 8

    water_score = handicap_result.get("details", {}).get("water_score", 50)
    return (water_score / 100) * 25


def _score_strength_match(model_results: dict) -> float:
    """
    实力匹配评分 (0-20)
    实力方向与盘口方向一致=高分，背离=低分
    """
    strength = model_results.get("strength", {})
    handicap = model_results.get("handicap", {})

    if not strength or not handicap:
        return 8

    s_dir = strength.get("direction", "neutral")
    h_dir = handicap.get("direction", "neutral")

    if s_dir == "neutral" or h_dir == "neutral":
        return 10  # 一方中性

    if s_dir == h_dir:
        # 一致 → 高分
        s_conf = strength.get("confidence", 50)
        h_conf = handicap.get("confidence", 50)
        avg_conf = (s_conf + h_conf) / 2
        return 12 + (avg_conf / 100) * 8  # 12-20
    else:
        # 背离 → 低分（但有可能是市场错误信号）
        return 5


def _score_market_anomaly(model_results: dict) -> float:
    """
    市场异常评分 (0-20)
    无异常=高分(市场正常)，有诱热=中分(需警惕)，严重异常=低分
    注意：这里"异常"是减分项，无异常=市场健康=高分
    """
    market = model_results.get("market", {})
    ai_referee = model_results.get("ai_referee", {})

    if not market:
        return 10

    # 诱热检测
    trap_info = market.get("details", {}).get("trap", {})
    trap_risk = trap_info.get("trap_risk", 0)

    # AI异常检测
    anomalies = []
    if ai_referee:
        anomalies = ai_referee.get("details", {}).get("anomalies", [])

    # 基础分20，每个风险点扣分
    score = 20
    if trap_info.get("is_trap"):
        score -= 8
    score -= min(trap_risk / 20, 5)
    score -= len(anomalies) * 2

    return max(3, min(20, score))


def _get_rating(crown_index: float) -> str:
    """皇冠指数评级"""
    if crown_index >= 85:
        return "极强信号"
    elif crown_index >= 75:
        return "强信号"
    elif crown_index >= 65:
        return "中强信号"
    elif crown_index >= 55:
        return "中等信号"
    elif crown_index >= 45:
        return "弱信号"
    elif crown_index >= 30:
        return "观察"
    else:
        return "无信号"
