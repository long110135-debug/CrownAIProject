"""
皇冠AI赛事研判系统 - 市场模型 (权重20%)
判断市场资金行为：热度、诱热、资金流向
"""
from models.base_model import BaseModel
from utils.logger import log


class MarketModel(BaseModel):
    """市场行为模型"""

    name = "market"

    def analyze(self, match_data: dict) -> dict:
        """
        分析市场资金行为
        
        核心逻辑:
        - 热门队投注热度高但盘口不升 → 诱热风险
        - 冷门方水位持续下降 → 聪明钱流入
        - 盘口与热度背离 → 重要信号
        """
        odds = match_data.get("odds", {})
        market_data = match_data.get("market_data", {})

        if not odds:
            return self._no_data_result()

        # === 1. 热度分析 ===
        heat_analysis = self._analyze_heat(odds, market_data)

        # === 2. 诱热检测 ===
        trap_analysis = self._detect_trap(odds, market_data, match_data)

        # === 3. 资金流向 ===
        flow_analysis = self._analyze_flow(odds, market_data)

        # 综合评分
        score = (
            heat_analysis["score"] * 0.35 +
            trap_analysis["score"] * 0.35 +
            flow_analysis["score"] * 0.30
        )

        # 方向
        direction = self._determine_direction(heat_analysis, trap_analysis, flow_analysis)
        confidence = self._calc_confidence(score, trap_analysis)

        reasoning = self._build_reasoning(heat_analysis, trap_analysis, flow_analysis)

        return {
            "model": self.name,
            "score": round(score, 1),
            "direction": direction,
            "confidence": round(confidence, 1),
            "reasoning": reasoning,
            "details": {
                "heat": heat_analysis,
                "trap": trap_analysis,
                "flow": flow_analysis,
            },
        }

    def _analyze_heat(self, odds: dict, market_data: dict) -> dict:
        """
        热度分析
        判断哪方是市场热门
        """
        home_odds = odds.get("home_odds", 0.95)
        away_odds = odds.get("away_odds", 0.95)
        handicap = odds.get("current_handicap", odds.get("asian_handicap", ""))

        # 让球方通常是热门
        is_home_favorite = "主让" in str(handicap)
        heat_side = "home" if is_home_favorite else "away"

        # 热度指标 (如果有投注比例数据)
        heat_ratio = market_data.get("heat_ratio", {})  # {"home": 0.65, "away": 0.35}
        if heat_ratio:
            home_heat = heat_ratio.get("home", 0.5)
            if home_heat > 0.7:
                heat_level = "过热"
            elif home_heat > 0.55:
                heat_level = "偏热"
            else:
                heat_level = "正常"
        else:
            heat_level = "未知"

        # 评分: 热度越极端，风险越高(分数越低=越危险)
        if heat_level == "过热":
            score = 35  # 过热=高风险
        elif heat_level == "偏热":
            score = 55
        else:
            score = 65  # 正常热度

        return {
            "score": score,
            "heat_side": heat_side,
            "heat_level": heat_level,
            "is_home_favorite": is_home_favorite,
        }

    def _detect_trap(self, odds: dict, market_data: dict, match_data: dict) -> dict:
        """
        诱热检测
        
        诱热特征:
        1. 热门方投注热度高，但盘口不升甚至降
        2. 热门方水位偏高(给高水吸引投注)
        3. 临场突然升水(吸引最后一波资金)
        """
        change_type = odds.get("change_type", "不变")
        home_odds = odds.get("home_odds", 0.95)
        away_odds = odds.get("away_odds", 0.95)
        handicap = odds.get("current_handicap", "")

        trap_risk = 0
        trap_signals = []

        # 信号1: 热门方高水 (让球方水位>1.0)
        if "主让" in str(handicap) and home_odds > 1.0:
            trap_risk += 25
            trap_signals.append("主队让球但水位偏高(>1.0)")
        elif "客让" in str(handicap) and away_odds > 1.0:
            trap_risk += 25
            trap_signals.append("客队让球但水位偏高(>1.0)")

        # 信号2: 热度高但盘口不升
        heat_ratio = market_data.get("heat_ratio", {})
        if heat_ratio:
            fav_heat = max(heat_ratio.get("home", 0.5), heat_ratio.get("away", 0.5))
            if fav_heat > 0.65 and change_type != "升盘":
                trap_risk += 30
                trap_signals.append(f"热度{fav_heat:.0%}但盘口未升")

        # 信号3: 降盘(可能是诱热后降盘出货)
        if change_type == "降盘" and home_odds < 0.85:
            trap_risk += 20
            trap_signals.append("降盘+低水组合(可能诱热)")

        # 评分: 诱热风险越高分数越低
        score = self._clamp(80 - trap_risk, 10, 90)

        return {
            "score": score,
            "trap_risk": trap_risk,
            "trap_signals": trap_signals,
            "is_trap": trap_risk >= 40,
        }

    def _analyze_flow(self, odds: dict, market_data: dict) -> dict:
        """
        资金流向分析
        通过水位变化推断资金方向
        """
        home_odds = odds.get("home_odds", 0.95)
        away_odds = odds.get("away_odds", 0.95)

        # 低水方=资金流入方
        if home_odds < away_odds - 0.08:
            flow_direction = "home"
            flow_strength = min((away_odds - home_odds) * 100, 80)
        elif away_odds < home_odds - 0.08:
            flow_direction = "away"
            flow_strength = min((home_odds - away_odds) * 100, 80)
        else:
            flow_direction = "balanced"
            flow_strength = 20

        # 评分
        score = 50 + flow_strength * 0.3

        return {
            "score": self._clamp(score, 30, 85),
            "flow_direction": flow_direction,
            "flow_strength": round(flow_strength, 1),
        }

    def _determine_direction(self, heat, trap, flow) -> str:
        """综合判断市场方向"""
        # 如果检测到诱热，方向取反
        if trap.get("is_trap"):
            # 诱热方通常是热门方，反向操作
            heat_side = heat.get("heat_side", "home")
            return "away" if heat_side == "home" else "home"

        # 否则跟随资金流向
        flow_dir = flow.get("flow_direction", "balanced")
        if flow_dir != "balanced":
            return flow_dir

        return "neutral"

    def _calc_confidence(self, score, trap) -> float:
        """计算可信度"""
        base = score * 0.6
        if trap.get("is_trap"):
            base += 15  # 诱热信号明确时加分
        return self._clamp(base, 20, 85)

    def _build_reasoning(self, heat, trap, flow) -> str:
        """生成推理说明"""
        parts = []

        if trap.get("is_trap"):
            signals = trap.get("trap_signals", [])
            parts.append(f"⚠️诱热风险: {'; '.join(signals[:2])}")
        else:
            parts.append(f"热度: {heat.get('heat_level', '未知')}")

        flow_dir = flow.get("flow_direction", "balanced")
        if flow_dir == "home":
            parts.append("资金流向主队")
        elif flow_dir == "away":
            parts.append("资金流向客队")
        else:
            parts.append("资金流向均衡")

        return "，".join(parts)

    def _no_data_result(self) -> dict:
        return {
            "model": self.name,
            "score": 0,
            "direction": "neutral",
            "confidence": 0,
            "reasoning": "无市场数据",
            "details": {"no_data": True},
        }
