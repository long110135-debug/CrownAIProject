"""
皇冠AI赛事研判系统 - 实力模型 (权重25%)
基于联赛排名、xG、进失球、主客场、近期状态计算实力差

输入规范: match_data必须包含home_stats/away_stats(由调用方预取注入)
模型自身不访问数据库。
"""
from models.base_model import BaseModel
from utils.logger import log


class StrengthModel(BaseModel):
    """球队实力模型"""

    name = "strength"

    def analyze(self, match_data: dict) -> dict:
        """
        计算双方实力对比
        
        输入match_data需包含:
        - home_team, away_team, league
        - home_stats: {rank, played, wins, draws, losses, goals_for, goals_against, xg, xga, home_wins, away_wins, recent_form}
        - away_stats: 同上
        """
        home = match_data.get("home_team", "")
        away = match_data.get("away_team", "")

        # 只使用调用方注入的数据，不自己访问DB
        home_stats = match_data.get("home_stats")
        away_stats = match_data.get("away_stats")

        if not home_stats or not away_stats:
            log.info(f"[实力模型] 数据不足: {home} vs {away}，使用默认评估")
            return self._default_result(home, away)

        # === 计算实力分 ===
        home_power = self._calc_power(home_stats, is_home=True)
        away_power = self._calc_power(away_stats, is_home=False)

        # 实力差 (正值=主队强)
        power_diff = home_power - away_power

        # 转为0-100评分 (50为均势)
        score = self._clamp(50 + power_diff * 2)

        # 方向判断
        if power_diff > 8:
            direction = "home"
            confidence = min(50 + power_diff, 90)
        elif power_diff < -8:
            direction = "away"
            confidence = min(50 + abs(power_diff), 90)
        else:
            direction = "draw"
            confidence = 40

        reasoning = self._build_reasoning(home, away, home_stats, away_stats, power_diff)

        return {
            "model": self.name,
            "score": round(score, 1),
            "direction": direction,
            "confidence": round(confidence, 1),
            "reasoning": reasoning,
            "details": {
                "home_power": round(home_power, 1),
                "away_power": round(away_power, 1),
                "power_diff": round(power_diff, 1),
                "home_rank": home_stats.get("rank"),
                "away_rank": away_stats.get("rank"),
            },
        }

    def _calc_power(self, stats: dict, is_home: bool) -> float:
        """
        计算球队实力值 (0-50范围)
        
        维度:
        - 排名 (权重30%)
        - 进失球差 (权重25%)
        - xG差 (权重20%)
        - 主/客场胜率 (权重15%)
        - 近期状态 (权重10%)
        """
        power = 25.0  # 基准值

        # 排名加成 (排名越高加分越多)
        rank = stats.get("rank", 10)
        played = stats.get("played", 1)
        if rank and played:
            # 排名越靠前，加分越多 (第1名+10, 第20名-5)
            rank_bonus = (10 - rank * 0.75)
            power += rank_bonus * 0.30

        # 进失球差
        gf = stats.get("goals_for", 0)
        ga = stats.get("goals_against", 0)
        if played > 0:
            goal_diff_per_game = (gf - ga) / played
            power += goal_diff_per_game * 3 * 0.25

        # xG差
        xg = stats.get("xg", 0)
        xga = stats.get("xga", 0)
        if xg and xga:
            xg_diff = xg - xga
            power += xg_diff * 2 * 0.20

        # 主客场胜率
        if is_home:
            wins = stats.get("home_wins", stats.get("wins", 0))
        else:
            wins = stats.get("away_wins", stats.get("wins", 0))
        if played > 0:
            win_rate = wins / max(played / 2, 1)
            power += (win_rate - 0.4) * 10 * 0.15

        # 近期状态 (最近5场)
        form = stats.get("recent_form", "")
        if form:
            form_score = self._parse_form(form)
            power += form_score * 0.10

        return self._clamp(power, 0, 50)

    def _parse_form(self, form: str) -> float:
        """解析近期状态 WWDWL → 分数"""
        score = 0
        for ch in form.upper()[:5]:
            if ch == "W":
                score += 2
            elif ch == "D":
                score += 0.5
            elif ch == "L":
                score -= 1
        return score  # 范围约 -5 到 +10

    def _build_reasoning(self, home, away, home_stats, away_stats, diff) -> str:
        """生成推理说明"""
        parts = []
        home_rank = home_stats.get("rank", "?")
        away_rank = away_stats.get("rank", "?")
        parts.append(f"{home}(排名第{home_rank}) vs {away}(排名第{away_rank})")

        if diff > 5:
            parts.append(f"主队实力明显占优(+{diff:.1f})")
        elif diff < -5:
            parts.append(f"客队实力明显占优({diff:.1f})")
        else:
            parts.append("双方实力接近")

        return "，".join(parts)

    def _default_result(self, home, away) -> dict:
        """数据不足时的默认结果"""
        return {
            "model": self.name,
            "score": 50.0,
            "direction": "neutral",
            "confidence": 20,
            "reasoning": f"{home} vs {away}: 球队数据不足，无法评估实力差",
            "details": {"data_missing": True},
        }
