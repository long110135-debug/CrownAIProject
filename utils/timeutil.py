"""
皇冠AI - 统一时间工具(唯一定义处)

数据库内部统一存储 timezone-aware UTC ISO 8601(如 2026-07-29T05:30:00+00:00)。
展示层统一转换 Asia/Shanghai。
业务代码禁止直接使用 naive datetime.now()，一律用本模块。

旧记录迁移分类(不得盲加8小时):
  legacy_cst_naive - naive北京时间(来自_format_time或datetime.now()本地) → 减8h转UTC
  legacy_utc_naive - naive UTC时间 → 直接标+00:00
  ambiguous        - 无法确定(如中文格式无明确来源) → 不自动迁移，生成清单
"""
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
UTC = timezone.utc


def now_utc() -> datetime:
    """当前时间(timezone-aware UTC)。业务代码统一用此，禁用naive datetime.now()。"""
    return datetime.now(UTC)


def utc_iso(dt: datetime = None) -> str:
    """datetime → UTC ISO 8601字符串(带+00:00)，用于存储。默认当前时间。"""
    if dt is None:
        dt = now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def to_shanghai(dt: datetime) -> datetime:
    """aware datetime → Asia/Shanghai 时区(用于展示)。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(SHANGHAI)


def format_shanghai(dt: datetime, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """aware datetime → 北京时间展示字符串。"""
    return to_shanghai(dt).strftime(fmt)


def parse_to_aware(value) -> datetime:
    """解析存储的时间字符串 → aware datetime。

    支持:
      ISO 8601带时区 (2026-07-29T05:30:00+00:00) → 直接解析
      naive ISO (2026-07-29 05:30:00) → 视为UTC(迁移后的标准存储)
      naive北京时间旧格式 → 需先迁移，此处按UTC处理(迁移后调用)
    无法解析返回 None。
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    s = str(value).strip()
    if not s:
        return None
    # ISO 8601 带时区
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass
    # naive "YYYY-MM-DD HH:MM:SS" / "YYYY-MM-DD HH:MM" → 视为UTC
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        g = m.groups()
        sec = int(g[5]) if g[5] else 0
        return datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), sec, tzinfo=UTC)
    return None


def shanghai_day_to_utc_range(date_str: str):
    """北京时间自然日 → UTC时间范围(用于UTC范围查询替代LIKE 'YYYY-MM-DD%')。

    参数 date_str: 'YYYY-MM-DD' (北京时间日期)
    返回 (utc_start_iso, utc_end_iso): 该北京时间日对应的UTC起止(含+00:00)
    例: 北京时间2026-07-29全天 = UTC 2026-07-28T16:00:00+00:00 ~ 2026-07-29T15:59:59+00:00
    """
    day = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=SHANGHAI)
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = day.replace(hour=23, minute=59, second=59, microsecond=999999)
    return utc_iso(start), utc_iso(end)


def today_utc_range():
    """当前北京时间自然日 → UTC范围。返回 (utc_start_iso, utc_end_iso)。"""
    today_sh = datetime.now(SHANGHAI).strftime("%Y-%m-%d")
    return shanghai_day_to_utc_range(today_sh)


def today_shanghai() -> str:
    """当前北京日期字符串 'YYYY-MM-DD'(用于日聚合log_date字段)。"""
    return datetime.now(SHANGHAI).strftime("%Y-%m-%d")


# === 旧记录迁移分类 ===

_CN_DATE_RE = re.compile(r"(\d{1,2})月(\d{1,2})日")
_ISO_NAIVE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}")
_AWARE_RE = re.compile(r"[+-]\d{2}:\d{2}$|Z$")


def is_already_aware(value) -> bool:
    """判断时间字符串是否已带时区标记。"""
    if value is None:
        return False
    s = str(value).strip()
    return bool(_AWARE_RE.search(s)) or "T" in s and ("+" in s[10:] or s.endswith("Z"))


def classify_legacy_time(value, source_hint: str = "") -> str:
    """对旧naive时间记录分类。

    返回:
      'aware'           - 已带时区，无需迁移
      'legacy_cst_naive'- naive北京时间(可安全减8h转UTC)
      'legacy_utc_naive'- naive UTC(可安全标+00:00)
      'ambiguous'       - 无法确定(中文格式/无来源)，不自动迁移
    """
    if value is None or str(value).strip() == "":
        return "ambiguous"
    s = str(value).strip()
    if is_already_aware(s):
        return "aware"
    # 中文格式(08月21日 15:00) → ambiguous(无明确时区来源)
    if _CN_DATE_RE.search(s):
        return "ambiguous"
    # naive ISO格式
    if _ISO_NAIVE_RE.match(s):
        # 根据来源提示判断是CST还是UTC
        if source_hint in ("utc", "legacy_utc_naive"):
            return "legacy_utc_naive"
        # 默认: 本系统旧naive时间多为北京时间(_format_time/datetime.now()本地)
        return "legacy_cst_naive"
    return "ambiguous"


def migrate_naive_to_utc(value, classification: str):
    """按分类将naive时间字符串转为UTC ISO 8601。

    legacy_cst_naive: 视为北京时间 → 减8h → UTC ISO
    legacy_utc_naive: 视为UTC → 标+00:00
    ambiguous/aware: 原样返回(不处理)
    返回 (new_value_iso, migrated_bool)。
    """
    if classification == "aware":
        return value, False
    if classification == "ambiguous":
        return value, False
    s = str(value).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if not m:
        return value, False
    g = m.groups()
    sec = int(g[5]) if g[5] else 0
    dt = datetime(int(g[0]), int(g[1]), int(g[2]), int(g[3]), int(g[4]), sec)
    if classification == "legacy_cst_naive":
        dt = dt.replace(tzinfo=SHANGHAI).astimezone(UTC)
    elif classification == "legacy_utc_naive":
        dt = dt.replace(tzinfo=UTC)
    else:
        return value, False
    return dt.isoformat(timespec="seconds"), True
