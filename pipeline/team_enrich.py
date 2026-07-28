"""
皇冠AI赛事研判系统 - 球队数据充实模块
从API-Football获取积分榜/近况数据，映射到皇冠中文队名
"""
import json
from typing import Dict, Optional
from utils.logger import log
from utils.database import get_connection

# 皇冠中文队名 → API-Football英文队名 映射
TEAM_NAME_MAP = {
    # 英超
    "阿森纳": "Arsenal", "曼城": "Manchester City", "利物浦": "Liverpool",
    "切尔西": "Chelsea", "曼联": "Manchester United", "托特纳姆热刺": "Tottenham",
    "纽卡斯尔": "Newcastle", "阿斯顿维拉": "Aston Villa", "布莱顿": "Brighton",
    "西汉姆联": "West Ham", "伯恩茅斯": "Bournemouth", "水晶宫": "Crystal Palace",
    "富勒姆": "Fulham", "狼队": "Wolves", "埃弗顿": "Everton",
    "布伦特福德": "Brentford", "诺丁汉森林": "Nottingham Forest",
    "伯恩利": "Burnley", "谢菲尔德联": "Sheffield Utd", "卢顿": "Luton",
    "利兹联": "Leeds", "考文垂": "Coventry", "赫尔城": "Hull City",
    "伊普斯维奇": "Ipswich", "桑德兰": "Sunderland", "莱斯特城": "Leicester",
    "南安普顿": "Southampton", "米德尔斯堡": "Middlesbrough",
    # 西甲
    "皇家马德里": "Real Madrid", "巴塞罗那": "Barcelona", "马德里竞技": "Atletico Madrid",
    "皇家苏斯达": "Real Sociedad", "比雷亚雷亚尔": "Villarreal",
    "皇家贝迪斯": "Real Betis", "塞维利亚": "Sevilla", "华伦西亚": "Valencia",
    "奥萨苏纳": "Osasuna", "赫塔费": "Getafe", "塞尔塔": "Celta Vigo",
    "维戈塞尔塔": "Celta Vigo", "阿拉维斯": "Alaves", "巴列卡诺": "Rayo Vallecano",
    "马洛卡": "Mallorca", "拉斯帕尔马斯": "Las Palmas", "格拉纳达": "Granada",
    "加的斯": "Cadiz", "阿尔梅里亚": "Almeria", "马拉加": "Malaga",
    "拉科鲁尼亚": "Deportivo La Coruna", "艾尔切": "Elche",
    "爱斯宾奴": "Espanyol", "利云特": "Levante", "桑坦德": "Racing Santander",
    "萨拉戈萨": "Zaragoza", "希洪竞技": "Sporting Gijon",
    # 德甲
    "拜仁慕尼黑": "Bayern Munich", "多特蒙德": "Borussia Dortmund",
    "勒沃库森": "Bayer Leverkusen", "RB莱比锡": "RB Leipzig",
    "法兰克福": "Eintracht Frankfurt", "沃尔夫斯堡": "Wolfsburg",
    "弗赖堡": "Freiburg", "门兴格拉德巴赫": "Borussia Monchengladbach",
    "斯图加特": "Stuttgart", "云达不莱梅": "Werder Bremen",
    "霍芬海姆": "Hoffenheim", "柏林联": "Union Berlin",
    "科隆": "Cologne", "奥格斯堡": "Augsburg", "奥斯堡": "Augsburg",
    "美因茨05": "Mainz 05", "美因茨": "Mainz 05",
    "波鸿": "Bochum", "达姆施塔特": "Darmstadt",
    "汉堡": "Hamburg", "帕德博恩": "Paderborn",
    "沙尔克04": "Schalke 04", "柏林赫塔": "Hertha Berlin",
    "汉诺威96": "Hannover 96", "杜塞尔多夫": "Fortuna Dusseldorf",
    "凯泽斯劳滕": "Kaiserslautern", "马格德堡": "Magdeburg",
    "艾禾斯堡": "Elversberg", "卡尔斯鲁厄": "Karlsruhe",
    # 意甲
    "国际米兰": "Inter", "AC米兰": "AC Milan", "尤文图斯": "Juventus",
    "那不勒斯": "Napoli", "罗马": "Roma", "拉齐奥": "Lazio",
    "亚特兰大": "Atalanta", "佛罗伦萨": "Fiorentina", "都灵": "Torino",
    "博洛尼亚": "Bologna", "蒙扎": "Monza", "乌迪内斯": "Udinese",
    "萨索洛": "Sassuolo", "恩波利": "Empoli", "卡利亚里": "Cagliari",
    "维罗纳": "Verona", "莱切": "Lecce", "热那亚": "Genoa",
    "弗洛西诺尼": "Frosinone", "萨勒尼塔纳": "Salernitana",
    "帕尔马": "Parma", "科木": "Como", "威尼斯": "Venezia",
    "克雷莫纳": "Cremonese", "巴里": "Bari", "布雷西亚": "Brescia",
    # 法甲
    "巴黎圣日耳曼": "Paris Saint Germain", "马赛": "Marseille",
    "摩纳哥": "Monaco", "里尔": "Lille", "尼斯": "Nice",
    "里昂": "Lyon", "朗斯": "Lens", "雷恩": "Rennes",
    "图鲁兹": "Toulouse", "斯特拉斯堡": "Strasbourg",
    "蒙彼利埃": "Montpellier", "南特": "Nantes",
    "布雷斯特": "Brest", "利文斯": "Le Havre",
    "洛里昂": "Lorient", "克莱蒙": "Clermont",
    "梅斯": "Metz", "昂热": "Angers", "欧塞尔": "Auxerre",
    "圣埃蒂安": "Saint Etienne", "巴黎": "Paris FC",
    "特鲁瓦": "Troyes", "甘冈": "Guingamp",
    # 瑞超
    "马尔默": "Malmo FF", "尤尔加登": "Djurgardens IF", "卡尔马": "Kalmar FF",
    "奥尔格里特": "Orgryte IS", "AIK索尔纳": "AIK", "哈马比": "Hammarby",
    "哥德堡": "IFK Goteborg", "埃尔夫斯堡": "Elfsborg", "赫根": "Hacken",
    "北雪平": "Norrkoping", "锡里乌斯": "Sirius", "瓦尔贝里": "Varbergs BoIS",
    "米亚尔比": "Mjallby", "布洛马波卡纳": "Brommapojkarna",
    "哈尔姆斯塔德": "Halmstad", "代格福什": "Degerfors",
    "韦纳穆": "Varnamo", "松兹瓦尔": "GIF Sundsvall",
    # 瑞超(API-Football返回的全名格式)
    "哈马比": "Hammarby FF", "赫根": "BK Hacken", "AIK": "AIK Stockholm",
    "盖斯": "Gais", "韦斯特罗斯": "Vasteras SK FK",
    "埃尔夫斯堡": "IF Elfsborg", "米亚尔比": "Mjallby AIF",
    "布洛马波卡纳": "IF Brommapojkarna", "代格福什": "Degerfors IF",
    # 芬超
    "伊尔韦斯": "Ilves", "图尔库PS": "Turku PS", "拉赫蒂": "Lahti",
    "玛丽港": "Mariehamn", "赫尔辛基": "HJK helsinki", "洪卡": "Honka",
    "库奥皮奥": "KuPS", "塞伊奈约基": "SJK", "奥卢": "AC Oulu",
    "科特卡": "KTP", "哈卡": "Haka", "瓦萨": "VPS",
    # 芬超(API-Football返回的全名格式)
    "国际图尔库": "Inter Turku", "HJK赫尔辛基": "HJK Helsinki",
    "格尼斯坦": "Gnistan", "亚罗": "FF Jaro",
    # 挪超
    "博多格林特": "Bodo/Glimt", "莫尔德": "Molde", "罗森博格": "Rosenborg",
    "维京": "Viking", "利勒斯特罗姆": "Lillestrom", "瓦勒伦加": "Valerenga",
    "布兰": "Brann", "特罗姆瑟": "Tromso", "萨尔普斯堡": "Sarpsborg 08",
    "斯特伦斯戈德塞特": "Stromsgodset", "奥德": "Odd", "桑纳菲尤尔": "Sandefjord",
    # 丹超
    "哥本哈根": "FC Copenhagen", "中日德兰": "FC Midtjylland",
    "布隆德比": "Brondby", "奥胡斯": "AGF", "北西兰": "Nordsjaelland",
    "锡尔克堡": "Silkeborg", "兰德斯": "Randers", "欧登塞": "OB",
    "维堡": "Viborg", "林比": "Lyngby", "瓦埃勒": "Vejle", "霍森斯": "Horsens",
}

