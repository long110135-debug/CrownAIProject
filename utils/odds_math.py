"""
皇冠AI赛事研判系统 - 盘口数学工具(唯一定义处)
所有升盘/降盘/水位变化判断逻辑只在这里。
odds_tracker、odds_profile、clv_analysis 都从这里导入，不自己重写。
"""
import re
from typing import Optional, Tuple


def handicap_to_number(handicap_str: str) -> float:
    """
    盘口文字转数值(唯一实现)
    '主让0.5' → 0.5
    '客让1' → -1.0
    '平手' → 0.0
    '-0.5' → -0.5
    """
    if not handicap_str:
        return 0.0
    s = str(handicap_str).strip()
    nums = re.findall(r'[\d.]+', s)
    if not nums:
        return 0.0
    val = float(nums[0])
    if "客让" in s or "受" in s or s.startswith('-'):
        val = -val
    return val


def number_to_handicap(val: float) -> str:
    """数值转盘口文字: 0.5→'主让0.5', -1.0→'客让1', 0→'平手'"""
    if val == 0:
        return "平手"
    elif val > 0:
        return f"主让{val}"
    else:
        return f"客让{abs(val)}"


def compute_change(open_hdp: str, curr_hdp: str,
                   open_hw: float, curr_hw: float,
                   open_aw: float, curr_aw: float) -> dict:
    """
    计算两次盘口快照之间的变化(唯一实现)
    
    返回: {
        "change_type": "升盘"/"降盘"/"水位异动"/"不变",
        "handicap_diff": float,
        "home_water_shift": float,
        "away_water_shift": float,
        "signal": "home_support"/"away_support"/"neutral",
        "significance": 0-95,
    }
    """
    old_val = handicap_to_number(open_hdp)
    new_val = handicap_to_number(curr_hdp)
    hdp_diff = new_val - old_val
    hw_shift = curr_hw - open_hw
    aw_shift = curr_aw - open_aw

    # 变化类型
    if abs(hdp_diff) > 0.01:
        change_type = "升盘" if hdp_diff > 0 else "降盘"
    elif abs(hw_shift) > 0.03 or abs(aw_shift) > 0.03:
        change_type = "水位异动"
    else:
        change_type = "不变"

    # 信号和强度
    signal = "neutral"
    significance = 0

    if change_type == "升盘":
        signal = "home_support"
        significance = min(abs(hdp_diff) * 40, 50)
        if hw_shift < -0.03:
            significance += 20
    elif change_type == "降盘":
        signal = "away_support"
        significance = min(abs(hdp_diff) * 40, 50)
        if aw_shift < -0.03:
            significance += 20
    elif change_type == "水位异动":
        if hw_shift < -0.03:
            signal = "home_support"
        elif aw_shift < -0.03:
            signal = "away_support"
        significance = max(abs(hw_shift), abs(aw_shift)) * 100

    return {
        "change_type": change_type,
        "handicap_diff": round(hdp_diff, 3),
        "home_water_shift": round(hw_shift, 3),
        "away_water_shift": round(aw_shift, 3),
        "signal": signal,
        "significance": round(min(significance, 95)),
    }


def calc_clv(recommended_hdp: str, closing_hdp: str,
             recommended_hw: float, closing_hw: float) -> dict:
    """
    计算CLV(唯一实现): 推荐时盘口 vs 收盘盘口
    
    正CLV = 推荐时拿到了比收盘更好的价格
    
    返回: {
        "clv_handicap": float (正=推荐时盘口更深),
        "clv_water": float (正=推荐时水位更优),
        "positive": bool,
    }
    """
    rec_val = handicap_to_number(recommended_hdp)
    close_val = handicap_to_number(closing_hdp)

    clv_hdp = round(rec_val - close_val, 3)
    clv_water = round(recommended_hw - closing_hw, 4) if recommended_hw and closing_hw else 0.0

    return {
        "clv_handicap": clv_hdp,
        "clv_water": clv_water,
        "positive": clv_hdp > 0 or (clv_hdp == 0 and clv_water > 0),
    }
