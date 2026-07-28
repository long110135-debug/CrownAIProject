"""
皇冠AI赛事研判系统 - API-Football数据源
复用ZCode的API-Football Pro计划，获取赛程+球队数据
"""
import subprocess
import json
import time
from datetime import datetime, timedelta
from typing import List, Optional
from utils.logger import log


# === API-Football联赛ID映射 ===
# 一级联赛
LEAGUE_IDS_TIER1 = {
    # 欧洲五大联赛
    39: "英超",
    140: "西甲",
    135: "意甲",
    78: "德甲",
    61: "法甲",
    # 欧洲其他顶级
    88: "荷甲",
    94: "葡超",
    203: "土超",
    37: "比甲",
    179: "苏超",
    # 北欧(夏季联赛，7-8月有比赛)
    113: "瑞超",
    244: "芬超",
    103: "挪超",
    119: "丹超",
    # 中欧/东欧
    170: "瑞士超",
    184: "奥甲",
    235: "俄超",
    # 洲际赛事
    2: "欧冠",
    3: "欧联",
    848: "欧协联",
    # 南美
    71: "巴甲",
    128: "阿甲",
    13: "解放者杯",
    # 亚洲
    98: "日职",
    292: "韩K",
    169: "澳超",
    # 北美
    253: "美职联",
}

# 二级联赛
LEAGUE_IDS_TIER2 = {
    40: "英冠",
    79: "德乙",
    141: "西乙",
    136: "意乙",
    62: "法乙",
    89: "荷乙",
    95: "葡甲",
    99: "日乙",
    41: "英甲",
}

ALL_LEAGUE_IDS = {**LEAGUE_IDS_TIER1, **LEAGUE_IDS_TIER2}


def get_api_key() -> str:
    """从macOS钥匙串获取API-Football密钥"""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-s", "ZCodeProject_API_FOOTBALL_KEY", "-w"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception as e:
        log.warning(f"钥匙串读取失败: {e}")

    # 备用: 环境变量
    import os
    key = os.environ.get("API_FOOTBALL_KEY", "")
    if key:
        return key

    log.error("未找到API-Football密钥，请确认钥匙串中有ZCodeProject_API_FOOTBALL_KEY")
    return ""


