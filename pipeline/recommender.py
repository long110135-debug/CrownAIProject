"""
皇冠AI赛事研判系统 - 推荐引擎 v1.2
三级推荐: A级(★★★★★) / B级(★★★★) / C级(观察)

v1.2推荐过滤器:
- 皇冠指数 >= 75
- 实力评分 >= 70
- 盘口评分 >= 70
- 数据完整度 >= 80%
- 盘口稳定性 >= 70 (新增)
目标: 29场→6场，质量优先
"""
from typing import List
from utils.logger import log
from config.settings import RECOMMEND_THRESHOLDS, DAILY_CONFIG, MODEL_VERSION


def generate_recommendation(analysis: dict) -> dict:
    """
    为单场比赛生成推荐
    
    v1.2严格过滤: A/B级必须同时满足:
    - 皇冠指数 ≥ 75
    - 实力评分 ≥ 70
    - 盘口评分 ≥ 70
    - 数据完整度 ≥ 80%
    - 盘口稳定性 ≥ 70 (盘口画像)
    否则降为C级(观察)
    """
    crown_index = analysis.get("crown_index", 0)
    model_results = analysis.get("model_results", {})
    data_completeness = analysis.get("data_completeness", 0)

    # 各模型分数
    strength_score = model_results.get("strength", {}).get("score", 0) if isinstance(model_results.get("strength"), dict) else 0
    handicap_score = model_results.get("handicap", {}).get("score", 0) if isinstance(model_results.get("handicap"), dict) else 0

    # 盘口稳定性(从画像获取)
    match_id = analysis.get("match_id", "")
    stability_score = _get_stability(match_id)

    # v1.2严格过滤: 五项全达标才能进A/B
    passes_filter = (
        crown_index >= 75 and
        strength_score >= 70 and
        handicap_score >= 70 and
        data_completeness >= 80 and
        stability_score >= 70
    )

    # 确定推荐等级
    if passes_filter and crown_index >= RECOMMEND_THRESHOLDS["A"]:
        level = "A"
        stars = 5
    elif passes_filter and crown_index >= RECOMMEND_THRESHOLDS["B"]:
        level = "B"
        stars = 4
    else:
        level = "C"
        stars = 0

    # 确定方向
    direction = _consensus_direction(model_results)

    # 确定盘口建议
    odds = analysis.get("odds", {})
    handicap_suggestion = _handicap_suggestion(odds, direction)

    # 风险评估
    risk_level = _assess_risk(analysis, model_results)

    # 理由
    reasoning = _build_reasoning(analysis, model_results, level)

    # 可信度 (各模型加权)
    confidence = _weighted_confidence(model_results)

    # 完整度描述
    completeness_label = _completeness_label(data_completeness)

    return {
        "match_id": analysis.get("match_id", ""),
        "league": analysis.get("league", ""),
        "home_team": analysis.get("home_team", ""),
        "away_team": analysis.get("away_team", ""),
        "match_time": analysis.get("match_time", ""),
        "level": level,
        "stars": stars,
        "direction": direction,
        "direction_label": _direction_label(direction),
        "handicap": odds.get("current_handicap", odds.get("asian_handicap", "")),
        "handicap_suggestion": handicap_suggestion,
        "crown_index": crown_index,
        "crown_rating": analysis.get("crown_rating", ""),
        "confidence": round(confidence, 1),
        "risk_level": risk_level,
        "reasoning": reasoning,
        "data_completeness": data_completeness,
        "completeness_label": completeness_label,
        "model_version": MODEL_VERSION,
    }


def rank_recommendations(recommendations: List[dict]) -> dict:
    """
    对今日所有推荐进行排序和分组
    
    返回:
    {
        "a_level": [...],      # A级推荐
        "b_level": [...],      # B级推荐
        "c_level": [...],      # C级观察
        "risk_alerts": [...],  # 风险提示
        "top5": [...],         # 今日TOP5
    }
    """
    a_level = []
    b_level = []
    c_level = []
    risk_alerts = []

    for rec in recommendations:
        level = rec.get("level", "C")
        if level == "A":
            a_level.append(rec)
        elif level == "B":
            b_level.append(rec)
        else:
            c_level.append(rec)

        # 风险提示
        if rec.get("risk_level") in ("高", "极高"):
            risk_alerts.append(rec)

    # 按皇冠指数排序
    a_level.sort(key=lambda x: x.get("crown_index", 0), reverse=True)
    b_level.sort(key=lambda x: x.get("crown_index", 0), reverse=True)
    risk_alerts.sort(key=lambda x: x.get("crown_index", 0))

    # TOP5
    all_ranked = sorted(recommendations, key=lambda x: x.get("crown_index", 0), reverse=True)
    top5 = all_ranked[:DAILY_CONFIG.get("max_recommend", 5)]

    # 限制数量
    risk_alerts = risk_alerts[:DAILY_CONFIG.get("max_risk_alert", 3)]

    return {
        "a_level": a_level,
        "b_level": b_level,
        "c_level": c_level,
        "risk_alerts": risk_alerts,
        "top5": top5,
        "total_matches": len(recommendations),
        "a_count": len(a_level),
        "b_count": len(b_level),
        "c_count": len(c_level),
    }


