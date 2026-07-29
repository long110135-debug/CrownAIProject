"""
皇冠AI - 盘口序列管理(固定盘口源 + 盘口线身份)

核心规则:
- 同一水位趋势只能比较 相同bookmaker + 相同market_type + 相同handicap_value 的数据。
- 不同公司之间不得计算水位升降。
- 不同handicap line之间不得计算水位升降，只能记为 line_move(盘口线变化)。
- primary bookmaker 一经确定(最早有效亚盘记录的公司)，比赛期间不因缺失自动切换。
- primary 缺失时标记 source_gap，不用其他公司价格接续水位曲线。
- 其他公司记录可保存但 is_primary_series=0；如需fallback须开新series，不与旧series求差。
- "最平衡线"仅用于首次选择主盘口线，不每快照重选后伪装成同一曲线。
"""
from utils.database import get_connection


def make_series_key(match_id: str, bookmaker: str, market_type: str, handicap_value) -> str:
    """series_key 唯一标识一条盘口序列: match_id|bookmaker|market_type|handicap_value"""
    bm = bookmaker or "unknown"
    mt = market_type or "asian_handicap"
    hv = round(float(handicap_value), 3) if handicap_value is not None else 0.0
    return f"{match_id}|{bm}|{mt}|{hv}"


def get_primary_bookmaker(match_id: str):
    """返回该比赛的 primary bookmaker(最早一条有bookmaker标记的亚盘记录的公司)。

    一旦确定即固定，比赛期间不因缺失自动切换。无记录返回 None。
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT bookmaker FROM odds_timeline
        WHERE match_id = ? AND bookmaker IS NOT NULL AND bookmaker != ''
        ORDER BY record_time ASC, id ASC LIMIT 1
    """, (match_id,))
    row = cursor.fetchone()
    conn.close()
    return row["bookmaker"] if row else None


def get_primary_opening(match_id: str):
    """主序列开盘: primary bookmaker 最早一条有效记录。"""
    primary = get_primary_bookmaker(match_id)
    if not primary:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM odds_timeline
        WHERE match_id = ? AND bookmaker = ?
        ORDER BY record_time ASC, id ASC LIMIT 1
    """, (match_id, primary))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_primary_current(match_id: str):
    """主序列当前盘口: primary bookmaker 最新一条有效记录。"""
    primary = get_primary_bookmaker(match_id)
    if not primary:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM odds_timeline
        WHERE match_id = ? AND bookmaker = ?
        ORDER BY record_time DESC, id DESC LIMIT 1
    """, (match_id, primary))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def detect_line_moves(match_id: str):
    """检测主序列的盘口线变化(line_move)。

    返回 primary bookmaker 序列中 handicap_value 发生变化的相邻记录对列表:
    [{from_time, to_time, from_value, to_value, direction}]
    不同盘口线之间只记 line_move，不当作水位变化。
    """
    primary = get_primary_bookmaker(match_id)
    if not primary:
        return []
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT record_time, handicap_value FROM odds_timeline
        WHERE match_id = ? AND bookmaker = ? AND handicap_value IS NOT NULL
        ORDER BY record_time ASC, id ASC
    """, (match_id, primary))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    moves = []
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]
        if prev["handicap_value"] is None or curr["handicap_value"] is None:
            continue
        if abs(curr["handicap_value"] - prev["handicap_value"]) > 0.01:
            diff = curr["handicap_value"] - prev["handicap_value"]
            moves.append({
                "from_time": prev["record_time"],
                "to_time": curr["record_time"],
                "from_value": prev["handicap_value"],
                "to_value": curr["handicap_value"],
                "direction": "升盘" if diff > 0 else "降盘",
            })
    return moves


def classify_series_record(match_id: str, bookmaker: str, market_type: str,
                           handicap_value) -> dict:
    """判定一条待写入记录的序列身份。

    返回:
      primary_bookmaker: 该比赛的主公司(写入前已存在的)
      is_primary_series: 本记录是否属于主序列(bookmaker==primary)
      series_key: 序列标识
      is_source_gap: 本快照主公司缺失(本记录非主公司且主公司无同时刻记录)——供上层判断
    """
    primary = get_primary_bookmaker(match_id)
    bm = bookmaker or "unknown"
    # 若尚无primary(首条记录)，本记录公司即成为primary
    effective_primary = primary or bm
    is_primary = 1 if bm == effective_primary else 0
    return {
        "primary_bookmaker": effective_primary,
        "is_primary_series": is_primary,
        "series_key": make_series_key(match_id, bm, market_type, handicap_value),
        "is_source_gap": 0,  # 由上层根据同快照主公司是否缺失设置
    }
