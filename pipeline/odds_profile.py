"""
皇冠AI赛事研判系统 - 盘口变化画像 v1.2
从odds_timeline提取盘口变化模式，分类为:
- 持续升盘: 盘口单调递增(主让0.25→0.5→0.75)
- 持续降盘: 盘口单调递减
- 升后回落: 先升后降(诱热信号)
- 降后回升: 先降后升(诱冷信号)
- 震荡: 反复波动无明确方向
- 稳定: 基本不变

输出: pattern_type + stability_score(0-100) + 详细路径
用途: 模型直接使用"盘口类型"而非数值
"""
from typing import List, Optional
from utils.logger import log
from utils.database import get_timeline, save_odds_profile, get_odds_profile


def generate_profile(match_id: str) -> Optional[dict]:
    """
    为某场比赛生成盘口变化画像
    
    返回: {
        pattern_type: "持续升盘"/"持续降盘"/"升后回落"/"降后回升"/"震荡"/"稳定",
        total_steps: 变化次数,
        net_change: 净变化(收盘-开盘),
        max_change: 最大单步变化,
        stability_score: 稳定性评分(0-100, 越高越稳定),
        opening_value: 开盘盘口值,
        closing_value: 收盘盘口值,
        water_trend: 水位趋势,
        detail: [{phase, handicap, home_water, time}...]
    }
    """
    timeline = get_timeline(match_id)
    if not timeline:
        return None

    # 提取盘口值序列
    values = []
    waters = []
    detail = []
    for t in timeline:
        hdp_val = t.get('handicap_value') or 0
        hw = t.get('home_water') or 0
        values.append(hdp_val)
        waters.append(hw)
        detail.append({
            "phase": t.get('phase', ''),
            "handicap": t.get('handicap', ''),
            "handicap_value": hdp_val,
            "home_water": hw,
            "time": t.get('record_time', ''),
        })

    if len(values) < 2:
        # 只有一次快照，无法判断趋势
        profile = {
            "pattern_type": "数据不足",
            "total_steps": 0,
            "net_change": 0,
            "max_change": 0,
            "stability_score": 50,
            "opening_value": values[0] if values else 0,
            "closing_value": values[0] if values else 0,
            "water_trend": "未知",
            "detail": detail,
        }
        save_odds_profile(match_id, profile)
        return profile

    # 计算变化步骤
    steps = [values[i+1] - values[i] for i in range(len(values)-1)]
    net_change = values[-1] - values[0]
    max_change = max(abs(s) for s in steps) if steps else 0

    # 水位趋势
    water_steps = [waters[i+1] - waters[i] for i in range(len(waters)-1)]
    water_net = waters[-1] - waters[0] if len(waters) >= 2 else 0
    if water_net < -0.03:
        water_trend = "主水下降(资金流入主队)"
    elif water_net > 0.03:
        water_trend = "主水上升(资金流入客队)"
    else:
        water_trend = "水位平稳"

    # 分类盘口模式
    pattern = _classify_pattern(steps, net_change)

    # 稳定性评分: 变化越小越稳定
    # 0步变化=100, 每步0.25变化扣15分
    stability = max(0, 100 - len(steps) * 10 - abs(net_change) * 40)
    stability = round(min(stability, 100), 1)

    profile = {
        "pattern_type": pattern,
        "total_steps": len(steps),
        "net_change": round(net_change, 3),
        "max_change": round(max_change, 3),
        "stability_score": stability,
        "opening_value": values[0],
        "closing_value": values[-1],
        "water_trend": water_trend,
        "detail": detail,
    }

    save_odds_profile(match_id, profile)
    return profile


