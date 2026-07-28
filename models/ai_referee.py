"""
皇冠AI赛事研判系统 - AI裁判模型 (权重10%)

职责: 纯裁决，不重复分析。
输入: 四个模型的结构化结果 + 数据质量 + 冲突标记
输出: approve / downgrade / reject + 原因

禁止:
- 自己判断球队实力
- 自己生成方向
- 自己访问原始数据
- 自己修改盘口方向
- 自己绕过过滤层
"""
import json
import os
from typing import Optional
from models.base_model import BaseModel
from utils.logger import log


class AIRefereeModel(BaseModel):
    """AI裁判 - 纯裁决，不重复分析"""

    name = "ai_referee"

    def __init__(self, ai_config: dict = None):
        self.ai_config = ai_config or {
            "provider": "qwen",
            "model": "qwen-max",
            "temperature": 0.3,
            "max_tokens": 500,
        }

    def analyze(self, match_data: dict) -> dict:
        """
        裁决输入(结构化，不含原始数据):
        - model_results: {strength, handicap, squad, market} 各含 score/direction/confidence
        - data_quality: 数据完整度分数
        - odds: 仅用于检测盘口与方向是否矛盾

        裁决输出:
        - decision: approve / downgrade / reject
        - score: 裁决置信分(0-100)
        - direction: 继承多数模型方向(不自己生成)
        - confidence: 裁决后的置信度
        - reasoning: 裁决原因
        """
        model_results = match_data.get("model_results", {})
        if not model_results:
            return self._result("reject", 0, "neutral", 0, "无模型结果可裁决")

        # 提取结构化输入
        inputs = self._extract_inputs(model_results, match_data)

        # 本地规则裁决
        decision, score, reasons = self._local_arbitrate(inputs)

        # 尝试AI增强裁决(可选)
        ai_decision = self._call_ai_arbitrate(inputs)
        if ai_decision:
            decision = ai_decision.get("decision", decision)
            score = ai_decision.get("score", score)
            reasons = [ai_decision.get("reason", "")] + reasons

        # 方向: 继承多数模型，不自己生成
        direction = inputs["consensus_direction"]
        confidence = self._calc_confidence(inputs, decision, score)

        reasoning = f"AI裁判[{decision}]: " + "; ".join(reasons[:3]) if reasons else f"AI裁判[{decision}]: 无异常"

        return self._result(decision, score, direction, confidence, reasoning, inputs)

    def _extract_inputs(self, model_results: dict, match_data: dict) -> dict:
        """从模型结果提取结构化裁决输入"""
        scores = {}
        directions = {}
        confidences = {}

        for name in ("strength", "handicap", "squad", "market"):
            r = model_results.get(name, {})
            if isinstance(r, dict):
                scores[name] = r.get("score", 0)
                directions[name] = r.get("direction", "neutral")
                confidences[name] = r.get("confidence", 0)

        # 共识方向(多数票)
        from collections import Counter
        valid_dirs = [d for d in directions.values() if d != "neutral"]
        if valid_dirs:
            consensus = Counter(valid_dirs).most_common(1)[0][0]
            consensus_count = Counter(valid_dirs).most_common(1)[0][1]
        else:
            consensus = "neutral"
            consensus_count = 0

        # 冲突检测
        conflicts = []
        home_votes = sum(1 for d in directions.values() if d == "home")
        away_votes = sum(1 for d in directions.values() if d == "away")
        if home_votes >= 1 and away_votes >= 1:
            conflicts.append(f"方向冲突: {home_votes}票home vs {away_votes}票away")

        # 实力vs盘口背离
        if directions.get("strength") != "neutral" and directions.get("handicap") != "neutral":
            if directions["strength"] != directions["handicap"]:
                conflicts.append(f"实力({directions['strength']})与盘口({directions['handicap']})背离")

        # 风险标记
        risk_flags = []
        market_r = model_results.get("market", {})
        if isinstance(market_r, dict):
            trap = market_r.get("details", {}).get("trap", {})
            if trap.get("is_trap"):
                risk_flags.append("诱热风险")

        # 低信心标记
        for name, conf in confidences.items():
            if conf < 25:
                risk_flags.append(f"{name}信心过低({conf}%)")

        # 数据质量
        data_quality = match_data.get("data_completeness", 0) or match_data.get("_data_quality", 0)

        return {
            "scores": scores,
            "directions": directions,
            "confidences": confidences,
            "consensus_direction": consensus,
            "consensus_count": consensus_count,
            "total_models": len([d for d in directions.values() if d != "neutral"]),
            "conflicts": conflicts,
            "risk_flags": risk_flags,
            "data_quality": data_quality,
        }

    def _local_arbitrate(self, inputs: dict) -> tuple:
        """
        本地规则裁决
        返回: (decision, score, reasons)
        """
        reasons = []
        score = 70  # 基准

        conflicts = inputs["conflicts"]
        risk_flags = inputs["risk_flags"]
        consensus_count = inputs["consensus_count"]
        total = inputs["total_models"]

        # 规则1: 严重冲突 → reject
        if len(conflicts) >= 2:
            score -= 30
            reasons.extend(conflicts)

        # 规则2: 诱热风险 → downgrade
        if "诱热风险" in risk_flags:
            score -= 20
            reasons.append("市场检测到诱热")

        # 规则3: 模型一致性
        if total > 0:
            agreement = consensus_count / 4  # 4个方向模型
            if agreement >= 0.75:
                score += 10
            elif agreement < 0.5:
                score -= 15
                reasons.append(f"模型一致性低({consensus_count}/4)")

        # 规则4: 数据质量过低 → downgrade
        if inputs["data_quality"] < 50:
            score -= 15
            reasons.append(f"数据质量{inputs['data_quality']:.0f}%")

        # 规则5: 多模型低信心
        low_conf_count = sum(1 for c in inputs["confidences"].values() if c < 30)
        if low_conf_count >= 3:
            score -= 15
            reasons.append(f"{low_conf_count}个模型信心<30%")

        # 裁决
        score = max(0, min(100, score))
        if score >= 65:
            decision = "approve"
        elif score >= 40:
            decision = "downgrade"
        else:
            decision = "reject"

        if not reasons:
            reasons.append("模型结论一致，无异常")

        return decision, score, reasons

    def _calc_confidence(self, inputs: dict, decision: str, score: float) -> float:
        """计算裁决后置信度"""
        if decision == "reject":
            return min(score, 30)
        elif decision == "downgrade":
            return min(score, 55)
        else:
            return score

    def _call_ai_arbitrate(self, inputs: dict) -> Optional[dict]:
        """调用AI增强裁决(可选，不可用时跳过)"""
        api_key = os.environ.get("DASHSCOPE_API_KEY", "")
        if not api_key:
            return None

        try:
            import requests
            prompt = self._build_arbitrate_prompt(inputs)
            resp = requests.post(
                "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.ai_config.get("model", "qwen-max"),
                    "messages": [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 300,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return self._parse_response(content)
        except Exception as e:
            log.warning(f"[AI裁判] AI调用失败: {e}")
        return None

    def _system_prompt(self) -> str:
        return """你是盘口分析系统的AI裁判。你只做裁决，不做预测。
输入是四个模型的结构化结果。你只判断这些结论是否可信。
输出严格JSON: {"decision": "approve/downgrade/reject", "score": 0-100, "reason": "一句话"}
禁止: 自己判断比赛方向、自己分析球队实力、自己修改盘口。"""

    def _build_arbitrate_prompt(self, inputs: dict) -> str:
        return f"""四模型评分: {inputs['scores']}
四模型方向: {inputs['directions']}
共识方向: {inputs['consensus_direction']} ({inputs['consensus_count']}/4票)
冲突: {inputs['conflicts']}
风险: {inputs['risk_flags']}
数据质量: {inputs['data_quality']}%

请裁决: approve(可信) / downgrade(降级观察) / reject(不可信)"""

    def _parse_response(self, content: str) -> Optional[dict]:
        import re
        try:
            m = re.search(r'\{[^{}]*\}', content, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                decision = data.get("decision", "approve")
                if decision not in ("approve", "downgrade", "reject"):
                    decision = "approve"
                return {
                    "decision": decision,
                    "score": float(data.get("score", 60)),
                    "reason": data.get("reason", ""),
                }
        except (json.JSONDecodeError, ValueError):
            pass
        return None

    def _result(self, decision: str, score: float, direction: str,
                confidence: float, reasoning: str, inputs: dict = None) -> dict:
        """统一输出格式"""
        return {
            "model": self.name,
            "score": round(score, 1),
            "direction": direction,
            "confidence": round(confidence, 1),
            "reasoning": reasoning,
            "details": {
                "decision": decision,
                "conflicts": inputs.get("conflicts", []) if inputs else [],
                "risk_flags": inputs.get("risk_flags", []) if inputs else [],
            },
        }
