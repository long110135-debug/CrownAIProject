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


def decimal_to_hk_water(odds) -> float:
    """
    欧洲盘十进制赔率 → 亚洲盘水位(HK，仅利润，唯一实现)。

    十进制赔率 = 本金 + 利润；亚洲盘水位 = 仅利润。故 HK水 = 十进制 - 1。
    例: 1.95 → 0.95 (平衡线)，1.32 → 0.32 (重度受让方)。

    幂等保护: 已落在亚洲盘水位区间(<1.3)的值原样返回，避免重复转换。
    判定依据: 亚洲盘水位实测≤1.23，欧洲盘十进制实测≥1.3，1.3为安全分界。
    """
    try:
        val = float(odds)
    except (TypeError, ValueError):
        return odds
    if val >= 1.3:
        return round(val - 1, 3)
    return val


def line_favorite(handicap_str) -> str:
    """
    盘口线隐含的热门方(让球方)，唯一实现。

    亚盘让球方=市场认定的强队=更可能获胜方:
      主让(>0) → "home"
      客让(<0) → "away"
      平手/无盘口(=0) → "neutral"

    修复要点: 受让方(下盘)天然低水，但低水≠被看好；让球方向才指示热门。
    """
    val = handicap_to_number(str(handicap_str) if handicap_str else "")
    if val > 0:
        return "home"
    if val < 0:
        return "away"
    return "neutral"


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


# === 唯一亚盘结算函数 ===
# legacy / consensus / 普通推荐 / 报表PnL 全部调用此处，不各自重写。

_HIT_TO_PNL = {
    "win": 1.0,
    "half_win": 0.5,
    "push": 0.0,
    "half_loss": -0.5,
    "loss": -1.0,
    "no_bet": None,
    "invalid": None,
}


def hit_to_pnl(hit: str):
    """结算结果→单位收益(唯一实现)。win=+1, half_win=+0.5, push=0, half_loss=-0.5, loss=-1, no_bet/invalid=None"""
    return _HIT_TO_PNL.get(hit)


def settle_asian_handicap(direction: str, handicap_str: str,
                          home_score: int, away_score: int) -> str:
    """
    唯一亚盘结算函数。

    参数:
      direction: 推荐方向 'home'/'away'/'draw'/'neutral'/None
      handicap_str: 盘口文字('主让0.5'/'客让0.25'/'平手'等)
      home_score, away_score: 全场比分(亚盘按90分钟计)

    返回: 'win'/'half_win'/'push'/'half_loss'/'loss'/'invalid'/'no_bet'

    覆盖盘口: 0, ±0.25, ±0.5, ±0.75, ±1, ±1.25, ±1.5, ±2 等。
    逻辑: 主队让球后净胜 margin=(home-away)-hdp (hdp主让为正/客让为负)，
          先从主队视角定盘口结果，再按推荐方向映射(away则翻转)。
    """
    if not direction or direction == "neutral":
        return "no_bet"
    if direction == "draw":
        return "invalid"  # 亚盘无平局投注方向

    hdp = handicap_to_number(str(handicap_str) if handicap_str else "")
    # 主队让球后净胜(正=主队覆盖盘口)
    margin = (home_score - away_score) - hdp

    # 四分之一盘(x.25/x.75)有半赢半输
    is_quarter = abs(round(abs(hdp) * 4)) % 2 == 1

    if is_quarter:
        if abs(margin - 0.25) < 0.01:
            home_result = "half_win"
        elif abs(margin + 0.25) < 0.01:
            home_result = "half_loss"
        elif margin > 0.01:
            home_result = "win"
        elif margin < -0.01:
            home_result = "loss"
        else:
            home_result = "push"
    else:
        if abs(margin) < 0.01:
            home_result = "push"
        elif margin > 0:
            home_result = "win"
        else:
            home_result = "loss"

    if direction == "home":
        return home_result
    # away: 翻转主队视角结果
    flip = {"win": "loss", "loss": "win", "half_win": "half_loss",
            "half_loss": "half_win", "push": "push"}
    return flip[home_result]
