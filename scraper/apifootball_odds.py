"""
皇冠AI赛事研判系统 - API-Football盘口数据源
从API-Football odds端点获取亚盘数据(主数据源，不依赖Playwright)

优先级: Bet365 > Marathonbet > 10Bet > Unibet > 其他
输出标准格式: {handicap, home_water, away_water, over_line, over_water, under_water}
"""
import re
from typing import Optional, List
from utils.logger import log


# 优先使用的博彩公司(按可靠性排序)
PREFERRED_BOOKMAKERS = [
    "Bet365", "Marathonbet", "Pinnacle", "10Bet", "Unibet",
    "William Hill", "Betfair", "1xBet", "Betway",
]


def fetch_odds_for_fixture(client, fixture_id: int) -> Optional[dict]:
    """
    从API-Football获取单场比赛的亚盘+大小球
    遍历多家博彩公司(按优先级)，直到找到有效盘口(水位在合理范围内)
    
    返回: {
        "handicap": "主让0.5",
        "home_water": 1.95,
        "away_water": 1.80,
        "over_line": "2.5",
        "over_water": 1.90,
        "under_water": 1.90,
        "bookmaker": "Bet365",
        "source": "api-football",
    }
    """
    data = client._request("odds", {"fixture": fixture_id})
    if not data or not data.get("response"):
        return None

    bookmakers = data["response"][0].get("bookmakers", [])
    if not bookmakers:
        return None

    # 按优先级排序所有公司
    sorted_bms = _sort_bookmakers(bookmakers)

    # 遍历多家公司，找到第一个有有效亚盘的
    result = {"source": "api-football"}
    for bm in sorted_bms:
        asian = _parse_asian_handicap(bm)
        if asian and asian.get("handicap"):
            result["handicap"] = asian["handicap"]
            result["home_water"] = asian["home_water"]
            result["away_water"] = asian["away_water"]
            result["bookmaker"] = bm.get("name", "")
            break

    # 大小球: 从所有公司中找最平衡的
    ou = _parse_over_under_best(sorted_bms)
    if ou:
        result.update(ou)

    return result if result.get("handicap") or result.get("over_line") else None


def fetch_odds_batch(client, fixture_ids: List[int]) -> dict:
    """
    批量获取盘口(逐场调用，带限流)
    
    返回: {fixture_id: odds_dict}
    """
    import time
    results = {}
    for fid in fixture_ids:
        odds = fetch_odds_for_fixture(client, fid)
        if odds:
            results[fid] = odds
        time.sleep(0.5)  # API限流
    return results


def _sort_bookmakers(bookmakers: list) -> list:
    """按优先级排序所有博彩公司(优先列表在前，其余在后)"""
    preferred = []
    others = []
    pref_set = set(PREFERRED_BOOKMAKERS)
    for bm in bookmakers:
        if bm.get("name", "") in pref_set:
            preferred.append(bm)
        else:
            others.append(bm)
    # 优先列表内部按PREFERRED_BOOKMAKERS顺序
    preferred.sort(key=lambda x: PREFERRED_BOOKMAKERS.index(x.get("name", ""))
                   if x.get("name", "") in PREFERRED_BOOKMAKERS else 999)
    return preferred + others


def _parse_over_under_best(bookmakers: list) -> Optional[dict]:
    """从所有公司中找最平衡的大小球线"""
    best = None
    best_balance = 999
    for bm in bookmakers:
        ou = _parse_over_under(bm)
        if ou:
            ov = ou.get("over_water", 0)
            un = ou.get("under_water", 0)
            balance = abs(ov - 1.9) + abs(un - 1.9)
            if balance < best_balance:
                best_balance = balance
                best = ou
    return best


