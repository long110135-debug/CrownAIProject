"""
皇冠AI赛事研判系统 - SQLite数据库
存储比赛、盘口、分析结果、历史记录、盘口时间线、CLV追踪、表现日志

v2.0 新增:
- odds_timeline: 盘口全生命周期追踪(开盘→早盘→临场→收盘)
- closing_odds: 临场收盘赔率(CLV计算基准)
- performance_log: 每日模型表现日志
- prediction_history增加CLV字段
- 索引优化
"""
import sqlite3
import json
import time as _time
from pathlib import Path
from datetime import datetime
from typing import Optional, List

DB_PATH = Path(__file__).parent.parent / "data" / "crown.db"

# SQLite写重试配置
_RETRY_MAX = 3
_RETRY_BACKOFF = [0.5, 1.0, 2.0]  # 秒


def _retry_on_locked(fn):
    """
    包装SQLite写操作，遇到'database is locked'时有限重试。
    最多3次，退避0.5s/1s/2s。超过后rollback+关闭连接+抛异常。
    """
    last_err = None
    for attempt in range(_RETRY_MAX):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
            last_err = e
            if attempt < _RETRY_MAX - 1:
                _time.sleep(_RETRY_BACKOFF[attempt])
    # 重试耗尽
    from utils.logger import log
    log.error(f"[DB] 写入重试{_RETRY_MAX}次仍失败: {last_err}")
    raise last_err


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db():
    """初始化数据库表"""
    conn = get_connection()
    cursor = conn.cursor()

    # 比赛表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            league TEXT,
            league_tier INTEGER,
            home_team TEXT,
            away_team TEXT,
            match_time TEXT,
            status TEXT DEFAULT 'pending',
            home_score INTEGER,
            away_score INTEGER,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # 盘口快照表（记录每次抓取的盘口变化）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            snapshot_time TEXT,
            asian_handicap TEXT,
            home_odds REAL,
            away_odds REAL,
            open_handicap TEXT,
            current_handicap TEXT,
            change_type TEXT,
            over_under TEXT,
            over_odds REAL,
            under_odds REAL,
            source TEXT DEFAULT 'crown',
            raw_data TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # === v2.0 新增: 盘口时间线(精细追踪) ===
    # phase: opening(初盘) / early(早盘) / prematch(临场) / closing(收盘) / live(滚球)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_timeline (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'early',
            record_time TEXT NOT NULL,
            handicap TEXT,
            handicap_value REAL,
            home_water REAL,
            away_water REAL,
            over_line TEXT,
            over_water REAL,
            under_water REAL,
            home_win REAL,
            draw REAL,
            away_win REAL,
            source TEXT DEFAULT 'crown',
            is_first INTEGER DEFAULT 0,
            is_closing INTEGER DEFAULT 0,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # === v2.0 新增: 收盘赔率(CLV基准) ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS closing_odds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE NOT NULL,
            closing_time TEXT NOT NULL,
            handicap TEXT,
            handicap_value REAL,
            home_water REAL,
            away_water REAL,
            over_line TEXT,
            over_water REAL,
            under_water REAL,
            home_win REAL,
            draw REAL,
            away_win REAL,
            source TEXT DEFAULT 'crown',
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # === v2.0 新增: 每日表现日志 ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS performance_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT UNIQUE NOT NULL,
            matches_analyzed INTEGER DEFAULT 0,
            recommendations_a INTEGER DEFAULT 0,
            recommendations_b INTEGER DEFAULT 0,
            settled_count INTEGER DEFAULT 0,
            hit_count INTEGER DEFAULT 0,
            miss_count INTEGER DEFAULT 0,
            hit_rate REAL DEFAULT 0,
            avg_crown_index REAL DEFAULT 0,
            avg_data_completeness REAL DEFAULT 0,
            clv_avg REAL,
            roi_simulated REAL,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # === v1.2 新增: 赛果表 ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS match_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE NOT NULL,
            home_score INTEGER,
            away_score INTEGER,
            winner TEXT,
            handicap_result TEXT,
            over_under_result TEXT,
            result_source TEXT DEFAULT 'api-football',
            settled_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # === v1.3 新增: 结果验证层(L4) ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_validation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE NOT NULL,
            league TEXT,
            level TEXT,
            crown_index REAL,
            data_completeness REAL,
            strength_score REAL,
            handicap_score REAL,
            squad_score REAL,
            market_score REAL,
            ai_score REAL,
            recommend_direction TEXT,
            actual_result TEXT,
            result_score TEXT,
            hit INTEGER,
            cover INTEGER,
            clv_handicap REAL,
            clv_water REAL,
            odds_pattern TEXT,
            recommendation_reason TEXT,
            validated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # === v1.3 新增: 覆盖率漏斗统计 ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS filter_funnel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            log_date TEXT UNIQUE NOT NULL,
            total_synced INTEGER DEFAULT 0,
            after_l1 INTEGER DEFAULT 0,
            after_l2 INTEGER DEFAULT 0,
            after_l3 INTEGER DEFAULT 0,
            level_a INTEGER DEFAULT 0,
            level_b INTEGER DEFAULT 0,
            level_c INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )
    """)

    # === v1.2 新增: 盘口变化画像 ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE NOT NULL,
            pattern_type TEXT,
            total_steps INTEGER DEFAULT 0,
            net_change REAL DEFAULT 0,
            max_change REAL DEFAULT 0,
            stability_score REAL DEFAULT 0,
            opening_value REAL,
            closing_value REAL,
            water_trend TEXT,
            profile_detail TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # === v1.2 新增: 模型贡献分析 ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_contribution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            hit INTEGER,
            strength_score REAL,
            handicap_score REAL,
            squad_score REAL,
            market_score REAL,
            ai_score REAL,
            top_model TEXT,
            top_contribution REAL,
            attribution TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # 分析结果表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            analysis_time TEXT,
            model_version TEXT,
            strength_score REAL,
            handicap_score REAL,
            squad_score REAL,
            market_score REAL,
            ai_referee_score REAL,
            crown_index REAL,
            direction TEXT,
            recommendation TEXT,
            stars INTEGER,
            confidence REAL,
            risk_level TEXT,
            reasoning TEXT,
            details TEXT,
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # 球队数据表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS team_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_name TEXT,
            league TEXT,
            season TEXT,
            rank INTEGER,
            played INTEGER,
            wins INTEGER,
            draws INTEGER,
            losses INTEGER,
            goals_for INTEGER,
            goals_against INTEGER,
            xg REAL,
            xga REAL,
            home_wins INTEGER,
            away_wins INTEGER,
            recent_form TEXT,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE(team_name, league, season)
        )
    """)

    # 伤停/阵容表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS squad_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT,
            team_name TEXT,
            missing_players TEXT,
            key_absences TEXT,
            rotation_risk TEXT,
            fatigue_days INTEGER,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        )
    """)

    # 预测历史表（回测核心）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS prediction_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE,
            league TEXT,
            home_team TEXT,
            away_team TEXT,
            kickoff TEXT,
            asian_open TEXT,
            asian_live TEXT,
            crown_index REAL,
            strength_score REAL,
            handicap_score REAL,
            market_score REAL,
            squad_score REAL,
            ai_score REAL,
            data_completeness REAL DEFAULT 0,
            recommend TEXT,
            level TEXT,
            confidence REAL,
            result TEXT DEFAULT '',
            result_score TEXT DEFAULT '',
            hit INTEGER DEFAULT -1,
            error_reason TEXT DEFAULT '',
            predicted_at TEXT DEFAULT (datetime('now', 'localtime')),
            settled_at TEXT,
            clv_handicap REAL,
            clv_water REAL,
            closing_handicap TEXT,
            closing_home_water REAL,
            closing_away_water REAL,
            model_version TEXT,
            model_weights TEXT,
            ai_decision TEXT,
            odds_home_water REAL,
            odds_away_water REAL
        )
    """)

    # === v1.3 影子对照实验表 ===
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendation_experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT UNIQUE NOT NULL,
            model_version TEXT,
            legacy_recommend TEXT,
            consensus_recommend TEXT,
            consensus_weights TEXT,
            consensus_reason TEXT,
            legacy_hit TEXT,
            consensus_hit TEXT,
            legacy_pnl REAL,
            consensus_pnl REAL,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            settled_at TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_experiments_match ON recommendation_experiments(match_id)")

    # === 索引 ===
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_match ON odds_snapshots(match_id, snapshot_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_match ON odds_timeline(match_id, record_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timeline_phase ON odds_timeline(match_id, phase)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_closing_match ON closing_odds(match_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prediction_hit ON prediction_history(hit, level)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_prediction_kickoff ON prediction_history(kickoff)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_matches_time ON matches(match_time, status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_perf_date ON performance_log(log_date)")

    conn.commit()

    # === 迁移: 为旧prediction_history添加CLV字段(如果缺失) ===
    _migrate_prediction_clv(cursor, conn)

    conn.close()


def _migrate_prediction_clv(cursor, conn):
    """为已有的prediction_history表添加缺失字段(兼容旧库，可重复执行)"""
    try:
        cursor.execute("PRAGMA table_info(prediction_history)")
        columns = [row[1] for row in cursor.fetchall()]
        new_cols = {
            "clv_handicap": "REAL",
            "clv_water": "REAL",
            "closing_handicap": "TEXT",
            "closing_home_water": "REAL",
            "closing_away_water": "REAL",
            "model_version": "TEXT",
            "model_weights": "TEXT",
            "ai_decision": "TEXT",
            "odds_home_water": "REAL",
            "odds_away_water": "REAL",
        }
        for col, col_type in new_cols.items():
            if col not in columns:
                cursor.execute(f"ALTER TABLE prediction_history ADD COLUMN {col} {col_type}")
        conn.commit()
    except Exception:
        pass


def save_match(match_data: dict) -> str:
    """保存比赛数据"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO matches 
        (match_id, league, league_tier, home_team, away_team, match_time, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        match_data["match_id"],
        match_data["league"],
        match_data.get("league_tier", 1),
        match_data["home_team"],
        match_data["away_team"],
        match_data["match_time"],
        match_data.get("status", "pending"),
    ))
    conn.commit()
    conn.close()
    return match_data["match_id"]


def save_odds_snapshot(match_id: str, odds_data: dict):
    """保存盘口快照"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO odds_snapshots 
        (match_id, snapshot_time, asian_handicap, home_odds, away_odds,
         open_handicap, current_handicap, change_type, over_under,
         over_odds, under_odds, source, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        odds_data.get("asian_handicap"),
        odds_data.get("home_odds"),
        odds_data.get("away_odds"),
        odds_data.get("open_handicap"),
        odds_data.get("current_handicap"),
        odds_data.get("change_type"),
        odds_data.get("over_under"),
        odds_data.get("over_odds"),
        odds_data.get("under_odds"),
        odds_data.get("source", "crown"),
        json.dumps(odds_data, ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def save_analysis(match_id: str, result: dict):
    """保存分析结果"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO analysis_results 
        (match_id, analysis_time, model_version, strength_score, handicap_score,
         squad_score, market_score, ai_referee_score, crown_index,
         direction, recommendation, stars, confidence, risk_level, reasoning, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        result.get("model_version"),
        result.get("strength_score"),
        result.get("handicap_score"),
        result.get("squad_score"),
        result.get("market_score"),
        result.get("ai_referee_score"),
        result.get("crown_index"),
        result.get("direction"),
        result.get("recommendation"),
        result.get("stars"),
        result.get("confidence"),
        result.get("risk_level"),
        result.get("reasoning"),
        json.dumps(result.get("details", {}), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def get_today_matches(date_str: Optional[str] = None) -> List[dict]:
    """获取今日比赛"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM matches WHERE match_time LIKE ? ORDER BY match_time
    """, (f"{date_str}%",))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_odds_history(match_id: str) -> List[dict]:
    """获取某场比赛的盘口变化历史"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM odds_snapshots 
        WHERE match_id = ? ORDER BY snapshot_time
    """, (match_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_team_stats(team_name: str, league: str = None) -> Optional[dict]:
    """获取球队数据"""
    conn = get_connection()
    cursor = conn.cursor()
    if league:
        cursor.execute("""
            SELECT * FROM team_stats 
            WHERE team_name = ? AND league = ?
            ORDER BY updated_at DESC LIMIT 1
        """, (team_name, league))
    else:
        cursor.execute("""
            SELECT * FROM team_stats 
            WHERE team_name = ?
            ORDER BY updated_at DESC LIMIT 1
        """, (team_name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# === 预测历史（回测核心） ===

def save_prediction(record: dict):
    """
    保存一条预测记录（每场比赛分析后调用，含当时完整快照）
    
    使用 ON CONFLICT DO UPDATE 只更新分析字段，绝不触碰结算字段
    (result/result_score/hit/error_reason/settled_at/clv_*/closing_*)。
    防止重复analyze摧毁已结算数据。
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO prediction_history
            (match_id, league, home_team, away_team, kickoff,
             asian_open, asian_live, crown_index,
             strength_score, handicap_score, market_score, squad_score, ai_score,
             data_completeness, recommend, level, confidence, predicted_at,
             model_version, model_weights, ai_decision, odds_home_water, odds_away_water)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                league = excluded.league,
                home_team = excluded.home_team,
                away_team = excluded.away_team,
                kickoff = excluded.kickoff,
                asian_open = excluded.asian_open,
                asian_live = excluded.asian_live,
                crown_index = excluded.crown_index,
                strength_score = excluded.strength_score,
                handicap_score = excluded.handicap_score,
                market_score = excluded.market_score,
                squad_score = excluded.squad_score,
                ai_score = excluded.ai_score,
                data_completeness = excluded.data_completeness,
                recommend = excluded.recommend,
                level = excluded.level,
                confidence = excluded.confidence,
                predicted_at = excluded.predicted_at,
                model_version = excluded.model_version,
                model_weights = excluded.model_weights,
                ai_decision = excluded.ai_decision,
                odds_home_water = excluded.odds_home_water,
                odds_away_water = excluded.odds_away_water
        """, (
            record.get("match_id"),
            record.get("league"),
            record.get("home_team"),
            record.get("away_team"),
            record.get("kickoff"),
            record.get("asian_open"),
            record.get("asian_live"),
            record.get("crown_index"),
            record.get("strength_score"),
            record.get("handicap_score"),
            record.get("market_score"),
            record.get("squad_score"),
            record.get("ai_score"),
            record.get("data_completeness", 0),
            record.get("recommend"),
            record.get("level"),
            record.get("confidence"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            record.get("model_version", ""),
            json.dumps(record.get("model_weights", {}), ensure_ascii=False),
            record.get("ai_decision", ""),
            record.get("odds_home_water"),
            record.get("odds_away_water"),
        ))
        conn.commit()
    finally:
        conn.close()


def settle_prediction(match_id: str, result: str, result_score: str, hit: int, error_reason: str = ""):
    """
    结算预测（比赛结束后调用）
    hit: 1=命中, 0=未命中, -1=未结算
    result: 胜/平/负
    result_score: 如 "2-1"
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE prediction_history
        SET result = ?, result_score = ?, hit = ?, error_reason = ?,
            settled_at = datetime('now', 'localtime')
        WHERE match_id = ?
    """, (result, result_score, hit, error_reason, match_id))
    conn.commit()
    conn.close()


def get_unsettled_predictions() -> List[dict]:
    """获取所有未结算的预测"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM prediction_history WHERE hit = -1 ORDER BY kickoff
    """)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_hit_stats(level: str = None, limit: int = 100) -> dict:
    """
    获取命中率统计
    返回: {total, hit, miss, hit_rate, by_level: {A: {...}, B: {...}, C: {...}}}
    """
    conn = get_connection()
    cursor = conn.cursor()

    where = "WHERE hit >= 0"
    params = []
    if level:
        where += " AND level = ?"
        params.append(level)

    cursor.execute(f"""
        SELECT level, COUNT(*) as total,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               SUM(CASE WHEN hit = 0 THEN 1 ELSE 0 END) as miss_count
        FROM prediction_history {where}
        GROUP BY level
        ORDER BY level
        LIMIT ?
    """, params + [limit])

    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    stats = {"total": 0, "hit": 0, "miss": 0, "hit_rate": 0, "by_level": {}}
    for row in rows:
        lv = row["level"] or "?"
        total = row["total"]
        hit = row["hit_count"] or 0
        miss = row["miss_count"] or 0
        rate = round(hit / total * 100, 1) if total > 0 else 0
        stats["by_level"][lv] = {"total": total, "hit": hit, "miss": miss, "hit_rate": rate}
        stats["total"] += total
        stats["hit"] += hit
        stats["miss"] += miss

    if stats["total"] > 0:
        stats["hit_rate"] = round(stats["hit"] / stats["total"] * 100, 1)

    return stats


def get_recent_predictions(days: int = 7, level: str = None) -> List[dict]:
    """获取最近N天的预测记录"""
    conn = get_connection()
    cursor = conn.cursor()
    where = "WHERE predicted_at >= datetime('now', 'localtime', ?)"
    params = [f"-{days} days"]
    if level:
        where += " AND level = ?"
        params.append(level)
    cursor.execute(f"""
        SELECT * FROM prediction_history {where}
        ORDER BY predicted_at DESC
    """, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


# === v2.0: 盘口时间线 ===

def save_timeline_record(match_id: str, odds_data: dict, phase: str = "early", source: str = "crown"):
    """
    保存一条盘口时间线记录(带并发写重试)
    
    phase: opening/early/prematch/closing/live
    odds_data: {handicap, home_water, away_water, over_line, over_water, under_water,
                home_win, draw, away_win}
    """
    def _do_write():
        conn = get_connection()
        try:
            cursor = conn.cursor()
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 判断是否是该比赛的首条记录(初盘)
            cursor.execute("SELECT COUNT(*) FROM odds_timeline WHERE match_id = ?", (match_id,))
            count = cursor.fetchone()[0]
            is_first = 1 if count == 0 else 0
            actual_phase = "opening" if is_first else phase

            # 盘口文字转数值
            handicap_str = odds_data.get("handicap", "")
            handicap_value = _handicap_to_number(handicap_str)

            cursor.execute("""
                INSERT INTO odds_timeline
                (match_id, phase, record_time, handicap, handicap_value,
                 home_water, away_water, over_line, over_water, under_water,
                 home_win, draw, away_win, source, is_first, is_closing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                match_id, actual_phase, now,
                handicap_str, handicap_value,
                _safe_float(odds_data.get("home_water")),
                _safe_float(odds_data.get("away_water")),
                odds_data.get("over_line", ""),
                _safe_float(odds_data.get("over_water")),
                _safe_float(odds_data.get("under_water")),
                _safe_float(odds_data.get("home_win")),
                _safe_float(odds_data.get("draw")),
                _safe_float(odds_data.get("away_win")),
                source, is_first,
                1 if actual_phase == "closing" else 0,
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    _retry_on_locked(_do_write)


def get_timeline(match_id: str) -> List[dict]:
    """获取某场比赛的完整盘口时间线"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM odds_timeline WHERE match_id = ? ORDER BY record_time
    """, (match_id,))
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows


def get_opening_odds(match_id: str) -> Optional[dict]:
    """获取某场比赛的初盘(时间线第一条记录)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM odds_timeline WHERE match_id = ? ORDER BY record_time LIMIT 1
    """, (match_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_latest_odds(match_id: str) -> Optional[dict]:
    """获取某场比赛的最新盘口"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM odds_timeline WHERE match_id = ? ORDER BY record_time DESC LIMIT 1
    """, (match_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# === v2.0: 收盘赔率 & CLV ===

def save_closing_odds(match_id: str, odds_data: dict, source: str = "crown"):
    """
    保存收盘赔率(比赛开始前最后一次抓取)
    用于CLV计算: 预测时赔率 vs 收盘赔率
    
    防旧覆盖: 只有当新记录的closing_time >= 已有记录时才更新。
    避免较早的track快照覆盖较晚的close记录。
    """
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    handicap_str = odds_data.get("handicap", "")
    handicap_value = _handicap_to_number(handicap_str)

    # 检查是否已有记录，且已有记录更新
    cursor.execute("SELECT closing_time FROM closing_odds WHERE match_id = ?", (match_id,))
    existing = cursor.fetchone()
    if existing and existing["closing_time"] and existing["closing_time"] > now:
        # 已有记录比当前更新，不覆盖
        conn.close()
        return

    cursor.execute("""
        INSERT OR REPLACE INTO closing_odds
        (match_id, closing_time, handicap, handicap_value,
         home_water, away_water, over_line, over_water, under_water,
         home_win, draw, away_win, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id, now, handicap_str, handicap_value,
        _safe_float(odds_data.get("home_water")),
        _safe_float(odds_data.get("away_water")),
        odds_data.get("over_line", ""),
        _safe_float(odds_data.get("over_water")),
        _safe_float(odds_data.get("under_water")),
        _safe_float(odds_data.get("home_win")),
        _safe_float(odds_data.get("draw")),
        _safe_float(odds_data.get("away_win")),
        source,
    ))

    # 同时写入时间线(closing阶段)
    cursor.execute("""
        INSERT INTO odds_timeline
        (match_id, phase, record_time, handicap, handicap_value,
         home_water, away_water, over_line, over_water, under_water,
         home_win, draw, away_win, source, is_first, is_closing)
        VALUES (?, 'closing', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 1)
    """, (
        match_id, now, handicap_str, handicap_value,
        _safe_float(odds_data.get("home_water")),
        _safe_float(odds_data.get("away_water")),
        odds_data.get("over_line", ""),
        _safe_float(odds_data.get("over_water")),
        _safe_float(odds_data.get("under_water")),
        _safe_float(odds_data.get("home_win")),
        _safe_float(odds_data.get("draw")),
        _safe_float(odds_data.get("away_win")),
        source,
    ))

    conn.commit()
    conn.close()


def get_closing_odds(match_id: str) -> Optional[dict]:
    """获取收盘赔率"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM closing_odds WHERE match_id = ?", (match_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def calc_clv(match_id: str) -> Optional[dict]:
    """
    计算CLV (Closing Line Value)
    DB读取在此，数学计算委托给 odds_math.calc_clv()
    """
    from utils.odds_math import calc_clv as _calc_clv_math

    conn = get_connection()
    cursor = conn.cursor()

    # 获取预测时的盘口
    cursor.execute("SELECT asian_open, asian_live, odds_home_water FROM prediction_history WHERE match_id = ?", (match_id,))
    pred = cursor.fetchone()
    if not pred:
        conn.close()
        return None

    # 获取收盘盘口
    cursor.execute("SELECT handicap, home_water, away_water FROM closing_odds WHERE match_id = ?", (match_id,))
    closing = cursor.fetchone()
    conn.close()

    if not closing:
        return None

    # 委托给odds_math计算
    recommended_hdp = pred["asian_live"] or pred["asian_open"] or ""
    closing_hdp = closing["handicap"] or ""
    recommended_hw = pred["odds_home_water"] or 0
    closing_hw = closing["home_water"] or 0

    clv = _calc_clv_math(recommended_hdp, closing_hdp, recommended_hw, closing_hw)

    return {
        "match_id": match_id,
        "clv_handicap": clv["clv_handicap"],
        "clv_water": clv["clv_water"],
        "positive_clv": clv["positive"],
        "predicted_handicap": recommended_hdp,
        "closing_handicap": closing_hdp,
        "predicted_home_water": recommended_hw,
        "closing_home_water": closing_hw,
    }


def update_prediction_clv(match_id: str):
    """计算并更新预测记录的CLV字段"""
    clv = calc_clv(match_id)
    if not clv:
        return

    closing = get_closing_odds(match_id)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE prediction_history
        SET clv_handicap = ?, clv_water = ?,
            closing_handicap = ?, closing_home_water = ?, closing_away_water = ?
        WHERE match_id = ?
    """, (
        clv["clv_handicap"], clv["clv_water"],
        closing.get("handicap", "") if closing else "",
        closing.get("home_water", 0) if closing else 0,
        closing.get("away_water", 0) if closing else 0,
        match_id,
    ))
    conn.commit()
    conn.close()


# === v2.0: 表现日志 ===

def save_performance_log(log_date: str, data: dict):
    """保存每日表现日志"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO performance_log
        (log_date, matches_analyzed, recommendations_a, recommendations_b,
         settled_count, hit_count, miss_count, hit_rate,
         avg_crown_index, avg_data_completeness, clv_avg, roi_simulated, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log_date,
        data.get("matches_analyzed", 0),
        data.get("recommendations_a", 0),
        data.get("recommendations_b", 0),
        data.get("settled_count", 0),
        data.get("hit_count", 0),
        data.get("miss_count", 0),
        data.get("hit_rate", 0),
        data.get("avg_crown_index", 0),
        data.get("avg_data_completeness", 0),
        data.get("clv_avg"),
        data.get("roi_simulated"),
        data.get("notes", ""),
    ))
    conn.commit()
    conn.close()


def get_performance_summary(days: int = 30) -> dict:
    """
    获取最近N天的表现汇总
    返回: {total_matches, total_settled, hit_rate, avg_clv, roi, by_level, trend}
    """
    conn = get_connection()
    cursor = conn.cursor()

    # 从prediction_history统计
    cursor.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               AVG(CASE WHEN hit >= 0 THEN hit * 1.0 ELSE NULL END) as hit_rate,
               AVG(clv_handicap) as avg_clv_hdp,
               AVG(clv_water) as avg_clv_water,
               AVG(crown_index) as avg_index,
               AVG(data_completeness) as avg_completeness
        FROM prediction_history
        WHERE predicted_at >= datetime('now', 'localtime', ?)
    """, (f"-{days} days",))
    row = dict(cursor.fetchone())

    # 按等级分组
    cursor.execute("""
        SELECT level, COUNT(*) as total,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled
        FROM prediction_history
        WHERE predicted_at >= datetime('now', 'localtime', ?)
        GROUP BY level
    """, (f"-{days} days",))
    by_level = {}
    for r in cursor.fetchall():
        r = dict(r)
        lv = r["level"] or "未分级"
        settled = r["settled"] or 0
        hit = r["hit_count"] or 0
        by_level[lv] = {
            "total": r["total"],
            "settled": settled,
            "hit": hit,
            "hit_rate": round(hit / settled * 100, 1) if settled > 0 else 0,
        }

    conn.close()

    total = row["total"] or 0
    settled = row["settled"] or 0
    hit_count = row["hit_count"] or 0

    return {
        "period_days": days,
        "total_matches": total,
        "total_settled": settled,
        "hit_count": hit_count,
        "hit_rate": round(hit_count / settled * 100, 1) if settled > 0 else 0,
        "avg_clv_handicap": round(row["avg_clv_hdp"], 4) if row["avg_clv_hdp"] else None,
        "avg_clv_water": round(row["avg_clv_water"], 4) if row["avg_clv_water"] else None,
        "avg_crown_index": round(row["avg_index"], 1) if row["avg_index"] else 0,
        "avg_data_completeness": round(row["avg_completeness"], 1) if row["avg_completeness"] else 0,
        "by_level": by_level,
    }


# === v1.2: 赛果 ===

def save_match_result(match_id: str, home_score: int, away_score: int,
                      winner: str, handicap_result: str = "", over_under_result: str = "",
                      source: str = "api-football"):
    """保存赛果"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO match_result
        (match_id, home_score, away_score, winner, handicap_result, over_under_result, result_source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (match_id, home_score, away_score, winner, handicap_result, over_under_result, source))
    # 同时更新matches表
    cursor.execute("""
        UPDATE matches SET home_score=?, away_score=?, status='finished',
        updated_at=datetime('now','localtime') WHERE match_id=?
    """, (home_score, away_score, match_id))
    conn.commit()
    conn.close()


def get_match_result(match_id: str) -> Optional[dict]:
    """获取赛果"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM match_result WHERE match_id = ?", (match_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# === v1.2: 盘口变化画像 ===

def save_odds_profile(match_id: str, profile: dict):
    """保存盘口变化画像"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO odds_profile
        (match_id, pattern_type, total_steps, net_change, max_change,
         stability_score, opening_value, closing_value, water_trend, profile_detail)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        profile.get("pattern_type", ""),
        profile.get("total_steps", 0),
        profile.get("net_change", 0),
        profile.get("max_change", 0),
        profile.get("stability_score", 0),
        profile.get("opening_value"),
        profile.get("closing_value"),
        profile.get("water_trend", ""),
        json.dumps(profile.get("detail", []), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def get_odds_profile(match_id: str) -> Optional[dict]:
    """获取盘口变化画像"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM odds_profile WHERE match_id = ?", (match_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# === v1.2: 模型贡献分析 ===

def save_model_contribution(match_id: str, contribution: dict):
    """保存模型贡献分析"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO model_contribution
        (match_id, hit, strength_score, handicap_score, squad_score, market_score, ai_score,
         top_model, top_contribution, attribution)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        contribution.get("hit"),
        contribution.get("strength_score"),
        contribution.get("handicap_score"),
        contribution.get("squad_score"),
        contribution.get("market_score"),
        contribution.get("ai_score"),
        contribution.get("top_model", ""),
        contribution.get("top_contribution", 0),
        json.dumps(contribution.get("attribution", {}), ensure_ascii=False),
    ))
    conn.commit()
    conn.close()


def get_model_contribution_stats(days: int = 30) -> dict:
    """
    获取模型贡献统计(最近N天)
    返回: {by_model: {strength: {avg_score, top_count}, ...}, top_model_distribution}
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT top_model, COUNT(*) as cnt,
               AVG(top_contribution) as avg_contrib,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_when_top
        FROM model_contribution
        WHERE created_at >= datetime('now', 'localtime', ?)
        GROUP BY top_model
    """, (f"-{days} days",))
    rows = [dict(r) for r in cursor.fetchall()]

    # 各模型平均分
    cursor.execute("""
        SELECT AVG(strength_score) as avg_str, AVG(handicap_score) as avg_hdp,
               AVG(squad_score) as avg_sqd, AVG(market_score) as avg_mkt, AVG(ai_score) as avg_ai
        FROM model_contribution
        WHERE created_at >= datetime('now', 'localtime', ?)
    """, (f"-{days} days",))
    avgs = dict(cursor.fetchone())
    conn.close()

    top_dist = {}
    for r in rows:
        top_dist[r["top_model"] or "?"] = {
            "count": r["cnt"],
            "avg_contribution": round(r["avg_contrib"], 1) if r["avg_contrib"] else 0,
            "hit_when_top": r["hit_when_top"] or 0,
        }

    return {
        "period_days": days,
        "top_model_distribution": top_dist,
        "avg_scores": {
            "strength": round(avgs["avg_str"], 1) if avgs["avg_str"] else 0,
            "handicap": round(avgs["avg_hdp"], 1) if avgs["avg_hdp"] else 0,
            "squad": round(avgs["avg_sqd"], 1) if avgs["avg_sqd"] else 0,
            "market": round(avgs["avg_mkt"], 1) if avgs["avg_mkt"] else 0,
            "ai": round(avgs["avg_ai"], 1) if avgs["avg_ai"] else 0,
        },
    }


# === v1.3: 结果验证层(L4) ===

def save_validation_record(match_id: str, record: dict):
    """保存赛后验证记录(结算时自动调用)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO model_validation
        (match_id, league, level, crown_index, data_completeness,
         strength_score, handicap_score, squad_score, market_score, ai_score,
         recommend_direction, actual_result, result_score, hit, cover,
         clv_handicap, clv_water, odds_pattern, recommendation_reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        match_id,
        record.get("league", ""),
        record.get("level", ""),
        record.get("crown_index"),
        record.get("data_completeness"),
        record.get("strength_score"),
        record.get("handicap_score"),
        record.get("squad_score"),
        record.get("market_score"),
        record.get("ai_score"),
        record.get("recommend_direction", ""),
        record.get("actual_result", ""),
        record.get("result_score", ""),
        record.get("hit"),
        record.get("cover"),
        record.get("clv_handicap"),
        record.get("clv_water"),
        record.get("odds_pattern", ""),
        record.get("recommendation_reason", ""),
    ))
    conn.commit()
    conn.close()


def get_validation_stats(days: int = 30) -> dict:
    """
    获取验证统计(按等级)
    核心指标: A级命中率是否明显优于B级
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT level, COUNT(*) as total,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               SUM(CASE WHEN cover = 1 THEN 1 ELSE 0 END) as cover_count,
               AVG(clv_handicap) as avg_clv,
               AVG(crown_index) as avg_index
        FROM model_validation
        WHERE validated_at >= datetime('now', 'localtime', ?)
        GROUP BY level ORDER BY level
    """, (f"-{days} days",))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    by_level = {}
    for r in rows:
        lv = r["level"] or "?"
        total = r["total"] or 0
        hit = r["hit_count"] or 0
        cover = r["cover_count"] or 0
        by_level[lv] = {
            "total": total,
            "hit": hit,
            "hit_rate": round(hit / total * 100, 1) if total > 0 else 0,
            "cover": cover,
            "cover_rate": round(cover / total * 100, 1) if total > 0 else 0,
            "avg_clv": round(r["avg_clv"], 3) if r["avg_clv"] else None,
            "avg_index": round(r["avg_index"], 1) if r["avg_index"] else 0,
        }

    return {"period_days": days, "by_level": by_level}


# === v1.3: 覆盖率漏斗 ===

def save_filter_funnel(log_date: str, funnel: dict):
    """保存每日过滤漏斗数据"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO filter_funnel
        (log_date, total_synced, after_l1, after_l2, after_l3, level_a, level_b, level_c)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        log_date,
        funnel.get("total_synced", 0),
        funnel.get("after_l1", 0),
        funnel.get("after_l2", 0),
        funnel.get("after_l3", 0),
        funnel.get("level_a", 0),
        funnel.get("level_b", 0),
        funnel.get("level_c", 0),
    ))
    conn.commit()
    conn.close()


def get_funnel_summary(days: int = 30) -> dict:
    """获取漏斗汇总(最近N天)"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT SUM(total_synced) as synced, SUM(after_l1) as l1,
               SUM(after_l2) as l2, SUM(after_l3) as l3,
               SUM(level_a) as a, SUM(level_b) as b, SUM(level_c) as c,
               COUNT(*) as days
        FROM filter_funnel
        WHERE log_date >= date('now', 'localtime', ?)
    """, (f"-{days} days",))
    row = dict(cursor.fetchone())
    conn.close()

    synced = row["synced"] or 0
    return {
        "period_days": row["days"] or 0,
        "total_synced": synced,
        "after_l1": row["l1"] or 0,
        "after_l2": row["l2"] or 0,
        "after_l3": row["l3"] or 0,
        "level_a": row["a"] or 0,
        "level_b": row["b"] or 0,
        "level_c": row["c"] or 0,
        "coverage_rate": round((row["a"] or 0) + (row["b"] or 0), 1) if synced == 0 else
                         round(((row["a"] or 0) + (row["b"] or 0)) / synced * 100, 1),
    }


# === v1.3 影子对照实验 ===

def save_experiment(record: dict):
    """
    保存影子对照实验记录(幂等UPSERT，不覆盖已结算字段)
    
    record: {match_id, model_version, legacy_recommend, consensus_recommend,
             consensus_weights, consensus_reason}
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO recommendation_experiments
            (match_id, model_version, legacy_recommend, consensus_recommend,
             consensus_weights, consensus_reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
            ON CONFLICT(match_id) DO UPDATE SET
                model_version = excluded.model_version,
                legacy_recommend = excluded.legacy_recommend,
                consensus_recommend = excluded.consensus_recommend,
                consensus_weights = excluded.consensus_weights,
                consensus_reason = excluded.consensus_reason
        """, (
            record.get("match_id"),
            record.get("model_version", ""),
            record.get("legacy_recommend"),
            record.get("consensus_recommend"),
            json.dumps(record.get("consensus_weights", {}), ensure_ascii=False),
            record.get("consensus_reason", ""),
        ))
        conn.commit()
    finally:
        conn.close()


def settle_experiment(match_id: str, legacy_hit: str, consensus_hit: str,
                      legacy_pnl: float = None, consensus_pnl: float = None):
    """
    结算影子实验(幂等: 已结算则跳过)
    
    hit值: win/half_win/push/half_loss/loss/no_bet/invalid
    pnl: 单位收益(win=+1, half_win=+0.5, push=0, half_loss=-0.5, loss=-1, no_bet/invalid=None)
    """
    conn = get_connection()
    try:
        cursor = conn.cursor()
        # 幂等: 已结算则不覆盖
        cursor.execute("""
            UPDATE recommendation_experiments
            SET legacy_hit = ?, consensus_hit = ?, legacy_pnl = ?, consensus_pnl = ?,
                settled_at = datetime('now', 'localtime')
            WHERE match_id = ? AND settled_at IS NULL
        """, (legacy_hit, consensus_hit, legacy_pnl, consensus_pnl, match_id))
        conn.commit()
    finally:
        conn.close()


def get_experiment_stats() -> dict:
    """获取影子实验统计(observe报表用)"""
    conn = get_connection()
    cursor = conn.cursor()

    # 基础统计
    cursor.execute("SELECT COUNT(*) FROM recommendation_experiments")
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM recommendation_experiments WHERE settled_at IS NOT NULL")
    settled = cursor.fetchone()[0]

    # 方向一致性
    cursor.execute("""
        SELECT COUNT(*) FROM recommendation_experiments
        WHERE legacy_recommend = consensus_recommend AND settled_at IS NOT NULL
    """)
    agree = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM recommendation_experiments
        WHERE legacy_recommend != consensus_recommend AND settled_at IS NOT NULL
    """)
    disagree = cursor.fetchone()[0]

    # legacy结算分布
    cursor.execute("""
        SELECT legacy_hit, COUNT(*) as cnt FROM recommendation_experiments
        WHERE settled_at IS NOT NULL AND legacy_hit IS NOT NULL
        GROUP BY legacy_hit
    """)
    legacy_dist = {row[0]: row[1] for row in cursor.fetchall()}

    # consensus结算分布
    cursor.execute("""
        SELECT consensus_hit, COUNT(*) as cnt FROM recommendation_experiments
        WHERE settled_at IS NOT NULL AND consensus_hit IS NOT NULL
        GROUP BY consensus_hit
    """)
    consensus_dist = {row[0]: row[1] for row in cursor.fetchall()}

    # PnL
    cursor.execute("""
        SELECT SUM(legacy_pnl), SUM(consensus_pnl),
               COUNT(CASE WHEN legacy_pnl IS NOT NULL THEN 1 END),
               COUNT(CASE WHEN consensus_pnl IS NOT NULL THEN 1 END)
        FROM recommendation_experiments WHERE settled_at IS NOT NULL
    """)
    pnl_row = cursor.fetchone()
    legacy_pnl = pnl_row[0] or 0
    consensus_pnl = pnl_row[1] or 0
    legacy_bet_count = pnl_row[2] or 0
    consensus_bet_count = pnl_row[3] or 0

    conn.close()

    return {
        "total": total,
        "settled": settled,
        "unsettled": total - settled,
        "agree": agree,
        "disagree": disagree,
        "legacy_dist": legacy_dist,
        "consensus_dist": consensus_dist,
        "legacy_pnl": legacy_pnl,
        "consensus_pnl": consensus_pnl,
        "legacy_bet_count": legacy_bet_count,
        "consensus_bet_count": consensus_bet_count,
        "legacy_roi": round(legacy_pnl / legacy_bet_count * 100, 1) if legacy_bet_count > 0 else None,
        "consensus_roi": round(consensus_pnl / consensus_bet_count * 100, 1) if consensus_bet_count > 0 else None,
    }


# === 内部工具函数 ===

# 委托到唯一实现(utils/odds_math.py)，不重复定义
from utils.odds_math import handicap_to_number as _handicap_to_number
from utils.helpers import safe_float as _safe_float


# 初始化
init_db()
