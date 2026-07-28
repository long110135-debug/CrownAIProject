"""
皇冠AI赛事研判系统 - 联赛池配置
只分析一级/二级联赛，过滤青年队、低级别、友谊赛
"""

# === 一级联赛 ===
TIER1_LEAGUES = {
    # 欧洲五大联赛
    "英超": {"country": "英格兰", "code": "EPL", "priority": 1},
    "西甲": {"country": "西班牙", "code": "LaLiga", "priority": 1},
    "意甲": {"country": "意大利", "code": "SerieA", "priority": 1},
    "德甲": {"country": "德国", "code": "Bundesliga", "priority": 1},
    "法甲": {"country": "法国", "code": "Ligue1", "priority": 1},
    # 欧洲其他顶级
    "荷甲": {"country": "荷兰", "code": "Eredivisie", "priority": 1},
    "葡超": {"country": "葡萄牙", "code": "PrimeiraLiga", "priority": 1},
    # 洲际赛事
    "欧冠": {"country": "欧洲", "code": "UCL", "priority": 1},
    "欧联": {"country": "欧洲", "code": "UEL", "priority": 1},
    "欧协联": {"country": "欧洲", "code": "UECL", "priority": 2},
    # 南美
    "巴甲": {"country": "巴西", "code": "Brasileirao", "priority": 1},
    "阿甲": {"country": "阿根廷", "code": "LigaPro", "priority": 2},
    "解放者杯": {"country": "南美", "code": "Libertadores", "priority": 1},
    # 亚洲
    "日职": {"country": "日本", "code": "J1", "priority": 2},
    "韩K": {"country": "韩国", "code": "KLeague1", "priority": 2},
    "澳超": {"country": "澳大利亚", "code": "ALeague", "priority": 3},
    # 北美
    "美职联": {"country": "美国", "code": "MLS", "priority": 2},
    # 北欧(夏季联赛)
    "瑞超": {"country": "瑞典", "code": "Allsvenskan", "priority": 2},
    "芬超": {"country": "芬兰", "code": "Veikkausliiga", "priority": 2},
    "挪超": {"country": "挪威", "code": "Eliteserien", "priority": 2},
    "丹超": {"country": "丹麦", "code": "Superliga", "priority": 2},
    # 中欧/东欧
    "瑞士超": {"country": "瑞士", "code": "SuperLeague", "priority": 3},
    "奥甲": {"country": "奥地利", "code": "Bundesliga", "priority": 3},
    "俄超": {"country": "俄罗斯", "code": "RPL", "priority": 3},
    # 其他欧洲
    "土超": {"country": "土耳其", "code": "SuperLig", "priority": 2},
    "比甲": {"country": "比利时", "code": "ProLeague", "priority": 3},
    "苏超": {"country": "苏格兰", "code": "SPFL", "priority": 3},
}

# === 二级联赛 ===
TIER2_LEAGUES = {
    "英冠": {"country": "英格兰", "code": "Championship", "priority": 2},
    "德乙": {"country": "德国", "code": "Bundesliga2", "priority": 2},
    "西乙": {"country": "西班牙", "code": "LaLiga2", "priority": 2},
    "意乙": {"country": "意大利", "code": "SerieB", "priority": 2},
    "法乙": {"country": "法国", "code": "Ligue2", "priority": 2},
    "荷乙": {"country": "荷兰", "code": "EersteDivisie", "priority": 3},
    "葡甲": {"country": "葡萄牙", "code": "SegundaLiga", "priority": 3},
    "日乙": {"country": "日本", "code": "J2", "priority": 3},
    "英甲": {"country": "英格兰", "code": "League1", "priority": 3},
}

# === 过滤关键词（匹配到即排除） ===
FILTER_KEYWORDS = [
    "青年", "U19", "U21", "U23", "预备队", "梯队",
    "友谊赛", "热身赛", "表演赛",
    "全明星", "选拔队",
    "女足",  # 暂时排除，后续可加入
    "室内", "五人制", "沙滩",
]

# === 特殊赛事白名单（友谊赛中有价值的） ===
SPECIAL_WHITELIST = [
    "国际冠军杯",
    "酋长杯",
    "奥迪杯",
]


def get_all_leagues():
    """获取所有允许的联赛"""
    all_leagues = {}
    all_leagues.update(TIER1_LEAGUES)
    all_leagues.update(TIER2_LEAGUES)
    return all_leagues


def get_tier1_names():
    """获取一级联赛名称列表"""
    return list(TIER1_LEAGUES.keys())


def get_tier2_names():
    """获取二级联赛名称列表"""
    return list(TIER2_LEAGUES.keys())


def is_allowed_league(league_name: str) -> bool:
    """判断联赛是否在允许池中"""
    all_names = set(TIER1_LEAGUES.keys()) | set(TIER2_LEAGUES.keys())
    return league_name in all_names


def should_filter(match_info: dict) -> bool:
    """判断比赛是否应被过滤"""
    home = match_info.get('home', '') or match_info.get('home_team', '')
    away = match_info.get('away', '') or match_info.get('away_team', '')
    league = match_info.get('league', '')
    text = f"{home} {away} {league}"
    for keyword in FILTER_KEYWORDS:
        if keyword in text:
            # 检查白名单
            for white in SPECIAL_WHITELIST:
                if white in text:
                    return False
            return True
    return False


def get_league_tier(league_name: str) -> int:
    """获取联赛等级 1/2/0(不在池中)"""
    if league_name in TIER1_LEAGUES:
        return 1
    if league_name in TIER2_LEAGUES:
        return 2
    return 0