# 联赛名 → API-Football联赛ID (同时支持皇冠长名和API短名)
LEAGUE_MAP = {
    # 皇冠长名
    "英格兰超级联赛": 39, "英格兰冠军联赛": 40,
    "西班牙甲组联赛": 140, "西班牙乙组联赛": 141,
    "意大利甲组联赛": 135, "意大利乙组联赛": 136,
    "德国甲组联赛": 78, "德国乙组联赛": 79,
    "法国甲组联赛": 61, "法国乙组联赛": 62,
    "荷兰甲组联赛": 88, "葡萄牙超级联赛": 94,
    "瑞典超级联赛": 113, "芬兰超级联赛": 244,
    "挪威超级联赛": 103, "丹麦超级联赛": 119,
    # API-Football短名(matches表实际存储格式)
    "英超": 39, "英冠": 40, "英甲": 41,
    "西甲": 140, "西乙": 141,
    "意甲": 135, "意乙": 136,
    "德甲": 78, "德乙": 79,
    "法甲": 61, "法乙": 62,
    "荷甲": 88, "荷乙": 89,
    "葡超": 94, "葡甲": 95,
    "瑞超": 113, "芬超": 244, "挪超": 103, "丹超": 119,
    "欧冠": 2, "欧联": 3, "欧协联": 848,
    "阿甲": 128, "巴甲": 71, "解放者杯": 13,
    "美职联": 253, "日职": 98, "日乙": 99, "韩K": 292,
    "土超": 203, "俄超": 235, "比甲": 37, "苏超": 179,
    "瑞士超": 170, "奥甲": 184, "澳超": 169,
}

