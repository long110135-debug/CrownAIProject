"""模型结果数据结构"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModelResult:
    """单个模型的输出(统一格式)"""
    model: str                  # strength / handicap / squad / market / ai_referee
    score: float                # 0-100
    direction: str              # home / away / draw / neutral
    confidence: float           # 0-100
    reasoning: str = ""
    details: dict = field(default_factory=dict)

    @property
    def has_direction(self) -> bool:
        return self.direction != "neutral"


@dataclass
class AnalysisResult:
    """一场比赛的完整分析结果(五模型+皇冠指数)"""
    match_id: str
    home_team: str
    away_team: str
    league: str
    match_time: str
    model_version: str
    crown_index: float
    crown_rating: str
    data_completeness: float

    # 五模型结果
    strength: Optional[ModelResult] = None
    handicap: Optional[ModelResult] = None
    squad: Optional[ModelResult] = None
    market: Optional[ModelResult] = None
    ai_referee: Optional[ModelResult] = None

    # 当时盘口快照(推荐时刻冻结)
    odds_handicap: str = ""
    odds_home_water: float = 0.0
    odds_away_water: float = 0.0

    # 模型权重快照(推荐时刻冻结)
    model_weights: dict = field(default_factory=dict)

    analysis_time: str = ""

    @property
    def model_results(self) -> dict:
        """兼容旧接口"""
        results = {}
        for name in ("strength", "handicap", "squad", "market", "ai_referee"):
            r = getattr(self, name, None)
            if r:
                results[name] = {
                    "model": r.model, "score": r.score,
                    "direction": r.direction, "confidence": r.confidence,
                    "reasoning": r.reasoning, "details": r.details,
                }
        return results

    @property
    def consensus_direction(self) -> str:
        """多数票方向"""
        from collections import Counter
        dirs = []
        for name in ("strength", "handicap", "squad", "market"):
            r = getattr(self, name, None)
            if r and r.has_direction:
                dirs.append(r.direction)
        if not dirs:
            return "neutral"
        return Counter(dirs).most_common(1)[0][0]