def _classify_pattern(steps: List[float], net_change: float) -> str:
    """
    根据变化步骤序列分类盘口模式
    
    steps: [0.25, 0.25, -0.5] 表示先升两次再降一次
    """
    if not steps:
        return "稳定"

    # 全部为0或极小变化
    if all(abs(s) < 0.01 for s in steps):
        return "稳定"

    # 判断方向序列
    ups = sum(1 for s in steps if s > 0.01)
    downs = sum(1 for s in steps if s < -0.01)
    total_directional = ups + downs

    if total_directional == 0:
        return "稳定"

    # 持续升盘: 全部(或绑大多数)是升
    if ups == total_directional and net_change > 0.01:
        return "持续升盘"

    # 持续降盘: 全部是降
    if downs == total_directional and net_change < -0.01:
        return "持续降盘"

    # 升后回落 / 降后回升 / 震荡
    if ups > 0 and downs > 0:
        # 先检查震荡(多次方向变化)
        direction_changes = sum(1 for i in range(len(steps)-1)
                              if steps[i] * steps[i+1] < 0 and abs(steps[i]) > 0.01)
        if direction_changes >= 2:
            return "震荡"

        # 找转折点(峰值) → 升后回落
        peak_idx = _find_peak(steps)
        if peak_idx is not None and peak_idx < len(steps) - 1:
            before = steps[:peak_idx+1]
            after = steps[peak_idx+1:]
            before_sum = sum(before)
            after_sum = sum(after)

            if before_sum > 0.01 and after_sum < -0.01:
                if net_change > 0.01:
                    return "持续升盘"
                else:
                    return "升后回落"

        # 找转折点(谷底) → 降后回升
        trough_idx = _find_trough(steps)
        if trough_idx is not None and trough_idx < len(steps) - 1:
            before = steps[:trough_idx+1]
            after = steps[trough_idx+1:]
            before_sum = sum(before)
            after_sum = sum(after)

            if before_sum < -0.01 and after_sum > 0.01:
                if net_change < -0.01:
                    return "持续降盘"
                else:
                    return "降后回升"

    # 震荡: 多次方向变化
    direction_changes = sum(1 for i in range(len(steps)-1)
                          if steps[i] * steps[i+1] < 0 and abs(steps[i]) > 0.01)
    if direction_changes >= 2:
        return "震荡"

    # 默认按净变化判断
    if net_change > 0.1:
        return "持续升盘"
    elif net_change < -0.1:
        return "持续降盘"
    else:
        return "震荡"


def _find_peak(steps: List[float]) -> Optional[int]:
    """找到累积变化的峰值位置"""
    cumulative = 0
    peak_val = 0
    peak_idx = None
    for i, s in enumerate(steps):
        cumulative += s
        if cumulative > peak_val:
            peak_val = cumulative
            peak_idx = i
    return peak_idx


def _find_trough(steps: List[float]) -> Optional[int]:
    """找到累积变化的谷底位置"""
    cumulative = 0
    trough_val = 0
    trough_idx = None
    for i, s in enumerate(steps):
        cumulative += s
        if cumulative < trough_val:
            trough_val = cumulative
            trough_idx = i
    return trough_idx


def generate_all_profiles() -> int:
    """为所有有时间线数据的比赛生成画像"""
    from utils.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT match_id FROM odds_timeline")
    match_ids = [r['match_id'] for r in cursor.fetchall()]
    conn.close()

    count = 0
    for mid in match_ids:
        # 跳过已有画像的
        existing = get_odds_profile(mid)
        if existing:
            continue
        profile = generate_profile(mid)
        if profile:
            count += 1

    if count:
        log.info(f"[画像] 生成{count}场盘口变化画像")
    return count


def get_pattern_stats() -> dict:
    """获取盘口模式分布统计"""
    from utils.database import get_connection
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pattern_type, COUNT(*) as cnt, AVG(stability_score) as avg_stability
        FROM odds_profile GROUP BY pattern_type ORDER BY cnt DESC
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {
        "total": sum(r["cnt"] for r in rows),
        "distribution": {
            r["pattern_type"]: {
                "count": r["cnt"],
                "avg_stability": round(r["avg_stability"], 1) if r["avg_stability"] else 0,
            } for r in rows
        },
    }
