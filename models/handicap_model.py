"""
皇冠AI赛事研判系统 - 盘口模型 (权重30%，核心)
分析皇冠初盘、即时盘、水位、热度，判断盘口方向
"""
import re
from models.base_model import BaseModel
from utils.logger import log


class HandicapModel(BaseModel):
    """盘口分析模型 - 系统核心"""

    name = "handicap"

    def analyze(self, match_data: dict) -> dict:
        """
        分析盘口数据
        
        输入match_data需包含:
        - odds: {asian_handicap, home_odds, away_odds, open_handicap, 
                 current_handicap, change_type, over_under, over_odds, under_odds}
        - odds_history: [多次快照] (可选)
        """
        odds = match_data.get("odds", {})
        if not odds:
            return self._no_data_result()

        # === 1. 盘口变化分析 (40分) ===
        change_score = self._analyze_change(odds)

        # === 2. 水位分析 (30分) ===
        water_score = self._analyze_water(odds)

        # === 3. 盘口合理性 (20分) ===
        reasonability_score = self._analyze_reasonability(odds, match_data)

        # === 4. 大小球辅助 (10分) ===
        ou_score = self._analyze_over_under(odds)

        # 综合评分
        total_score = (
            change_score * 0.40 +
            water_score * 0.30 +
            reasonability_score * 0.20 +
            ou_score * 0.10
        )

        # 方向判断
        direction = self._determine_direction(odds, change_score, water_score)
        confidence = self._calc_confidence(total_score, odds)

        reasoning = self._build_reasoning(odds, change_score, water_score, direction)

        return {
            "model": self.name,
            "score": round(total_score, 1),
            "direction": direction,
            "confidence": round(confidence, 1),
            "reasoning": reasoning,
            "details": {
                "change_score": round(change_score, 1),
                "water_score": round(water_score, 1),
                "reasonability_score": round(reasonability_score, 1),
                "ou_score": round(ou_score, 1),
                "open_handicap": odds.get("open_handicap", ""),
                "current_handicap": odds.get("current_handicap", ""),
                "change_type": odds.get("change_type", ""),
                "home_odds": odds.get("home_odds", 0),
                "away_odds": odds.get("away_odds", 0),
            },
        }

    def _analyze_change(self, odds: dict) -> float:
        """
        盘口变化分析 (0-100)
        升盘=市场增强主队信心，降盘=反向
        """
        change_type = odds.get("change_type", "不变")
        open_hdp = odds.get("open_handicap", "")
        current_hdp = odds.get("current_handicap", "")

        if change_type == "升盘":
            # 升盘幅度越大，信号越强
            diff = self._handicap_diff(open_hdp, current_hdp)
            if diff >= 0.5:
                return 90  # 大幅升盘，强信号
            elif diff >= 0.25:
                return 75  # 正常升盘
            else:
                return 65  # 小幅升盘
        elif change_type == "降盘":
            diff = abs(self._handicap_diff(open_hdp, current_hdp))
            if diff >= 0.5:
                return 85  # 大幅降盘，客队强信号
            elif diff >= 0.25:
                return 70
            else:
                return 60
        else:
            # 不变 - 中性偏稳定
            return 50

    def _analyze_water(self, odds: dict) -> float:
        """
        水位分析 (0-100)
        低水方=资金流入方=市场看好方
        """
        home_odds = odds.get("home_odds", 0.95)
        away_odds = odds.get("away_odds", 0.95)

        if not home_odds or not away_odds:
            return 50

        # 水位差 (正值=主队低水=看好主队)
        water_diff = away_odds - home_odds

        if water_diff > 0.15:
            return 85  # 主队明显低水
        elif water_diff > 0.08:
            return 72  # 主队略低水
        elif water_diff < -0.15:
            return 80  # 客队明显低水(反向信号)
        elif water_diff < -0.08:
            return 68  # 客队略低水
        else:
            return 50  # 水位均衡

    def _analyze_reasonability(self, odds: dict, match_data: dict) -> float:
        """
        盘口合理性分析 (0-100)
        盘口是否与实力匹配，异常盘口=重要信号
        """
        # 如果有实力模型的结果，可以交叉验证
        strength_direction = match_data.get("strength_direction", "neutral")
        handicap_value = self._handicap_to_number(
            odds.get("current_handicap", odds.get("asian_handicap", ""))
        )

        # 默认合理
        score = 60

        # 盘口方向与实力方向一致 → 合理
        if strength_direction == "home" and handicap_value > 0:
            score = 75
        elif strength_direction == "away" and handicap_value < 0:
            score = 75
        elif strength_direction == "home" and handicap_value <= 0:
            # 实力看好主队但盘口不让球 → 异常（可能诱盘）
            score = 40
        elif strength_direction == "away" and handicap_value >= 0.5:
            # 实力看好客队但主队深让 → 异常
            score = 35

        return score

    def _analyze_over_under(self, odds: dict) -> float:
        """大小球辅助分析"""
        ou = odds.get("over_under", "")
        over_odds = odds.get("over_odds", 0)
        under_odds = odds.get("under_odds", 0)

        if not ou or not over_odds:
            return 50

        # 大小球水位可以辅助判断比赛节奏预期
        if over_odds < under_odds - 0.1:
            return 65  # 看好大球=进攻型比赛
        elif under_odds < over_odds - 0.1:
            return 60  # 看好小球=防守型比赛
        return 50

    def _determine_direction(self, odds: dict, change_score: float, water_score: float) -> str:
        """综合判断盘口方向"""
        change_type = odds.get("change_type", "不变")
        home_odds = odds.get("home_odds", 0.95)
        away_odds = odds.get("away_odds", 0.95)

        # 盘口变化方向
        if change_type == "升盘":
            change_dir = "home"
        elif change_type == "降盘":
            change_dir = "away"
        else:
            change_dir = "neutral"

        # 水位方向
        if home_odds < away_odds - 0.05:
            water_dir = "home"
        elif away_odds < home_odds - 0.05:
            water_dir = "away"
        else:
            water_dir = "neutral"

        # 综合
        if change_dir == water_dir and change_dir != "neutral":
            return change_dir  # 盘口+水位一致，强信号
        elif change_dir != "neutral":
            return change_dir  # 以盘口变化为主
        elif water_dir != "neutral":
            return water_dir
        else:
            return "neutral"

    def _calc_confidence(self, score: float, odds: dict) -> float:
        """计算可信度"""
        base = score * 0.7
        # 盘口变化明确加分
        if odds.get("change_type") in ("升盘", "降盘"):
            base += 10
        # 水位差明显加分
        diff = abs(odds.get("away_odds", 0.95) - odds.get("home_odds", 0.95))
        if diff > 0.1:
            base += 8
        return self._clamp(base, 20, 95)

    def _build_reasoning(self, odds, change_score, water_score, direction) -> str:
        """生成推理说明"""
        parts = []
        change = odds.get("change_type", "不变")
        open_h = odds.get("open_handicap", "?")
        curr_h = odds.get("current_handicap", "?")
        parts.append(f"盘口: {open_h}→{curr_h}({change})")
        parts.append(f"水位: 主{odds.get('home_odds', '?')}/客{odds.get('away_odds', '?')}")

        if direction == "home":
            parts.append("盘口信号指向主队")
        elif direction == "away":
            parts.append("盘口信号指向客队")
        else:
            parts.append("盘口信号中性")

        return "，".join(parts)

    def _handicap_diff(self, open_hdp: str, current_hdp: str) -> float:
        """计算盘口变化幅度(委托odds_math)"""
        from utils.odds_math import handicap_to_number
        return handicap_to_number(current_hdp) - handicap_to_number(open_hdp)

    def _handicap_to_number(self, handicap_str: str) -> float:
        """盘口文字转数值(委托odds_math唯一实现)"""
        from utils.odds_math import handicap_to_number
        return handicap_to_number(handicap_str)

    def _no_data_result(self) -> dict:
        """无盘口数据"""
        return {
            "model": self.name,
            "score": 0,
            "direction": "neutral",
            "confidence": 0,
            "reasoning": "无盘口数据",
            "details": {"no_data": True},
        }
