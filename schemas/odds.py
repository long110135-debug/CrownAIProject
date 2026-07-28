"""盘口数据结构"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class OddsSnapshot:
    """一次盘口抓取快照(追加写入，不覆盖)"""
    match_id: str
    company: str                # 数据来源: crown_daemon / api-football(Bet365)
    handicap: str               # 盘口文字: "主让0.5" / "客让1" / "平手"
    handicap_value: float       # 盘口数值: 0.5 / -1.0 / 0
    home_odds: float            # 主队水位
    away_odds: float            # 客队水位
    over_line: str = ""         # 大小球线: "2.5"
    over_odds: float = 0.0
    under_odds: float = 0.0
    home_win: float = 0.0       # 独赢赔率(可选)
    draw: float = 0.0
    away_win: float = 0.0
    captured_at: datetime = field(default_factory=datetime.now)
    phase: str = "early"        # opening / early / prematch / closing

    @property
    def is_valid(self) -> bool:
        """盘口数据是否有效(非空)"""
        return bool(self.handicap) and self.home_odds > 0 and self.away_odds > 0


@dataclass
class OddsTimeline:
    """一场比赛的盘口时间序列"""
    match_id: str
    snapshots: list = field(default_factory=list)  # List[OddsSnapshot]

    @property
    def opening(self) -> Optional[OddsSnapshot]:
        """初盘(第一条记录)"""
        return self.snapshots[0] if self.snapshots else None

    @property
    def closing(self) -> Optional[OddsSnapshot]:
        """收盘(最后一条closing标记，或最后一条记录)"""
        for s in reversed(self.snapshots):
            if s.phase == "closing":
                return s
        return self.snapshots[-1] if self.snapshots else None

    @property
    def latest(self) -> Optional[OddsSnapshot]:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def count(self) -> int:
        return len(self.snapshots)
