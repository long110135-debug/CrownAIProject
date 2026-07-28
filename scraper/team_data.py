"""
皇冠AI赛事研判系统 - 球队数据模块
从API-Football获取: 近期10场、主客场、xG、进失球、伤停
供实力模型和阵容模型使用
"""
from typing import Optional
from utils.logger import log
from utils.database import get_team_stats


class TeamDataCollector:
    """球队数据采集器"""

    def __init__(self, api_client=None):
        self.api_client = api_client
        self._standings_cache = {}  # 联赛积分榜缓存

    def get_match_team_data(self, match: dict) -> dict:
        """
        获取一场比赛双方的完整数据
        
        返回:
        {
            "home_stats": {...},
            "away_stats": {...},
            "home_squad": {...},
            "away_squad": {...},
        }
        """
        home = match.get("home_team", "")
        away = match.get("away_team", "")
        league_id = match.get("league_id")
        season = match.get("season")
        fixture_id = match.get("fixture_id")

        log.info(f"[球队数据] 获取: {home} vs {away}")

        # 获取积分榜（含排名）
        standings = self._get_standings(league_id, season)

        # 主队数据
        home_stats = self._build_team_stats(home, standings, league_id, season)
        away_stats = self._build_team_stats(away, standings, league_id, season)

        # 伤停数据
        home_squad = self._get_squad_info(fixture_id, "home")
        away_squad = self._get_squad_info(fixture_id, "away")

        return {
            "home_stats": home_stats,
            "away_stats": away_stats,
            "home_squad": home_squad,
            "away_squad": away_squad,
        }

    def _get_standings(self, league_id: int, season) -> dict:
        """获取联赛积分榜（带缓存）"""
        if not self.api_client or not league_id:
            return {}

        cache_key = f"{league_id}_{season}"
        if cache_key in self._standings_cache:
            return self._standings_cache[cache_key]

        try:
            season_year = int(season) if season else self.api_client.get_current_season(league_id)
            standings = self.api_client.get_standings(league_id, season_year)
            self._standings_cache[cache_key] = standings
            log.info(f"[球队数据] 积分榜获取成功: league={league_id}, {len(standings)}支球队")
            return standings
        except Exception as e:
            log.warning(f"[球队数据] 积分榜获取失败: {e}")
            return {}

    def _build_team_stats(self, team_name: str, standings: dict,
                          league_id: int, season) -> dict:
        """构建球队统计数据"""
        # 优先从积分榜获取
        if team_name in standings:
            row = standings[team_name]
            played = row.get("played", 0)
            gf = row.get("goals_for", 0)
            ga = row.get("goals_against", 0)

            return {
                "team_name": team_name,
                "rank": row.get("rank", 0),
                "played": played,
                "wins": row.get("wins", 0),
                "draws": row.get("draws", 0),
                "losses": row.get("losses", 0),
                "goals_for": gf,
                "goals_against": ga,
                "goal_diff": gf - ga,
                "points": row.get("points", 0),
                "recent_form": row.get("form", "")[-5:],
                "xg": 0,  # API-Football标准版不含xG，后续可接其他源
                "xga": 0,
                "home_wins": 0,  # 需要额外请求
                "away_wins": 0,
                "team_id": row.get("team_id", 0),
            }

        # 积分榜没有，尝试本地数据库
        local = get_team_stats(team_name)
        if local:
            return local

        # 无数据
        return {
            "team_name": team_name,
            "rank": 0,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_diff": 0,
            "points": 0,
            "recent_form": "",
            "xg": 0,
            "xga": 0,
            "home_wins": 0,
            "away_wins": 0,
            "team_id": 0,
        }

    def _get_squad_info(self, fixture_id: int, side: str) -> dict:
        """获取伤停/阵容信息"""
        if not self.api_client or not fixture_id:
            return {
                "missing_players": [],
                "key_absences": [],
                "rotation_risk": "",
                "fatigue_days": 5,
            }

        try:
            injuries = self.api_client.get_injuries(fixture_id)
            side_injuries = injuries.get(side, [])

            missing = [inj["player"] for inj in side_injuries if inj.get("player")]
            # 简化: 超过3人缺阵视为关键
            key_absences = missing[:3] if len(missing) > 3 else []

            return {
                "missing_players": missing,
                "key_absences": key_absences,
                "rotation_risk": "高" if len(missing) > 4 else ("中" if len(missing) > 2 else "低"),
                "fatigue_days": 5,  # TODO: 从赛程密度计算
            }
        except Exception as e:
            log.warning(f"[球队数据] 伤停获取失败: {e}")
            return {
                "missing_players": [],
                "key_absences": [],
                "rotation_risk": "",
                "fatigue_days": 5,
            }

    def enrich_match_data(self, match: dict) -> dict:
        """
        为比赛补充完整数据（供模型使用）
        
        在原始match基础上添加:
        - home_stats, away_stats (实力模型用)
        - home_squad, away_squad (阵容模型用)
        """
        team_data = self.get_match_team_data(match)
        match.update(team_data)
        return match
