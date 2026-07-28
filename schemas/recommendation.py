"""推荐数据结构"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Recommendation:
    """一条推荐记录(保存当时完整快照，赛后不可篡改)"""
    match_id: str
    league: str
    home_team: str
    away_team: str
    kickoff: str

    # 推荐结论
    level: str                  # A / B / C
    direction: str              # home / away / draw / neutral
    crown_index: float
    confidence: float

    # 推荐时刻盘口快照(冻结)
    odds_handicap: str = ""
    odds_home_water: float = 0.0
    odds_away_water: float = 0.0
    odds_over_line: str = ""

    # 推荐时刻模型快照(冻结)
    model_version: str = ""
    model_weights: dict = field(default_factory=dict)  # {"strength": 0.25, ...}
    strength_score: float = 0.0
    handicap_score: float = 0.0
    squad_score: float = 0.0
    market_score: float = 0.0
    ai_score: float = 0.0
    ai_decision: str = ""       # approve / downgrade / reject
    data_completeness: float = 0.0

    # 推荐原因
    reason: str = ""

    # 时间戳
    recommended_at: datetime = field(default_factory=datetime.now)

    @property
    def is_actionable(self) -> bool:
        """是否可执行(A/B级才算)"""
        return self.level in ("A", "B")
