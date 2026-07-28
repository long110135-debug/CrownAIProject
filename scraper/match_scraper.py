"""
皇冠AI赛事研判系统 - 比赛赛程抓取器
从公开数据源获取今日比赛列表
"""
import re
import json
from datetime import datetime, timedelta
from typing import List, Optional
from scraper.base_scraper import BaseScraper
from utils.logger import log
from config.leagues import is_allowed_league, should_filter, get_league_tier


class MatchScraper(BaseScraper):
    """比赛赛程抓取器"""

    def __init__(self, config: dict = None):
        super().__init__(config)

    def fetch_today_matches(self, source_url: str = None) -> List[dict]:
        """
        获取今日比赛列表
        
        返回格式:
        [
            {
                "match_id": "20260720_EPL_001",
                "league": "英超",
                "league_tier": 1,
                "home_team": "曼城",
                "away_team": "利物浦",
                "match_time": "2026-07-20 22:00",
                "status": "pending",
            },
            ...
        ]
        """
        if not source_url:
            log.warning("未配置赛程数据源，使用示例数据")
            return self._get_sample_matches()

        html = self.fetch(source_url)
        if not html:
            return []

        matches = self._parse_match_list(html)
        # 过滤
        filtered = self._filter_matches(matches)
        log.info(f"赛程抓取: 共{len(matches)}场, 过滤后{len(filtered)}场")
        return filtered

    def _parse_match_list(self, html: str) -> List[dict]:
        """解析比赛列表页面"""
        soup = self.parse_html(html)
        if not soup:
            return []

        matches = []
        today = datetime.now().strftime("%Y-%m-%d")

        # === 通用解析模板，需根据实际网站结构调整 ===

        # 模式1: JSON数据
        json_match = re.search(r'matchList\s*=\s*(\[.*?\]);', html, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(1))
                for item in data:
                    match = {
                        "match_id": item.get("id", f"{today}_{len(matches)+1}"),
                        "league": item.get("league", item.get("ln", "")),
                        "home_team": item.get("home", item.get("hn", "")),
                        "away_team": item.get("away", item.get("an", "")),
                        "match_time": item.get("time", f"{today} 20:00"),
                        "status": "pending",
                    }
                    matches.append(match)
                return matches
            except json.JSONDecodeError:
                pass

        # 模式2: 表格/列表
        rows = soup.find_all(["tr", "div"], class_=re.compile(r"match|game|event"))
        for i, row in enumerate(rows):
            text = row.get_text(strip=True)
            # 尝试提取 "联赛 主队 vs 客队 时间" 格式
            vs_match = re.search(r'(.+?)\s*(?:vs|VS|v)\s*(.+)', text)
            if vs_match:
                home = vs_match.group(1).strip()
                away = vs_match.group(2).strip()
                # 清理时间等后缀
                away = re.sub(r'\d{2}:\d{2}.*$', '', away).strip()
                match = {
                    "match_id": f"{today}_{i+1:03d}",
                    "league": self._detect_league(text),
                    "home_team": home,
                    "away_team": away,
                    "match_time": f"{today} 20:00",
                    "status": "pending",
                }
                matches.append(match)

        return matches

    def _detect_league(self, text: str) -> str:
        """从文本中识别联赛名称"""
        from config.leagues import get_all_leagues
        all_leagues = get_all_leagues()
        for name in all_leagues:
            if name in text:
                return name
        return "未知"

    def _filter_matches(self, matches: List[dict]) -> List[dict]:
        """过滤比赛：只保留允许联赛，排除青年队/友谊赛等"""
        filtered = []
        for match in matches:
            # 联赛过滤
            if not is_allowed_league(match.get("league", "")):
                continue
            # 关键词过滤
            if should_filter(match):
                continue
            # 添加联赛等级
            match["league_tier"] = get_league_tier(match["league"])
            filtered.append(match)
        return filtered

    def _get_sample_matches(self) -> List[dict]:
        """示例比赛数据（开发/测试用）"""
        today = datetime.now().strftime("%Y-%m-%d")
        return [
            {
                "match_id": f"{today}_EPL_001",
                "league": "英超",
                "league_tier": 1,
                "home_team": "曼城",
                "away_team": "阿森纳",
                "match_time": f"{today} 22:00",
                "status": "pending",
            },
            {
                "match_id": f"{today}_LaLiga_001",
                "league": "西甲",
                "league_tier": 1,
                "home_team": "巴塞罗那",
                "away_team": "皇家马德里",
                "match_time": f"{today} 23:00",
                "status": "pending",
            },
            {
                "match_id": f"{today}_SerieA_001",
                "league": "意甲",
                "league_tier": 1,
                "home_team": "国际米兰",
                "away_team": "AC米兰",
                "match_time": f"{today} 21:45",
                "status": "pending",
            },
            {
                "match_id": f"{today}_Bundesliga_001",
                "league": "德甲",
                "league_tier": 1,
                "home_team": "拜仁慕尼黑",
                "away_team": "多特蒙德",
                "match_time": f"{today} 21:30",
                "status": "pending",
            },
            {
                "match_id": f"{today}_Ligue1_001",
                "league": "法甲",
                "league_tier": 1,
                "home_team": "巴黎圣日耳曼",
                "away_team": "马赛",
                "match_time": f"{today} 21:00",
                "status": "pending",
            },
            {
                "match_id": f"{today}_UCL_001",
                "league": "欧冠",
                "league_tier": 1,
                "home_team": "利物浦",
                "away_team": "尤文图斯",
                "match_time": f"{today} 03:00",
                "status": "pending",
            },
        ]
