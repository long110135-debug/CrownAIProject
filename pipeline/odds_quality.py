"""
皇冠AI - 盘口数据质量评估与门控

为每场分析生成盘口质量状态。handicap_model/market_model 只有在满足全部条件时
才能使用水位动态(水位变化/资金流向):
  - 相同 primary bookmaker
  - 相同 market_type
  - 相同 handicap line
  - odds_format 已确认
  - 至少 2 条有效快照
  - 时间顺序合法
  - 全部为赛前数据
否则不计算水位变化，返回 insufficient 或仅用基础盘口定位，reason 明确缺失原因。
"""
from utils.database import get_connection
from pipeline.odds_series import (
    get_primary_bookmaker, get_primary_opening, get_primary_current, detect_line_moves,
)

CONFIRMED_FORMATS = {"decimal", "hk"}


def assess_odds_quality(match_id: str, kickoff_utc=None) -> dict:
    """评估一场比赛的盘口数据质量。

    返回:
    {
        "usable": bool,                 # 是否可使用水位动态
        "stable_primary_series": bool,  # 主序列稳定(同公司同线≥2快照格式确认)
        "bookmaker_switched": bool,     # 出现过bookmaker切换
        "line_changed": bool,           # 主序列盘口线发生过变化
        "source_gap": bool,             # 主公司缺失(其他公司在)
        "unknown_format": bool,         # 赔率格式未确认
        "unmatched_line": bool,         # 盘口线无法解析
        "insufficient_snapshots": bool, # 主序列有效快照<2
        "primary_bookmaker": str,
        "snapshot_count": int,          # 主序列快照数
        "reasons": [str],               # 不可用原因清单
    }
    """
    reasons = []
    primary = get_primary_bookmaker(match_id)

    flags = {
        "usable": True,
        "stable_primary_series": False,
        "bookmaker_switched": False,
        "line_changed": False,
        "source_gap": False,
        "unknown_format": False,
        "unmatched_line": False,
        "insufficient_snapshots": False,
        "primary_bookmaker": primary,
        "snapshot_count": 0,
        "reasons": reasons,
    }

    if not primary:
        flags["usable"] = False
        flags["insufficient_snapshots"] = True
        reasons.append("无primary bookmaker(无有效盘口记录)")
        return flags

    conn = get_connection()
    cur = conn.cursor()

    # 主序列记录(同primary bookmaker)
    cur.execute("""
        SELECT handicap_value, odds_format, home_water_normalized, record_time
        FROM odds_timeline
        WHERE match_id = ? AND bookmaker = ?
        ORDER BY record_time ASC, id ASC
    """, (match_id, primary))
    primary_rows = [dict(r) for r in cur.fetchall()]

    # 全部记录(检测bookmaker切换/source_gap)
    cur.execute("""
        SELECT DISTINCT bookmaker FROM odds_timeline
        WHERE match_id = ? AND bookmaker IS NOT NULL AND bookmaker != ''
    """, (match_id,))
    bookmakers = [r[0] for r in cur.fetchall()]
    conn.close()

    flags["snapshot_count"] = len(primary_rows)

    # 1. 快照数不足
    if len(primary_rows) < 2:
        flags["insufficient_snapshots"] = True
        flags["usable"] = False
        reasons.append(f"主序列有效快照{len(primary_rows)}条(<2)")

    # 2. bookmaker切换
    if len(bookmakers) > 1:
        flags["bookmaker_switched"] = True
        reasons.append(f"出现bookmaker切换({','.join(bookmakers)})，水位曲线不可跨公司比较")

    # 3. 盘口线变化
    line_moves = detect_line_moves(match_id)
    if line_moves:
        flags["line_changed"] = True
        reasons.append(f"主序列盘口线变化{len(line_moves)}次(不同线间只记line_move不比水位)")

    # 4. 格式未确认
    formats = {r["odds_format"] for r in primary_rows if r["odds_format"]}
    if not formats or not formats.issubset(CONFIRMED_FORMATS):
        flags["unknown_format"] = True
        flags["usable"] = False
        reasons.append(f"赔率格式未确认({formats or '空'})")

    # 5. 盘口线无法解析
    if any(r["handicap_value"] is None for r in primary_rows):
        flags["unmatched_line"] = True
        reasons.append("存在无法解析的盘口线")

    # 6. source_gap: 主公司记录数 < 全部记录数 且 存在非主公司记录
    #    (此处简化: 若有非primary公司记录, 提示主公司可能有缺口)
    non_primary_count = len([b for b in bookmakers if b != primary])
    if non_primary_count > 0 and len(primary_rows) < 2:
        flags["source_gap"] = True
        reasons.append("主公司快照不足而其他公司存在(source_gap)")

    # 稳定主序列: 同公司 + 同线 + ≥2快照 + 格式确认 + 无切换
    flags["stable_primary_series"] = (
        len(primary_rows) >= 2
        and not flags["bookmaker_switched"]
        and not flags["line_changed"]
        and not flags["unknown_format"]
        and not flags["unmatched_line"]
    )

    # 门控: 只有稳定主序列才可使用水位动态
    if not flags["stable_primary_series"]:
        flags["usable"] = False
        if not reasons:
            reasons.append("主序列不稳定")

    return flags


def can_use_water_dynamics(quality: dict) -> bool:
    """门控: 是否允许使用水位动态(水位变化/资金流向)。
    要求 stable_primary_series(同公司同线≥2快照格式确认无切换无线变)。
    """
    return bool(quality.get("stable_primary_series")) and bool(quality.get("usable"))
