"""
皇冠AI赛事研判系统 - 盘口变化追踪 v2.0
全生命周期: 开盘(opening)→早盘(early)→临场(prematch)→收盘(closing)
支持: 多次快照对比、盘口异动检测、收盘锁定、CLV自动计算

工作流程:
1. 首次抓取 → 写入odds_timeline(phase=opening) + odds_snapshots
2. 后续抓取 → 写入odds_timeline(phase=early/prematch) + 对比变化
3. 临场抓取(开赛前1h) → 写入closing_odds + odds_timeline(phase=closing)
4. 结算时 → 自动计算CLV(预测时盘口 vs 收盘盘口)
"""
import json
from datetime import datetime, timedelta
from typing import List, Optional
from utils.logger import log
from utils.database import (
    get_connection, save_odds_snapshot, get_odds_history,
    save_timeline_record, get_timeline, get_opening_odds, get_latest_odds,
    save_closing_odds, get_closing_odds, calc_clv, update_prediction_clv,
)


def save_scrape_snapshot(matches: List[dict], phase: str = "early"):
    """
    [DEPRECATED] 无调用方。盘口写入统一使用 crown_odds_collector.save_crown_odds()。
    本函数绕过collector直接写odds_snapshots，且内联构造match_id（不做联赛名/日期标准化）。
    保留仅供历史参考，新代码禁止调用。
    
    原参数:
    - matches: CrownOddsScraper.scrape_all_early()的返回值
    - phase: 当前抓取阶段 (early/prematch/closing)
    """
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    saved = 0
    for m in matches:
        match_id = f"CROWN_{m['league']}_{m['home']}_{m['away']}_{m['date']}"

        # 确保比赛存在
        cursor.execute("""
            INSERT OR IGNORE INTO matches (match_id, league, league_tier, home_team, away_team, match_time, status)
            VALUES (?, ?, 1, ?, ?, ?, 'pending')
        """, (match_id, m['league'], m['home'], m['away'], f"{m['date']} {m['time']}"))

        # 保存盘口快照(兼容旧表)
        cursor.execute("""
            INSERT INTO odds_snapshots 
            (match_id, snapshot_time, asian_handicap, home_odds, away_odds,
             open_handicap, current_handicap, change_type, over_under,
             over_odds, under_odds, source, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id, now,
            m.get('handicap', ''),
            _safe_float(m.get('home_water')),
            _safe_float(m.get('away_water')),
            m.get('handicap', ''),
            m.get('handicap', ''),
            '快照',
            m.get('over_line', ''),
            _safe_float(m.get('over_water')),
            _safe_float(m.get('under_water')),
            'crown_playwright',
            json.dumps(m, ensure_ascii=False),
        ))
        saved += 1

    conn.commit()
    conn.close()

    # 写入时间线(新表)
    for m in matches:
        match_id = f"CROWN_{m['league']}_{m['home']}_{m['away']}_{m['date']}"
        save_timeline_record(match_id, {
            "handicap": m.get("handicap", ""),
            "home_water": m.get("home_water", ""),
            "away_water": m.get("away_water", ""),
            "over_line": m.get("over_line", ""),
            "over_water": m.get("over_water", ""),
            "under_water": m.get("under_water", ""),
            "home_win": m.get("home_win", ""),
            "draw": m.get("draw", ""),
            "away_win": m.get("away_win", ""),
        }, phase=phase, source="crown_playwright")

    log.info(f"[追踪] 保存{saved}场盘口快照 (phase={phase}, {now})")


def detect_odds_changes() -> List[dict]:
    """
    检测所有比赛的盘口变化(对比时间线最近两条记录)
    
    返回: [{match_id, home, away, league, change_type, 
            old_handicap, new_handicap, old_home_water, new_home_water,
            signal, significance}]
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 获取所有有2次以上时间线记录的比赛
    cursor.execute("""
        SELECT match_id, COUNT(*) as cnt 
        FROM odds_timeline 
        GROUP BY match_id 
        HAVING cnt >= 2
    """)
    multi_matches = [row['match_id'] for row in cursor.fetchall()]
    conn.close()

    changes = []
    for match_id in multi_matches:
        timeline = get_timeline(match_id)
        if len(timeline) < 2:
            continue

        prev = timeline[-2]
        curr = timeline[-1]

        change = _compare_timeline_records(match_id, prev, curr)
        if change and change['change_type'] != '不变':
            changes.append(change)

    if changes:
        log.info(f"[追踪] 检测到{len(changes)}场盘口变化")
    return changes


def lock_closing_odds(hours_before_kickoff: float = 1.0):
    """
    锁定临场收盘赔率
    
    对所有即将开赛的比赛(开赛前N小时内)，将最新盘口标记为收盘赔率。
    应在每次抓取后调用，系统自动判断哪些比赛需要锁定。
    
    参数: hours_before_kickoff - 开赛前多少小时内视为临场
    """
    conn = get_connection()
    cursor = conn.cursor()
    from utils.timeutil import now_utc
    now = now_utc()

    # 获取所有pending状态的比赛
    cursor.execute("SELECT match_id, match_time FROM matches WHERE status = 'pending'")
    pending = [dict(row) for row in cursor.fetchall()]
    conn.close()

    locked = 0
    for match in pending:
        match_id = match['match_id']
        kickoff = _parse_match_time(match['match_time'])
        if not kickoff:
            continue

        # 判断是否进入临场窗口
        time_to_kickoff = (kickoff - now).total_seconds() / 3600
        if time_to_kickoff > hours_before_kickoff:
            continue  # 还没到临场
        if time_to_kickoff < -0.5:
            continue  # 已经开赛了(超过30分钟)

        # 检查是否已有收盘记录
        existing = get_closing_odds(match_id)
        if existing:
            continue  # 已锁定

        # 获取最新盘口作为收盘
        latest = get_latest_odds(match_id)
        if not latest:
            continue

        save_closing_odds(match_id, {
            "handicap": latest.get("handicap", ""),
            "home_water": latest.get("home_water", 0),
            "away_water": latest.get("away_water", 0),
            "over_line": latest.get("over_line", ""),
            "over_water": latest.get("over_water", 0),
            "under_water": latest.get("under_water", 0),
            "home_win": latest.get("home_win", 0),
            "draw": latest.get("draw", 0),
            "away_win": latest.get("away_win", 0),
        }, source="crown_auto_close")

        # 自动计算CLV
        update_prediction_clv(match_id)
        locked += 1

    if locked:
        log.info(f"[追踪] 锁定{locked}场收盘赔率并计算CLV")


def settle_match_clv(match_id: str):
    """
    单场比赛结算时调用: 确保有收盘赔率并计算CLV
    """
    # 如果没有收盘记录，用最新时间线记录作为收盘
    closing = get_closing_odds(match_id)
    if not closing:
        latest = get_latest_odds(match_id)
        if latest:
            save_closing_odds(match_id, {
                "handicap": latest.get("handicap", ""),
                "home_water": latest.get("home_water", 0),
                "away_water": latest.get("away_water", 0),
                "over_line": latest.get("over_line", ""),
                "over_water": latest.get("over_water", 0),
                "under_water": latest.get("under_water", 0),
            }, source="crown_settle_fallback")

    update_prediction_clv(match_id)


def get_match_tracking_report(match_id: str) -> dict:
    """获取单场比赛的完整追踪报告(含时间线+CLV)"""
    timeline = get_timeline(match_id)
    if not timeline:
        # 兼容旧数据: 从odds_snapshots获取
        history = get_odds_history(match_id)
        if history:
            return {
                'match_id': match_id,
                'snapshots': len(history),
                'source': 'legacy_snapshots',
                'first_snapshot': history[0].get('snapshot_time', ''),
                'last_snapshot': history[-1].get('snapshot_time', ''),
                'initial_handicap': history[0].get('asian_handicap', ''),
                'current_handicap': history[-1].get('current_handicap', ''),
                'changes': [],
            }
        return {'match_id': match_id, 'snapshots': 0, 'changes': []}

    # 计算变化
    changes = []
    for i in range(1, len(timeline)):
        change = _compare_timeline_records(match_id, timeline[i-1], timeline[i])
        if change:
            changes.append(change)

    # CLV
    clv = calc_clv(match_id)

    return {
        'match_id': match_id,
        'snapshots': len(timeline),
        'source': 'timeline_v2',
        'first_snapshot': timeline[0].get('record_time', ''),
        'last_snapshot': timeline[-1].get('record_time', ''),
        'opening_phase': timeline[0].get('phase', ''),
        'initial_handicap': timeline[0].get('handicap', ''),
        'initial_home_water': timeline[0].get('home_water', 0),
        'current_handicap': timeline[-1].get('handicap', ''),
        'current_home_water': timeline[-1].get('home_water', 0),
        'changes': changes,
        'total_changes': len(changes),
        'clv': clv,
        'phases_seen': list(set(t.get('phase', '') for t in timeline)),
    }


def get_daily_odds_summary(date_str: str = None) -> dict:
    """
    获取某日的盘口追踪汇总
    返回: {total_matches, with_changes, avg_snapshots, notable_moves}
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    # 当日有时间线记录的比赛
    cursor.execute("""
        SELECT DISTINCT match_id FROM odds_timeline 
        WHERE record_time LIKE ?
    """, (f"{date_str}%",))
    match_ids = [row['match_id'] for row in cursor.fetchall()]
    conn.close()

    if not match_ids:
        return {"date": date_str, "total_matches": 0, "with_changes": 0, "notable_moves": []}

    changes = detect_odds_changes()
    # 过滤当日的变化
    today_changes = [c for c in changes if c.get('curr_time', '').startswith(date_str)]

    # 显著异动(信号强度>=60)
    notable = sorted(
        [c for c in today_changes if c.get('significance', 0) >= 60],
        key=lambda x: -x['significance']
    )

    return {
        "date": date_str,
        "total_matches": len(match_ids),
        "with_changes": len(today_changes),
        "avg_snapshots": round(len(match_ids) and sum(
            len(get_timeline(mid)) for mid in match_ids[:20]
        ) / min(len(match_ids), 20), 1),
        "notable_moves": notable[:10],
    }


# === 内部方法 ===

def _compare_timeline_records(match_id: str, prev: dict, curr: dict) -> Optional[dict]:
    """对比两条时间线记录，检测变化(判断逻辑委托给odds_math)"""
    from utils.odds_math import compute_change

    change = compute_change(
        open_hdp=prev.get('handicap', ''),
        curr_hdp=curr.get('handicap', ''),
        open_hw=prev.get('home_water') or 0,
        curr_hw=curr.get('home_water') or 0,
        open_aw=prev.get('away_water') or 0,
        curr_aw=curr.get('away_water') or 0,
    )

    if change['change_type'] == '不变':
        return None

    return {
        'match_id': match_id,
        'match_info': match_id.replace('CROWN_', ''),
        'change_type': change['change_type'],
        'old_handicap': prev.get('handicap', ''),
        'new_handicap': curr.get('handicap', ''),
        'handicap_diff': change['handicap_diff'],
        'old_home_water': prev.get('home_water') or 0,
        'new_home_water': curr.get('home_water') or 0,
        'home_water_shift': change['home_water_shift'],
        'old_away_water': prev.get('away_water') or 0,
        'new_away_water': curr.get('away_water') or 0,
        'away_water_shift': change['away_water_shift'],
        'signal': change['signal'],
        'significance': change['significance'],
        'prev_time': prev.get('record_time', ''),
        'curr_time': curr.get('record_time', ''),
        'prev_phase': prev.get('phase', ''),
        'curr_phase': curr.get('phase', ''),
    }


from utils.helpers import parse_match_time as _parse_match_time, safe_float as _safe_float
