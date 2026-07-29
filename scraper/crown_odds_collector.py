"""
皇冠AI赛事研判系统 - 皇冠盘口统一采集器

职责: 调用各数据源，输出标准盘口格式，写入数据库。
这是盘口数据写入DB的唯一入口。

数据源优先级:
1. crown_daemon提供的浏览器页面(皇冠实时盘口)
2. API-Football odds端点(Bet365等公司)

标准输出格式:
{
    "match_id": "CROWN_瑞超_卡尔马_马尔默_2026-07-28",
    "league": "瑞超",
    "home": "卡尔马",
    "away": "马尔默",
    "handicap": "主让0.5",
    "home_water": 0.92,
    "away_water": 0.95,
    "over_line": "2.5",
    "over_water": 1.90,
    "under_water": 1.90,
    "source": "crown_daemon" | "api-football(Bet365)"
}
"""
import re
from datetime import datetime
from typing import List, Optional
from utils.logger import log
from utils.database import save_timeline_record


# 皇冠联赛名 → 系统短名(唯一定义处)
CROWN_LEAGUE_MAP = {
    '瑞典超级联赛': '瑞超', '瑞典超级甲组联赛': '瑞甲',
    '芬兰超级联赛': '芬超',
    '挪威超级联赛': '挪超',
    '丹麦超级联赛': '丹超',
    '英格兰超级联赛': '英超', '英格兰冠军联赛': '英冠',
    '西班牙甲组联赛': '西甲', '西班牙乙组联赛': '西乙',
    '意大利甲组联赛': '意甲', '意大利乙组联赛': '意乙',
    '德国甲组联赛': '德甲', '德国乙组联赛': '德乙',
    '法国甲组联赛': '法甲', '法国乙组联赛': '法乙',
    '荷兰甲组联赛': '荷甲', '荷兰乙组联赛': '荷乙',
    '葡萄牙超级联赛': '葡超', '葡萄牙甲组联赛': '葡甲',
    '土耳其超级联赛': '土超',
    '苏格兰超级联赛': '苏超',
    '比利时甲组联赛': '比甲',
    '瑞士超级联赛': '瑞士超',
    '奥地利甲组联赛': '奥甲',
    '俄罗斯超级联赛': '俄超',
    '阿根廷职业联赛': '阿甲',
    '巴西甲组联赛': '巴甲',
    '美国职业足球大联盟': '美职联',
    '墨西哥超级联赛': '墨超',
    '日本职业联赛': '日职',
    '韩国职业联赛': '韩K',
    '澳大利亚超级联赛': '澳超',
}


def normalize_league(crown_name: str) -> str:
    """皇冠联赛名 → 系统短名"""
    return CROWN_LEAGUE_MAP.get(crown_name, crown_name)


def normalize_date(date_str: str) -> str:
    """统一日期格式(委托到utils.helpers唯一实现，含跨年边界规则)"""
    from utils.helpers import normalize_date as _normalize_date
    return _normalize_date(date_str)


def build_match_id(league: str, home: str, away: str, date: str) -> str:
    """生成标准match_id"""
    norm_league = normalize_league(league)
    norm_date = normalize_date(date)
    return f"CROWN_{norm_league}_{home}_{away}_{norm_date}"


def save_crown_odds(matches: List[dict], source: str = "crown_daemon") -> int:
    """
    将皇冠抓取的原始比赛数据标准化后写入时间线。
    这是皇冠数据写入DB的唯一入口。

    参数:
        matches: crown_scraper解析出的原始比赛列表
                 [{league, date, time, home, away, handicap, home_water, away_water, ...}]
        source: 数据来源标记

    返回: 写入条数
    """
    count = 0
    for m in matches:
        home = m.get('home', '')
        away = m.get('away', '')
        if not home or not away:
            continue

        match_id = build_match_id(m.get('league', ''), home, away, m.get('date', ''))

        save_timeline_record(match_id, {
            "handicap": m.get("handicap", ""),
            "home_water": m.get("home_water", ""),
            "away_water": m.get("away_water", ""),
            "over_line": m.get("over_line", ""),
            "over_water": m.get("over_water", ""),
            "under_water": m.get("under_water", ""),
            "home_win": m.get("home_win", ""),
            "draw": m.get("draw", ""),
            "away_win": m.get("away_win", ""),
        }, phase="early", source=source)
        count += 1

    if count:
        log.info(f"[采集器] 写入{count}条盘口 (source={source})")
    return count


def save_api_odds(match_id: str, odds: dict, source: str = "api-football") -> bool:
    """
    将API-Football盘口数据写入时间线。

    参数:
        match_id: 标准match_id
        odds: {handicap, home_water, away_water, over_line, over_water, under_water,
               bookmaker(可选), fixture_id(可选)}
        source: 来源标记(如 "api-football(Bet365)")

    返回: 是否写入成功
    """
    if not odds or not odds.get("handicap"):
        return False

    # API-Football返回欧洲盘十进制赔率，统一转换为亚洲盘水位(HK)后入库，
    # 与crown_daemon源格式一致(模型阈值按亚洲盘水位校准)。
    from utils.odds_math import decimal_to_hk_water
    import re

    # 从source提取bookmaker: "api-football(Bet365)" → "Bet365"
    bookmaker = odds.get("bookmaker")
    if not bookmaker:
        m = re.match(r"api-football\((.+)\)", source)
        bookmaker = m.group(1) if m else "unknown"

    raw_hw = odds.get("home_water", 0.95)
    raw_aw = odds.get("away_water", 0.95)

    save_timeline_record(match_id, {
        "handicap": odds["handicap"],
        "handicap_raw": odds["handicap"],
        "home_water": decimal_to_hk_water(raw_hw),
        "away_water": decimal_to_hk_water(raw_aw),
        "home_water_normalized": decimal_to_hk_water(raw_hw),
        "away_water_normalized": decimal_to_hk_water(raw_aw),
        "home_price_raw": raw_hw,
        "away_price_raw": raw_aw,
        "odds_format": "decimal",
        "bookmaker": bookmaker,
        "market_type": "asian_handicap",
        "fixture_id": odds.get("fixture_id", ""),
        "over_line": odds.get("over_line", ""),
        "over_water": decimal_to_hk_water(odds.get("over_water", 0)),
        "under_water": decimal_to_hk_water(odds.get("under_water", 0)),
    }, phase="early", source=source)
    return True