# 当前赛季
CURRENT_SEASON = 2026


def enrich_matches_with_stats(matches: list) -> list:
    """
    为比赛列表补充球队统计数据(排名/近况/进失球)
    
    参数: matches - CrownOddsScraper抓取的比赛列表
    返回: 补充了home_stats/away_stats的比赛列表
    """
    from scraper.apifootball_data import APIFootballClient
    
    client = APIFootballClient()
    if not client.api_key:
        log.warning("[充实] API-Football密钥不可用，跳过球队数据")
        return matches
    
    # 收集需要查询的联赛
    leagues_needed = set()
    for m in matches:
        league_id = LEAGUE_MAP.get(m.get('league', ''))
        if league_id:
            leagues_needed.add(league_id)
    
    if not leagues_needed:
        log.info("[充实] 无可映射的联赛，跳过")
        return matches
    
    # 批量获取积分榜(每个联赛一次请求)
    standings_cache = {}
    for league_id in leagues_needed:
        log.info(f"[充实] 获取联赛{league_id}积分榜...")
        standings = client.get_standings(league_id, CURRENT_SEASON)
        if standings:
            standings_cache[league_id] = standings
            log.info(f"[充实] 联赛{league_id}: {len(standings)}支球队")
        else:
            # 试上赛季
            standings = client.get_standings(league_id, CURRENT_SEASON - 1)
            if standings:
                standings_cache[league_id] = standings
                log.info(f"[充实] 联赛{league_id}(上赛季): {len(standings)}支球队")
    
    if not standings_cache:
        log.warning("[充实] 未获取到任何积分榜数据")
        return matches
    
    # 为每场比赛匹配球队数据
    enriched = 0
    for m in matches:
        league_id = LEAGUE_MAP.get(m.get('league', ''))
        if not league_id or league_id not in standings_cache:
            continue
        
        standings = standings_cache[league_id]
        league_name = m.get('league', '')
        
        home_name = m.get('home_team', '') or m.get('home', '')
        away_name = m.get('away_team', '') or m.get('away', '')
        
        home_stats = _match_team(home_name, standings)
        away_stats = _match_team(away_name, standings)
        
        if home_stats:
            m['home_stats'] = _format_stats(home_stats)
            _persist_team_stats(home_name, league_name, home_stats)
            enriched += 1
        if away_stats:
            m['away_stats'] = _format_stats(away_stats)
            _persist_team_stats(away_name, league_name, away_stats)
            enriched += 1
    
    log.info(f"[充实] 完成: {enriched}个球队数据已匹配")
    return matches


def _persist_team_stats(team_name: str, league: str, raw_stats: dict):
    """将球队数据持久化到team_stats表，供analyze_matches()通过get_team_stats()读取"""
    from utils.database import get_connection
    stats = _format_stats(raw_stats)
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO team_stats
            (team_name, league, season, rank, played, wins, draws, losses,
             goals_for, goals_against, home_wins, away_wins, recent_form, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        """, (
            team_name, league, str(CURRENT_SEASON),
            stats.get("rank", 0), stats.get("played", 0),
            stats.get("wins", 0), stats.get("draws", 0), stats.get("losses", 0),
            stats.get("goals_for", 0), stats.get("goals_against", 0),
            stats.get("home_wins", 0), stats.get("away_wins", 0),
            stats.get("recent_form", ""),
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"[充实] 持久化{team_name}失败: {e}")


def _match_team(name: str, standings: dict):
    """
    匹配球队名到积分榜数据。
    尝试顺序:
    1. 直接用名字匹配(已经是英文名)
    2. 中文→英文映射后匹配
    3. 模糊匹配(名字包含关系)
    """
    if not name:
        return None
    
    # 1. 直接匹配
    if name in standings:
        return standings[name]
    
    # 2. 中文→英文映射
    en_name = TEAM_NAME_MAP.get(name)
    if en_name and en_name in standings:
        return standings[en_name]
    
    # 3. 模糊匹配(名字包含)
    for team_key, stats in standings.items():
        if name.lower() in team_key.lower() or team_key.lower() in name.lower():
            return stats
    
    return None


def _format_stats(raw: dict) -> dict:
    """将API-Football积分榜数据转为实力模型需要的格式"""
    form = raw.get('form', '')
    return {
        "rank": raw.get('rank', 0),
        "played": raw.get('played', 0),
        "wins": raw.get('wins', 0),
        "draws": raw.get('draws', 0),
        "losses": raw.get('losses', 0),
        "goals_for": raw.get('goals_for', 0),
        "goals_against": raw.get('goals_against', 0),
        "home_wins": raw.get('wins', 0),  # 积分榜没有主客分开，用总胜场近似
        "away_wins": raw.get('wins', 0),
        "recent_form": form[-5:] if form else "",
        "points": raw.get('points', 0),
    }