class APIFootballClient:
    """API-Football客户端"""

    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(self):
        self.api_key = get_api_key()
        self.headers = {
            "x-apisports-key": self.api_key,
        }
        self._request_count = 0

    def _request(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """发送API请求"""
        if not self.api_key:
            log.error("API密钥为空，无法请求")
            return None

        import requests
        url = f"{self.BASE_URL}/{endpoint}"
        self._request_count += 1

        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("errors"):
                    log.warning(f"API错误: {data['errors']}")
                    return None
                return data
            elif resp.status_code == 429:
                log.warning("API限流，等待60秒...")
                time.sleep(60)
                return self._request(endpoint, params)
            else:
                log.warning(f"API HTTP {resp.status_code}: {endpoint}")
                return None
        except Exception as e:
            log.error(f"API请求异常: {e}")
            return None

    def get_fixtures_today(self) -> List[dict]:
        """
        获取今日所有比赛（按联赛ID过滤）
        
        返回: [{league, home_team, away_team, match_time, season, match_id, league_id}]
        """
        today = datetime.now().strftime("%Y-%m-%d")
        log.info(f"[API-Football] 获取 {today} 赛程...")

        all_fixtures = []

        # 按联赛批量获取（减少请求次数）
        # API-Football支持date参数获取某天所有比赛
        data = self._request("fixtures", {"date": today})
        if not data:
            return []

        fixtures = data.get("response", [])
        log.info(f"[API-Football] 今日共{len(fixtures)}场比赛，筛选目标联赛...")

        for fixture in fixtures:
            league_id = fixture.get("league", {}).get("id")
            if league_id not in ALL_LEAGUE_IDS:
                continue

            league_name = ALL_LEAGUE_IDS[league_id]
            tier = 1 if league_id in LEAGUE_IDS_TIER1 else 2

            match_info = {
                "match_id": f"AF_{fixture['fixture']['id']}",
                "fixture_id": fixture["fixture"]["id"],
                "league": league_name,
                "league_id": league_id,
                "league_tier": tier,
                "season": fixture.get("league", {}).get("season", ""),
                "home_team": fixture.get("teams", {}).get("home", {}).get("name", ""),
                "away_team": fixture.get("teams", {}).get("away", {}).get("name", ""),
                "match_time": self._format_time(fixture.get("fixture", {}).get("date", "")),
                "status": fixture.get("fixture", {}).get("status", {}).get("short", "NS"),
                "venue": fixture.get("fixture", {}).get("venue", {}).get("name", ""),
            }
            all_fixtures.append(match_info)

        log.info(f"[API-Football] 筛选后: {len(all_fixtures)}场目标联赛比赛")
        return all_fixtures

    def get_fixtures_by_date(self, date_str: str) -> List[dict]:
        """获取指定日期比赛"""
        data = self._request("fixtures", {"date": date_str})
        if not data:
            return []

        fixtures = data.get("response", [])
        results = []
        for fixture in fixtures:
            league_id = fixture.get("league", {}).get("id")
            if league_id not in ALL_LEAGUE_IDS:
                continue

            league_name = ALL_LEAGUE_IDS[league_id]
            tier = 1 if league_id in LEAGUE_IDS_TIER1 else 2

            results.append({
                "match_id": f"AF_{fixture['fixture']['id']}",
                "fixture_id": fixture["fixture"]["id"],
                "league": league_name,
                "league_id": league_id,
                "league_tier": tier,
                "season": fixture.get("league", {}).get("season", ""),
                "home_team": fixture.get("teams", {}).get("home", {}).get("name", ""),
                "away_team": fixture.get("teams", {}).get("away", {}).get("name", ""),
                "match_time": self._format_time(fixture.get("fixture", {}).get("date", "")),
                "status": fixture.get("fixture", {}).get("status", {}).get("short", "NS"),
            })
        return results

    def get_team_statistics(self, team_id: int, league_id: int, season: int) -> Optional[dict]:
        """
        获取球队赛季统计
        
        返回: {rank, played, wins, draws, losses, goals_for, goals_against, 
               home_wins, away_wins, form, xg, xga}
        """
        data = self._request("teams/statistics", {
            "team": team_id,
            "league": league_id,
            "season": season,
        })
        if not data or not data.get("response"):
            return None

        resp = data["response"]
        league_data = resp.get("league", {})
        fixtures_data = resp.get("fixtures", {})
        goals_data = resp.get("goals", {})
        form = resp.get("form", "")

        played = fixtures_data.get("played", {}).get("total", 0)
        wins = fixtures_data.get("wins", {}).get("total", 0)
        draws = fixtures_data.get("draws", {}).get("total", 0)
        losses = fixtures_data.get("losses", {}).get("total", 0)
        home_wins = fixtures_data.get("wins", {}).get("home", 0)
        away_wins = fixtures_data.get("wins", {}).get("away", 0)

        gf = goals_data.get("for", {}).get("total", {}).get("total", 0)
        ga = goals_data.get("against", {}).get("total", {}).get("total", 0)

        # 排名需要从standings获取
        return {
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "home_wins": home_wins,
            "away_wins": away_wins,
            "goals_for": gf if isinstance(gf, int) else 0,
            "goals_against": ga if isinstance(ga, int) else 0,
            "recent_form": form[-5:] if form else "",  # 最近5场
            "clean_sheets": resp.get("clean_sheet", {}).get("total", 0),
            "failed_to_score": resp.get("failed_to_score", {}).get("total", 0),
            "avg_goals_for": self._safe_avg(gf, played),
            "avg_goals_against": self._safe_avg(ga, played),
        }

    def get_standings(self, league_id: int, season: int) -> dict:
        """
        获取联赛积分榜
        返回: {team_name: {rank, points, played, ...}}
        """
        data = self._request("standings", {
            "league": league_id,
            "season": season,
        })
        if not data or not data.get("response"):
            return {}

        standings = {}
        for league_block in data["response"]:
            for group in league_block.get("league", {}).get("standings", []):
                for team_row in group:
                    team_name = team_row.get("team", {}).get("name", "")
                    standings[team_name] = {
                        "rank": team_row.get("rank", 0),
                        "points": team_row.get("points", 0),
                        "played": team_row.get("all", {}).get("played", 0),
                        "wins": team_row.get("all", {}).get("win", 0),
                        "draws": team_row.get("all", {}).get("draw", 0),
                        "losses": team_row.get("all", {}).get("lose", 0),
                        "goals_for": team_row.get("all", {}).get("goals", {}).get("for", 0),
                        "goals_against": team_row.get("all", {}).get("goals", {}).get("against", 0),
                        "form": team_row.get("form", ""),
                        "team_id": team_row.get("team", {}).get("id", 0),
                    }
        return standings

    def get_team_last_matches(self, team_id: int, last: int = 10) -> List[dict]:
        """
        获取球队最近N场比赛
        """
        data = self._request("fixtures", {
            "team": team_id,
            "last": last,
        })
        if not data:
            return []

        matches = []
        for fixture in data.get("response", []):
            status = fixture.get("fixture", {}).get("status", {}).get("short", "")
            if status not in ("FT", "AET", "PEN"):
                continue

            home = fixture.get("teams", {}).get("home", {})
            away = fixture.get("teams", {}).get("away", {})
            goals = fixture.get("goals", {})

            matches.append({
                "date": fixture.get("fixture", {}).get("date", ""),
                "home": home.get("name", ""),
                "away": away.get("name", ""),
                "home_goals": goals.get("home"),
                "away_goals": goals.get("away"),
                "is_home": home.get("id") == team_id,
                "league": fixture.get("league", {}).get("name", ""),
            })
        return matches

    def get_injuries(self, fixture_id: int) -> dict:
        """
        获取比赛伤停信息
        
        返回: {home: [{player, reason}], away: [{player, reason}]}
        """
        data = self._request("injuries", {"fixture": fixture_id})
        if not data:
            return {"home": [], "away": []}

        home_injuries = []
        away_injuries = []
        for injury in data.get("response", []):
            player = injury.get("player", {}).get("name", "")
            reason = injury.get("player", {}).get("reason", "")
            team_id = injury.get("team", {}).get("id", 0)

            entry = {"player": player, "reason": reason}
            # 需要和比赛的team_id对比来确定主客
            home_injuries.append(entry)  # 简化处理，后续可精确区分

        return {"home": home_injuries, "away": away_injuries}

    def get_odds(self, fixture_id: int) -> Optional[dict]:
        """
        获取API-Football提供的赔率数据（含亚洲盘口）
        注意: API-Football的odds端点包含部分bookmaker的亚洲盘口
        
        返回: {bookmaker, asian_handicap, home_odds, away_odds, ...}
        """
        data = self._request("odds", {
            "fixture": fixture_id,
            "bookmaker": 8,  # 8 = Crown/皇冠 (如果可用)
        })

        if not data or not data.get("response"):
            # 尝试不指定bookmaker获取所有
            data = self._request("odds", {"fixture": fixture_id})
            if not data or not data.get("response"):
                return None

        # 解析赔率数据
        return self._parse_odds_response(data)

    def _parse_odds_response(self, data: dict) -> Optional[dict]:
        """解析API-Football赔率响应"""
        for item in data.get("response", []):
            bookmakers = item.get("bookmakers", [])
            for bk in bookmakers:
                bk_name = bk.get("name", "")
                bk_id = bk.get("id", 0)

                # 优先找Crown(8)或类似亚洲盘口公司
                for bet in bk.get("bets", []):
                    bet_name = bet.get("name", "")

                    # Asian Handicap
                    if "Asian" in bet_name or "Handicap" in bet_name:
                        values = bet.get("values", [])
                        for val in values:
                            if val.get("value") == "Home":
                                home_odds = self._safe_float(val.get("odd"))
                            elif val.get("value") == "Away":
                                away_odds = self._safe_float(val.get("odd"))

                        return {
                            "bookmaker": bk_name,
                            "bookmaker_id": bk_id,
                            "bet_type": bet_name,
                            "values": values,
                            "source": "api-football",
                        }

        return None

    def get_current_season(self, league_id: int) -> int:
        """获取联赛当前赛季年份"""
        # 大部分联赛2025-2026赛季
        now = datetime.now()
        if now.month >= 7:
            return now.year  # 2026
        else:
            return now.year - 1  # 2025

    def _format_time(self, utc_time: str) -> str:
        """UTC时间转北京时间"""
        if not utc_time:
            return ""
        try:
            dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
            # 转UTC+8
            dt_local = dt + timedelta(hours=8)
            return dt_local.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return utc_time

    def _safe_float(self, val) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0

    def _safe_avg(self, total, played) -> float:
        if not played:
            return 0.0
        if isinstance(total, int):
            return round(total / played, 2)
        return 0.0
