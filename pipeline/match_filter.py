"""
皇冠AI赛事研判系统 - 三层过滤机制 v1.2

不是"有比赛就分析"，而是"只分析最值得分析的比赛"。

Layer 1 - 赛事过滤: 白名单联赛 + 排除垃圾赛事
Layer 2 - 数据过滤: 盘口完整 + 时间线>=2条 + 球队数据可用
Layer 3 - 推荐过滤: 皇冠指数 + 模型一致性 + 数据完整度 全达标

只有通过三层过滤的比赛才会输出推荐。
"""
from typing import List, Optional
from utils.logger import log
from config.leagues import (
    is_allowed_league, should_filter, get_league_tier,
    get_all_leagues, TIER1_LEAGUES, TIER2_LEAGUES
)


# === Layer 2 阈值: 数据完整性 ===
DATA_REQUIREMENTS = {
    "min_timeline_records": 2,    # 至少2条盘口时间线(有变化可追踪)
    "require_handicap": True,      # 必须有让球盘口
    "require_water": True,         # 必须有水位
    "min_team_data": False,        # 球队数据(暂不强制,积累期)
}

# === Layer 3 阈值: 推荐门槛 ===
RECOMMEND_REQUIREMENTS = {
    "min_crown_index": 75,         # 皇冠指数 >= 75
    "min_data_completeness": 80,   # 数据完整度 >= 80%
    "min_model_agreement": 0.6,    # 模型一致性 >= 60%(至少3/5模型同方向)
    "min_handicap_score": 70,      # 盘口模型评分 >= 70
    "min_stability": 70,           # 盘口稳定性 >= 70
}


def filter_matches(matches: List[dict]) -> List[dict]:
    """
    Layer 1: 赛事过滤
    只保留白名单联赛，排除青年队/友谊赛/低级别
    """
    filtered = []
    removed = 0

    for match in matches:
        league = match.get("league", "")

        if not is_allowed_league(league):
            removed += 1
            continue

        if should_filter(match):
            removed += 1
            continue

        match["league_tier"] = get_league_tier(league)
        all_leagues = get_all_leagues()
        league_info = all_leagues.get(league, {})
        match["league_priority"] = league_info.get("priority", 5)
        filtered.append(match)

    filtered.sort(key=lambda x: (x.get("league_tier", 9), x.get("league_priority", 9)))

    if removed > 0:
        log.info(f"[L1赛事过滤] {len(matches)}场 → {len(filtered)}场 (过滤{removed}场)")

    return filtered


def filter_by_data_quality(match_id: str, match: dict) -> dict:
    """
    Layer 2: 数据过滤
    检查单场比赛的数据是否足够支撑分析
    
    返回: {
        "pass": bool,
        "score": 0-100 (数据质量分),
        "reasons": [不通过原因],
        "details": {各项检查结果}
    }
    """
    from utils.database import get_timeline, get_latest_odds, get_team_stats

    reasons = []
    checks = {}

    # 检查盘口时间线
    timeline = get_timeline(match_id)
    timeline_count = len(timeline)
    checks["timeline_records"] = timeline_count
    if timeline_count < DATA_REQUIREMENTS["min_timeline_records"]:
        reasons.append(f"盘口时间线仅{timeline_count}条(需>={DATA_REQUIREMENTS['min_timeline_records']})")

    # 检查盘口数据
    latest = get_latest_odds(match_id)
    has_handicap = bool(latest and latest.get("handicap"))
    has_water = bool(latest and latest.get("home_water") and latest["home_water"] > 0)
    checks["has_handicap"] = has_handicap
    checks["has_water"] = has_water

    if DATA_REQUIREMENTS["require_handicap"] and not has_handicap:
        reasons.append("无让球盘口")
    if DATA_REQUIREMENTS["require_water"] and not has_water:
        reasons.append("无水位数据")

    # 检查球队数据(暂不强制)
    home_stats = get_team_stats(match.get("home_team", ""))
    away_stats = get_team_stats(match.get("away_team", ""))
    has_team_data = bool(home_stats and away_stats)
    checks["has_team_data"] = has_team_data

    # 计算数据质量分
    score = 0
    score += min(timeline_count * 15, 45)  # 时间线最多45分
    score += 25 if has_handicap else 0       # 盘口25分
    score += 15 if has_water else 0          # 水位15分
    score += 15 if has_team_data else 0      # 球队数据15分
    score = min(score, 100)
    checks["quality_score"] = score

    passed = len(reasons) == 0
    return {
        "pass": passed,
        "score": score,
        "reasons": reasons,
        "details": checks,
    }