def _parse_asian_handicap(bookmaker: dict) -> Optional[dict]:
    """
    解析亚盘数据，选择主流盘口线(水位最接近平衡的那条)
    
    API-Football格式:
    bet.name = "Asian Handicap"
    bet.values = [
        {"value": "Home -1.25", "odd": "4.80"},
        {"value": "Away -1.25", "odd": "1.18"},
        {"value": "Home +0.5", "odd": "1.95"},
        {"value": "Away +0.5", "odd": "1.80"},
        ...
    ]
    
    策略: 按handicap值配对Home/Away，选水位最接近2.0的配对
    """
    for bet in bookmaker.get("bets", []):
        bet_name = bet.get("name", "")
        if "Asian Handicap" not in bet_name and "Asian" not in bet_name:
            continue

        values = bet.get("values", [])
        if not values:
            continue

        # 按handicap值分组配对
        # "Home -0.5" → handicap=0.5(主让), "Away -0.5" → 同一盘口的客队方
        # "Home +0.5" → handicap=-0.5(客让), "Away +0.5" → 同一盘口
        pairs = {}  # {handicap_value: {"home_odd": x, "away_odd": y}}

        for v in values:
            val_str = v.get("value", "")
            odd = _safe_float(v.get("odd"))
            if odd <= 0:
                continue

            hdp = _extract_handicap_value(val_str)
            if hdp is None:
                continue

            if val_str.startswith("Home"):
                # "Home -0.5" = 主让0.5 → key=+0.5 (主让为正)
                # "Home +0.5" = 客让0.5 → key=-0.5
                key = -hdp
                if key not in pairs:
                    pairs[key] = {}
                pairs[key]["home_odd"] = odd
            elif val_str.startswith("Away"):
                # "Away -0.5" = 客让0.5 → key=-0.5
                # "Away +0.5" = 主让0.5 → key=+0.5
                key = hdp
                if key not in pairs:
                    pairs[key] = {}
                pairs[key]["away_odd"] = odd

        # 选择最平衡的配对(主客水位之和最接近2.0，且两边都有值)
        best_pair = None
        best_balance = 999

        for hdp_key, odds in pairs.items():
            hw = odds.get("home_odd")
            aw = odds.get("away_odd")
            if hw and aw and 1.3 <= hw <= 2.7 and 1.3 <= aw <= 2.7:
                # 水位越接近平衡(各~1.9)越好
                balance = abs(hw - 1.9) + abs(aw - 1.9)
                if balance < best_balance:
                    best_balance = balance
                    best_pair = (hdp_key, hw, aw)

        if best_pair:
            hdp_key, hw, aw = best_pair
            handicap_text = _format_handicap(hdp_key)
            return {
                "handicap": handicap_text,
                "home_water": hw,
                "away_water": aw,
            }

    return None


def _parse_over_under(bookmaker: dict) -> Optional[dict]:
    """解析大小球，选主流线(水位最平衡的)"""
    for bet in bookmaker.get("bets", []):
        bet_name = bet.get("name", "")
        if "Over/Under" not in bet_name and "Goals O/U" not in bet_name:
            continue

        values = bet.get("values", [])
        if not values:
            continue

        # 按line分组: {"2.5": {"over": 1.9, "under": 1.9}}
        lines = {}
        for v in values:
            val_str = v.get("value", "")
            odd = _safe_float(v.get("odd"))
            if odd <= 0:
                continue

            nums = re.findall(r'[\d.]+', val_str)
            if not nums:
                continue
            line_val = nums[0]

            if line_val not in lines:
                lines[line_val] = {}

            if val_str.startswith("Over"):
                lines[line_val]["over"] = odd
            elif val_str.startswith("Under"):
                lines[line_val]["under"] = odd

        # 选最平衡的线(两边水位都>1.0且最接近1.9)
        best_line = None
        best_balance = 999

        for line_val, odds in lines.items():
            ov = odds.get("over")
            un = odds.get("under")
            if ov and un and ov > 1.0 and un > 1.0:
                balance = abs(ov - 1.9) + abs(un - 1.9)
                if balance < best_balance:
                    best_balance = balance
                    best_line = (line_val, ov, un)

        if best_line:
            return {
                "over_line": best_line[0],
                "over_water": best_line[1],
                "under_water": best_line[2],
            }

    return None


def _extract_handicap_value(val_str: str) -> Optional[float]:
    """
    从 "Home -0.5" 或 "Away +1.25" 提取盘口值
    Home -0.5 → 0.5 (主让0.5)
    Home +0.5 → -0.5 (主受让0.5 = 客让0.5)
    """
    m = re.search(r'([+\-]?\s*[\d.]+)', val_str.replace("Home", "").replace("Away", "").strip())
    if not m:
        # 可能是 "Home +0" 表示平手
        if "+0" in val_str or "-0" in val_str:
            return 0.0
        return None
    val = float(m.group(1).replace(" ", ""))
    return val


def _format_handicap(val: float) -> str:
    """盘口数值转中文: 0.5→'主让0.5', -0.5→'客让0.5', 0→'平手'"""
    if val == 0:
        return "平手"
    elif val > 0:
        return f"主让{val}"
    else:
        return f"客让{abs(val)}"


def _safe_float(val) -> float:
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0