def _consensus_direction(model_results: dict) -> str:
    """多模型方向共识"""
    from config.settings import MODEL_WEIGHTS

    home_weight = 0
    away_weight = 0
    draw_weight = 0

    for name, result in model_results.items():
        if not isinstance(result, dict):
            continue
        direction = result.get("direction", "neutral")
        confidence = result.get("confidence", 0) / 100
        weight = MODEL_WEIGHTS.get(name, 0.1)

        if direction == "home":
            home_weight += weight * confidence
        elif direction == "away":
            away_weight += weight * confidence
        elif direction == "draw":
            draw_weight += weight * confidence

    if home_weight > away_weight and home_weight > draw_weight:
        return "home"
    elif away_weight > home_weight and away_weight > draw_weight:
        return "away"
    elif draw_weight > 0.15:
        return "draw"
    else:
        return "home" if home_weight >= away_weight else "away"


def _handicap_suggestion(odds: dict, direction: str) -> str:
    """盘口建议"""
    handicap = odds.get("current_handicap", odds.get("asian_handicap", ""))
    change = odds.get("change_type", "")

    if not handicap:
        return "盘口待定"

    if direction == "home":
        if change == "升盘":
            return f"主队方向明确，盘口{handicap}可关注"
        else:
            return f"主队方向，盘口{handicap}观察"
    elif direction == "away":
        if change == "降盘":
            return f"客队方向明确，盘口{handicap}可关注"
        else:
            return f"客队方向，盘口{handicap}观察"
    else:
        return f"方向不明，盘口{handicap}暂避"


def _assess_risk(analysis: dict, model_results: dict) -> str:
    """风险评估"""
    risk_score = 0

    # 模型方向冲突
    directions = [r.get("direction") for r in model_results.values()
                  if isinstance(r, dict) and r.get("direction") != "neutral"]
    if len(set(directions)) > 1:
        risk_score += 2

    # 诱热风险
    market = model_results.get("market", {})
    if isinstance(market, dict):
        trap = market.get("details", {}).get("trap", {})
        if trap.get("is_trap"):
            risk_score += 3

    # AI异常
    ai = model_results.get("ai_referee", {})
    if isinstance(ai, dict):
        anomalies = ai.get("details", {}).get("anomalies", [])
        risk_score += len(anomalies)

    # 皇冠指数低
    if analysis.get("crown_index", 0) < 50:
        risk_score += 2

    if risk_score >= 5:
        return "极高"
    elif risk_score >= 3:
        return "高"
    elif risk_score >= 2:
        return "中"
    else:
        return "低"


def _build_reasoning(analysis: dict, model_results: dict, level: str) -> str:
    """构建推荐理由"""
    parts = []

    # 盘口理由
    handicap = model_results.get("handicap", {})
    if isinstance(handicap, dict) and handicap.get("reasoning"):
        parts.append(handicap["reasoning"])

    # 实力理由
    strength = model_results.get("strength", {})
    if isinstance(strength, dict) and strength.get("reasoning"):
        parts.append(strength["reasoning"])

    # 市场理由
    market = model_results.get("market", {})
    if isinstance(market, dict) and market.get("reasoning"):
        parts.append(market["reasoning"])

    if level == "A":
        prefix = "【强推】"
    elif level == "B":
        prefix = "【关注】"
    else:
        prefix = "【观察】"

    reasoning = prefix + "；".join(parts[:3])
    return reasoning[:200]  # 限制长度


def _weighted_confidence(model_results: dict) -> float:
    """加权可信度"""
    from config.settings import MODEL_WEIGHTS
    total_weight = 0
    total_conf = 0

    for name, result in model_results.items():
        if isinstance(result, dict):
            w = MODEL_WEIGHTS.get(name, 0.1)
            c = result.get("confidence", 0)
            total_weight += w
            total_conf += w * c

    if total_weight == 0:
        return 0
    return total_conf / total_weight


def _completeness_label(pct: float) -> str:
    """数据完整度描述"""
    if pct >= 90:
        return f"{pct:.0f}% 完全分析"
    elif pct >= 70:
        return f"{pct:.0f}% 部分分析"
    elif pct >= 40:
        return f"{pct:.0f}% 跨联赛，仅盘口模型参与"
    else:
        return f"{pct:.0f}% 数据极少"


def _get_stability(match_id: str) -> float:
    """获取盘口稳定性评分(从画像表)"""
    try:
        from utils.database import get_odds_profile
        profile = get_odds_profile(match_id)
        if profile and profile.get("stability_score") is not None:
            return profile["stability_score"]
    except Exception:
        pass
    # 无画像数据时默认50(数据积累阶段不因此排除)
    return 50


def _direction_label(direction: str) -> str:
    """方向中文标签"""
    labels = {
        "home": "主胜",
        "away": "客胜",
        "draw": "平局",
        "home_handicap": "让胜",
        "away_handicap": "让负",
    }
    return labels.get(direction, direction)
