"""结算数据结构"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Settlement:
    """一场比赛的结算记录"""
    match_id: str
    league: str
    home_team: str
    away_team: str

    # 赛果
    home_score: int = 0
    away_score: int = 0
    winner: str = ""            # home / away / draw

    # 让球结算
    handicap_line: str = ""     # 推荐时的盘口
    handicap_result: str = ""   # home_cover / away_cover / push
    cover: Optional[int] = None  # 1=赢盘 0=输盘 None=走盘/无盘口

    # 命中判定
    recommended_direction: str = ""
    hit: int = -1               # 1=命中 0=未命中 2=未推荐(不计)

    # CLV(推荐时盘口 vs 收盘盘口)
    clv_handicap: Optional[float] = None
    clv_water: Optional[float] = None
    closing_handicap: str = ""
    closing_home_water: float = 0.0

    # 推荐等级(复盘用)
    level: str = ""
    crown_index: float = 0.0

    # 错因
    error_reason: str = ""

    settled_at: datetime = field(default_factory=datetime.now)

    @property
    def score_str(self) -> str:
        return f"{self.home_score}-{self.away_score}"

    @property
    def is_profitable(self) -> bool:
        """是否盈利(赢盘)"""
        return self.cover == 1
