"""
皇冠AI赛事研判系统 - 模型基类
权重统一从 config/settings.py MODEL_WEIGHTS 读取，模型文件不硬编码权重。
"""
from abc import ABC, abstractmethod
from typing import Optional
from config.settings import MODEL_WEIGHTS


class BaseModel(ABC):
    """所有模型的基类"""

    name: str = "base"

    @property
    def weight(self) -> float:
        """从全局配置读取权重(唯一定义处: config/settings.py)"""
        return MODEL_WEIGHTS.get(self.name, 0.0)

    @abstractmethod
    def analyze(self, match_data: dict) -> dict:
        """
        分析单场比赛
        
        参数: match_data - 包含比赛基础信息、盘口数据、球队数据等
        返回: {
            "model": self.name,
            "score": 0-100,        # 模型评分
            "direction": "home/away/draw",  # 方向判断
            "confidence": 0-100,   # 可信度
            "reasoning": str,      # 推理说明
            "details": {},         # 详细数据
        }
        """
        pass

    def _clamp(self, value: float, min_val: float = 0, max_val: float = 100) -> float:
        """限制数值范围"""
        return max(min_val, min(max_val, value))

    def _direction_label(self, direction: str) -> str:
        """方向标签转中文"""
        labels = {
            "home": "主胜",
            "away": "客胜",
            "draw": "平局",
            "home_handicap": "让胜",
            "away_handicap": "让负",
            "neutral": "中性",
        }
        return labels.get(direction, direction)