def filter_by_recommendation_quality(analysis: dict) -> dict:
    """
    Layer 3: 推荐过滤
    只有通过此层的比赛才会输出为A/B级推荐
    
    返回: {
        "pass": bool,
        "reasons": [不通过原因],
        "model_agreement": float,
        "scores": {各项分数}
    }
    """
    reasons = []
    model_results = analysis.get("model_results", {})
    crown_index = analysis.get("crown_index", 0)
    completeness = analysis.get("data_completeness", 0)

    # 皇冠指数
    if crown_index < RECOMMEND_REQUIREMENTS["min_crown_index"]:
        reasons.append(f"皇冠指数{crown_index}<{RECOMMEND_REQUIREMENTS['min_crown_index']}")

    # 数据完整度
    if completeness < RECOMMEND_REQUIREMENTS["min_data_completeness"]:
        reasons.append(f"完整度{completeness}%<{RECOMMEND_REQUIREMENTS['min_data_completeness']}%")

    # 模型一致性: 计算多少模型同意主方向
    agreement = _calc_model_agreement(model_results)
    if agreement < RECOMMEND_REQUIREMENTS["min_model_agreement"]:
        reasons.append(f"模型一致性{agreement:.0%}<{RECOMMEND_REQUIREMENTS['min_model_agreement']:.0%}")

    # 盘口模型评分
    handicap_score = model_results.get("handicap", {}).get("score", 0) if isinstance(model_results.get("handicap"), dict) else 0
    if handicap_score < RECOMMEND_REQUIREMENTS["min_handicap_score"]:
        reasons.append(f"盘口模型{handicap_score}<{RECOMMEND_REQUIREMENTS['min_handicap_score']}")

    # 盘口稳定性
    match_id = analysis.get("match_id", "")
    stability = _get_stability(match_id)
    if stability < RECOMMEND_REQUIREMENTS["min_stability"]:
        reasons.append(f"盘口稳定性{stability}<{RECOMMEND_REQUIREMENTS['min_stability']}")

    return {
        "pass": len(reasons) == 0,
        "reasons": reasons,
        "model_agreement": agreement,
        "scores": {
            "crown_index": crown_index,
            "completeness": completeness,
            "handicap_score": handicap_score,
            "stability": stability,
            "agreement": round(agreement, 2),
        },
    }


def apply_full_filter(matches: List[dict]) -> dict:
    """
    完整三层过滤流水线
    
    返回: {
        "layer1": [通过赛事过滤的比赛],
        "layer2": [通过数据过滤的比赛],
        "layer2_rejected": [(match, reason)...],
        "stats": {各层通过数}
    }
    """
    # Layer 1
    l1_passed = filter_matches(matches)

    # Layer 2
    l2_passed = []
    l2_rejected = []
    for match in l1_passed:
        match_id = match.get("match_id", "")
        result = filter_by_data_quality(match_id, match)
        if result["pass"]:
            match["_data_quality"] = result["score"]
            l2_passed.append(match)
        else:
            l2_rejected.append((match, result["reasons"]))

    log.info(f"[三层过滤] L1:{len(matches)}→{len(l1_passed)} | L2:{len(l1_passed)}→{len(l2_passed)} | 淘汰{len(l2_rejected)}场")

    return {
        "layer1": l1_passed,
        "layer2": l2_passed,
        "layer2_rejected": l2_rejected,
        "stats": {
            "input": len(matches),
            "after_l1": len(l1_passed),
            "after_l2": len(l2_passed),
            "rejected_l2": len(l2_rejected),
        },
    }


