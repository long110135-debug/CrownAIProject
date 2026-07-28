"""
皇冠AI赛事研判系统 - 共享工具函数
所有模块从这里导入，不再各自定义。
"""
import re
from datetime import datetime
from typing import Optional


def safe_float(val) -> float:
    """安全转换为浮点数，None/空/异常均返回0.0"""
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


def parse_match_time(time_str: str) -> Optional[datetime]:
    """
    解析比赛时间(支持多种格式)
    - "2026-07-20 17:00" → datetime
    - "07月20日 17:00" → datetime(当年)
    - None/空/无法解析 → None
    """
    if not time_str:
        return None

    # 格式1: "2026-07-20 17:00"
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', time_str)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                          int(m.group(4)), int(m.group(5)))
        except ValueError:
            return None

    # 格式2: "07月20日 17:00"
    m = re.match(r'(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})', time_str)
    if m:
        try:
            return datetime(datetime.now().year, int(m.group(1)), int(m.group(2)),
                          int(m.group(3)), int(m.group(4)))
        except ValueError:
            return None

    return None
