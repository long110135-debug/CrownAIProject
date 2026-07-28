"""
皇冠AI赛事研判系统 - 阵容模型 (权重15%)
分析伤停、主力缺席、轮换风险、赛程密度
"""
from models.base_model import BaseModel
from utils.logger import log


class SquadModel(BaseModel):
    """阵容/伤停模型"""

    name = "squad"

    def analyze(self, match_data: dict) -> dict:
        """
        分析阵容影响
        
        输入match_data可包含:
        - home_squad: {missing_players, key_absences, rotation_risk, fatigue_days}
        - away_squad: 同上
        """
        home_squad = match_data.get("home_squad", {})
        away_squad = match_data.get("away_squad", {})

        # 计算双方阵容完整度
        home_integrity = self._calc_integrity(home_squad)
        away_integrity = self._calc_integrity(away_squad)

        # 阵容差 (正值=主队阵容更完整)
        integrity_diff = home_integrity - away_integrity

        # 评分
        score = self._clamp(50 + integrity_diff * 2)

        # 方向
        if integrity_diff > 10:
            direction = "home"
            confidence = min(50 + integrity_diff, 80)
        elif integrity_diff < -10:
            direction = "away"
            confidence = min(50 + abs(integrity_diff), 80)
        else:
            direction = "neutral"
            confidence = 35

        reasoning = self._build_reasoning(
            match_data.get("home_team", ""),
            match_data.get("away_team", ""),
            home_squad, away_squad, integrity_diff
        )

        return {
            "model": self.name,
            "score": round(score, 1),
            "direction": direction,
            "confidence": round(confidence, 1),
            "reasoning": reasoning,
            "details": {
                "home_integrity": round(home_integrity, 1),
                "away_integrity": round(away_integrity, 1),
                "home_missing": home_squad.get("missing_players", []),
                "away_missing": away_squad.get("missing_players", []),
                "home_fatigue": home_squad.get("fatigue_days", 0),
                "away_fatigue": away_squad.get("fatigue_days", 0),
            },
        }

    def _calc_integrity(self, squad: dict) -> float:
        """
        计算阵容完整度 (0-50)
        50=完全健康，越低越差
        """
        if not squad:
            return 40  # 无数据时给中等偏下

        integrity = 50.0

        # 缺阵球员扣分
        missing = squad.get("missing_players", [])
        if isinstance(missing, list):
            integrity -= len(missing) * 3
        elif isinstance(missing, int):
            integrity -= missing * 3

        # 关键球员缺席 (重大扣分)
        key_absences = squad.get("key_absences", [])
        if isinstance(key_absences, list):
            integrity -= len(key_absences) * 6
        elif isinstance(key_absences, int):
            integrity -= key_absences * 6

        # 轮换风险
        rotation = squad.get("rotation_risk", "")
        if rotation in ("高", "high"):
            integrity -= 8
        elif rotation in ("中", "medium"):
            integrity -= 4

        # 赛程密度 (休息天数)
        fatigue_days = squad.get("fatigue_days", 5)
        if fatigue_days <= 2:
            integrity -= 6  # 极度疲劳
        elif fatigue_days <= 3:
            integrity -= 3  # 较疲劳

        return self._clamp(integrity, 0, 50)

    def _build_reasoning(self, home, away, home_squad, away_squad, diff) -> str:
        """生成推理说明"""
        parts = []

        home_missing = home_squad.get("missing_players", [])
        away_missing = away_squad.get("missing_players", [])

        if home_missing:
            count = len(home_missing) if isinstance(home_missing, list) else home_missing
            parts.append(f"{home}缺阵{count}人")
        if away_missing:
            count = len(away_missing) if isinstance(away_missing, list) else away_missing
            parts.append(f"{away}缺阵{count}人")

        if diff > 10:
            parts.append("主队阵容明显更完整")
        elif diff < -10:
            parts.append("客队阵容明显更完整")
        elif not parts:
            parts.append("双方阵容信息暂无，影响中性")

        return "，".join(parts) if parts else "阵容数据暂无"