def _calc_model_agreement(model_results: dict) -> float:
    """
    计算模型一致性: 有多少比例的模型同意主方向
    返回: 0.0-1.0
    """
    directions = []
    for name, result in model_results.items():
        if isinstance(result, dict):
            d = result.get("direction", "neutral")
            if d != "neutral":
                directions.append(d)

    if not directions:
        return 0.0

    # 找最多票方向
    from collections import Counter
    counts = Counter(directions)
    top_count = counts.most_common(1)[0][1]

    # 一致性 = 最多票 / 总有效模型数
    total_models = len(model_results)
    return top_count / total_models if total_models > 0 else 0


def _get_stability(match_id: str) -> float:
    """
    获取盘口稳定性
    
    V1.3观察期策略:
    - 前30天: 默认80，不参与扣分(数据积累期)
    - 30天后: 使用真实盘口画像的stability_score
    判断标准: model_validation表是否有30天前的数据
    """
    # 检查是否已过观察期
    try:
        from utils.database import get_connection
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM model_validation 
            WHERE validated_at < datetime('now', 'localtime', '-30 days')
        """)
        old_count = cursor.fetchone()[0]
        conn.close()
        if old_count == 0:
            # 观察期内，不惩罚
            return 80
    except Exception:
        return 80

    # 观察期后，使用真实画像
    try:
        from utils.database import get_odds_profile
        profile = get_odds_profile(match_id)
        if profile and profile.get("stability_score") is not None:
            return profile["stability_score"]
    except Exception:
        pass
    return 75


def build_recommendation_reason(analysis: dict, l3_result: dict = None) -> str:
    """
    生成结构化推荐原因
    
    A/B级: ✓ 逐项列出通过原因
    C级: ✗ 逐项列出未通过原因
    """
    model_results = analysis.get("model_results", {})
    crown_index = analysis.get("crown_index", 0)
    completeness = analysis.get("data_completeness", 0)
    match_id = analysis.get("match_id", "")

    # 模型一致性
    agreement = _calc_model_agreement(model_results)
    agreement_count = int(agreement * 5)

    # 盘口画像
    odds_pattern = ""
    try:
        from utils.database import get_odds_profile
        profile = get_odds_profile(match_id)
        if profile:
            odds_pattern = profile.get("pattern_type", "")
    except Exception:
        pass

    # 盘口模型分
    handicap_score = model_results.get("handicap", {}).get("score", 0) if isinstance(model_results.get("handicap"), dict) else 0

    # 稳定性
    stability = _get_stability(match_id)

    # 构建原因列表
    checks = [
        ("皇冠指数", crown_index >= RECOMMEND_REQUIREMENTS["min_crown_index"],
         f"皇冠指数{crown_index:.0f}"),
        ("数据完整度", completeness >= RECOMMEND_REQUIREMENTS["min_data_completeness"],
         f"数据完整度{completeness:.0f}%"),
        ("模型一致性", agreement >= RECOMMEND_REQUIREMENTS["min_model_agreement"],
         f"五模型{agreement_count}/5一致"),
        ("盘口模型", handicap_score >= RECOMMEND_REQUIREMENTS["min_handicap_score"],
         f"盘口模型{handicap_score:.0f}分"),
        ("盘口稳定性", stability >= RECOMMEND_REQUIREMENTS["min_stability"],
         f"盘口稳定性{stability:.0f}" + (f"({odds_pattern})" if odds_pattern else "")),
    ]

    passed = all(c[1] for c in checks)
    lines = []
    for name, ok, desc in checks:
        icon = "✓" if ok else "✗"
        lines.append(f"{icon} {desc}")

    return "\n".join(lines)


def get_league_summary(matches: List[dict]) -> dict:
    """获取联赛分布摘要"""
    summary = {}
    for match in matches:
        league = match.get("league", "未知")
        if league not in summary:
            summary[league] = {"count": 0, "tier": match.get("league_tier", 0)}
        summary[league]["count"] += 1
    return summary
