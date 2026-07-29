"""
皇冠AI赛事研判系统 - 共享工具函数
所有模块从这里导入，不再各自定义。
"""
import re
from datetime import datetime
from typing import Optional

from utils.timeutil import UTC, SHANGHAI


def safe_float(val) -> float:
    """安全转换为浮点数，None/空/异常均返回0.0"""
    try:
        return float(val) if val else 0.0
    except (ValueError, TypeError):
        return 0.0


def infer_year(month: int, reference_date: Optional[datetime] = None) -> int:
    """
    根据当前日期推断年份(半年边界规则):
    - 目标月份比当前月份小超过6个月 → 下一年
    - 目标月份比当前月份大超过6个月 → 上一年
    - 否则使用当前年
    """
    now = reference_date or datetime.now(UTC)
    current_month = now.month
    current_year = now.year

    diff = month - current_month
    if diff <= -6:
        return current_year + 1
    elif diff >= 6:
        return current_year - 1
    return current_year


def normalize_date(date_str: str, reference_date: Optional[datetime] = None) -> str:
    """
    统一日期格式(唯一公共实现):
    - '07月20日' → '2026-07-20' (使用半年边界规则推断年份)
    - '2026-07-20' → 原样返回
    - 无法解析 → 原样返回
    """
    if not date_str:
        return date_str

    # 已有完整年份的ISO格式，原样返回
    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
        return date_str

    # 中文格式: '07月20日' 或 '7月20日'
    m = re.match(r'(\d{1,2})月(\d{1,2})日', date_str)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = infer_year(month, reference_date)
        try:
            # 验证日期合法性(处理闰年等)
            datetime(year, month, day)
            return f"{year}-{month:02d}-{day:02d}"
        except ValueError:
            return date_str

    return date_str


def parse_match_time(time_str: str, reference_date: Optional[datetime] = None) -> Optional[datetime]:
    """
    解析比赛时间 → timezone-aware datetime(统一返回aware)。
    - ISO 8601带时区 "2026-07-29T05:30:00+00:00" → 按原时区解析
    - naive ISO "2026-07-20 17:00" → 视为UTC(迁移后的标准存储)
    - 中文 "07月20日 17:00" → 视为Asia/Shanghai北京时间(推断年份)
    - None/空/无法解析 → None
    """
    if not time_str:
        return None
    s = str(time_str).strip()

    # 格式0: ISO 8601 带时区 (含T和+HH:MM/Z)
    if "T" in s and (s.endswith("Z") or re.search(r"[+-]\d{2}:\d{2}$", s)):
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass

    # 格式1: naive ISO "2026-07-20 17:00[:SS]" → 视为UTC
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?', s)
    if m:
        g = m.groups()
        sec = int(g[5]) if g[5] else 0
        try:
            return datetime(int(g[0]), int(g[1]), int(g[2]),
                            int(g[3]), int(g[4]), sec, tzinfo=UTC)
        except ValueError:
            return None

    # 格式2: 中文 "07月20日 17:00" → 北京时间
    m = re.match(r'(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})', s)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year = infer_year(month, reference_date)
        try:
            return datetime(year, month, day, int(m.group(3)), int(m.group(4)),
                            tzinfo=SHANGHAI)
        except ValueError:
            return None

    return None
