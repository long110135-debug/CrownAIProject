"""比赛数据结构"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Match:
    """一场比赛的完整标识"""
    match_id: str               # 唯一ID: CROWN_{league}_{home}_{away}_{date}
    league: str                 # 系统短名: 瑞超/英超/西甲
    home_team: str              # 主队(中文)
    away_team: str              # 客队(中文)
    kickoff: datetime           # 开赛时间
    status: str = "pending"     # pending / finished / cancelled / postponed
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    source: str = "api-football"  # 数据来源
    source_fixture_id: Optional[int] = None  # API-Football fixture ID
    created_at: datetime = field(default_factory=datetime.now)

    @property
    def winner(self) -> Optional[str]:
        if self.home_score is None or self.away_score is None:
            return None
        if self.home_score > self.away_score:
            return "home"
        elif self.home_score < self.away_score:
            return "away"
        return "draw"

    @property
    def score_str(self) -> str:
        if self.home_score is None:
            return ""
        return f"{self.home_score}-{self.away_score}"
