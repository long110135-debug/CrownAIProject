"""
皇冠AI - 标准化盘口特征接口

为下一轮 handicap 模型重构提供干净、标准化的输入特征。
本轮只提取特征，不计算最终方向权重。

特征基于 primary bookmaker 主序列(同公司同线)，经数据质量门控。
水位动态特征仅在 data_quality.usable 时有效，否则为 None。
"""
from utils.database import get_connection
from utils.odds_math import handicap_to_number, line_favorite
from pipeline.odds_series import get_primary_bookmaker, get_primary_opening, get_primary_current
from pipeline.odds_quality import assess_odds_quality, can_use_water_dynamics


def _favorite_water(record: dict, fav_side: str):
    """取让球方/受让方在给定记录中的水位(归一化HK)。"""
    if not record:
        return None
    # handicap_value>0 = 主让(home favorite); <0 = 客让(away favorite)
    home_w = record.get("home_water_normalized", record.get("home_water"))
    away_w = record.get("away_water_normalized", record.get("away_water"))
    if fav_side == "home":
        return home_w
    elif fav_side == "away":
        return away_w
    return None


def extract_handicap_features(match_id: str, analysis_time=None) -> dict:
    """提取一场比赛的标准化盘口特征。

    返回:
    {
        "match_id", "opening_handicap", "current_handicap", "line_change",
        "favorite_side", "underdog_side",
        "favorite_open_water", "favorite_current_water", "favorite_water_change",
        "underdog_open_water", "underdog_current_water", "underdog_water_change",
        "bookmaker", "snapshot_count", "data_quality", "prematch_minutes",
    }
    水位动态特征在 data_quality 不可用时为 None(不计算)。
    """
    quality = assess_odds_quality(match_id)
    primary = get_primary_bookmaker(match_id)
    opening = get_primary_opening(match_id)
    current = get_primary_current(match_id)

    open_hdp = opening.get("handicap") if opening else None
    curr_hdp = current.get("handicap") if current else None
    open_val = handicap_to_number(open_hdp) if open_hdp else None
    curr_val = handicap_to_number(curr_hdp) if curr_hdp else None

    # 盘口线变化(当前线 - 开盘线)
    line_change = None
    if open_val is not None and curr_val is not None:
        line_change = round(curr_val - open_val, 3)

    # 让球方/受让方(基于当前盘口线)
    fav = line_favorite(curr_hdp) if curr_hdp else "neutral"
    if fav == "home":
        favorite_side, underdog_side = "home", "away"
    elif fav == "away":
        favorite_side, underdog_side = "away", "home"
    else:
        favorite_side, underdog_side = "neutral", "neutral"

    # 水位特征(仅数据质量可用时计算)
    use_water = can_use_water_dynamics(quality)
    fav_open = fav_curr = fav_change = None
    und_open = und_curr = und_change = None
    if use_water:
        fav_open = _favorite_water(opening, favorite_side)
        fav_curr = _favorite_water(current, favorite_side)
        und_open = _favorite_water(opening, underdog_side)
        und_curr = _favorite_water(current, underdog_side)
        if fav_open is not None and fav_curr is not None:
            fav_change = round(fav_curr - fav_open, 3)
        if und_open is not None and und_curr is not None:
            und_change = round(und_curr - und_open, 3)

    # 距开赛分钟数(基于matches.match_time, 北京时间)
    prematch_minutes = _prematch_minutes(match_id, analysis_time)

    return {
        "match_id": match_id,
        "opening_handicap": open_hdp,
        "current_handicap": curr_hdp,
        "line_change": line_change,
        "favorite_side": favorite_side,
        "underdog_side": underdog_side,
        "favorite_open_water": fav_open,
        "favorite_current_water": fav_curr,
        "favorite_water_change": fav_change,
        "underdog_open_water": und_open,
        "underdog_current_water": und_curr,
        "underdog_water_change": und_change,
        "bookmaker": primary,
        "snapshot_count": quality.get("snapshot_count", 0),
        "data_quality": quality,
        "prematch_minutes": prematch_minutes,
    }


def _prematch_minutes(match_id: str, analysis_time=None):
    """距开赛分钟数(正=未开赛)。基于matches.match_time与当前/指定时间(均aware)。"""
    from utils.timeutil import now_utc
    from utils.helpers import parse_match_time
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT match_time FROM matches WHERE match_id = ?", (match_id,))
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    kickoff = parse_match_time(row["match_time"])
    if not kickoff:
        return None
    now = analysis_time or now_utc()
    if now.tzinfo is None:
        from utils.timeutil import UTC
        now = now.replace(tzinfo=UTC)
    delta = (kickoff - now).total_seconds() / 60
    return round(delta, 1)
