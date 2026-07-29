"""
皇冠AI赛事研判系统 - 观察期只读统计 v1.3
只读取现有数据库，不改写任何历史预测、结算或模型结果。
不运行train_weights.py，不调整权重和阈值。

用法: python3 scheduler.py observe [--html]
"""
import os
import json
from datetime import datetime
from typing import Optional
from utils.database import get_connection
from utils.logger import log
from config.settings import MODEL_VERSION, OBSERVATION_PHASE, FORMAL_OBSERVATION_VERSIONS


def collect_observation() -> dict:
    """收集观察期全部统计指标(只读)"""
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')

    result = {
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "run_health": _run_health(cursor, today),
        "sample_stats": _sample_stats(cursor),
        "settlement_breakdown": _settlement_breakdown(cursor),
        "clv_distribution": _clv_distribution(cursor),
        "by_league": _by_league(cursor),
        "by_handicap_type": _by_handicap_type(cursor),
        "by_level": _by_level(cursor),
        "by_model_version": _by_model_version(cursor),
        "null_tracking": _null_tracking(cursor),
        "neutral_analysis": _neutral_analysis(cursor),
        "near_threshold": _near_threshold(cursor),
        "observation_phase": OBSERVATION_PHASE,
        "formal_progress": _formal_progress(cursor),
    }

    conn.close()

    # 影子对照实验统计(独立查询，不需要cursor)
    from utils.database import get_experiment_stats
    result["shadow_experiment"] = get_experiment_stats()

    return result


def _run_health(cursor, today: str) -> dict:
    """每日运行健康"""
    # sync写入比赛数
    cursor.execute("SELECT COUNT(*) FROM matches WHERE match_time LIKE ?", (f"{today}%",))
    sync_count = cursor.fetchone()[0]

    # track成功获取盘口的比赛数(今日timeline去重match_id)
    cursor.execute("""
        SELECT COUNT(DISTINCT match_id) FROM odds_timeline 
        WHERE record_time LIKE ?
    """, (f"{today}%",))
    track_count = cursor.fetchone()[0]

    # odds_timeline今日新增记录数
    cursor.execute("SELECT COUNT(*) FROM odds_timeline WHERE record_time LIKE ?", (f"{today}%",))
    timeline_new = cursor.fetchone()[0]

    # analyze: 总比赛数、L2通过数
    cursor.execute("""
        SELECT total_synced, after_l1, after_l2, after_l3, level_a, level_b, level_c
        FROM filter_funnel WHERE log_date = ?
    """, (today,))
    funnel = cursor.fetchone()
    if funnel:
        analyze_total = funnel[0] or 0
        l2_passed = funnel[2] or 0
        level_a = funnel[4] or 0
        level_b = funnel[5] or 0
        level_c = funnel[6] or 0
    else:
        analyze_total = l2_passed = level_a = level_b = level_c = 0

    # closing_odds今日新增
    cursor.execute("SELECT COUNT(*) FROM closing_odds WHERE closing_time LIKE ?", (f"{today}%",))
    closing_new = cursor.fetchone()[0]

    # settle: 已结算/待结算
    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE hit >= 0")
    settled = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE hit = -1")
    unsettled = cursor.fetchone()[0]

    # report生成状态
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    report_path = os.path.join(output_dir, f"daily_report_{today}.html")
    report_exists = os.path.exists(report_path)

    # watchdog状态
    health_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "data", "health_status.json")
    watchdog_healthy = None
    watchdog_time = None
    watchdog_issues = []
    if os.path.exists(health_path):
        try:
            with open(health_path) as f:
                wd = json.load(f)
            watchdog_healthy = wd.get("healthy")
            watchdog_time = wd.get("time")
            watchdog_issues = wd.get("issues", [])
        except Exception:
            pass

    # watchdog重启次数(从state文件)
    state_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "data", "watchdog_state.json")
    restart_count = 0
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                st = json.load(f)
            restart_count = len(st.get("restarts", []))
        except Exception:
            pass

    return {
        "sync_matches": sync_count,
        "track_odds_matches": track_count,
        "timeline_new_records": timeline_new,
        "analyze_total": analyze_total,
        "l2_passed": l2_passed,
        "level_a": level_a,
        "level_b": level_b,
        "level_c": level_c,
        "closing_odds_new": closing_new,
        "settled": settled,
        "unsettled": unsettled,
        "report_generated": report_exists,
        "watchdog_healthy": watchdog_healthy,
        "watchdog_time": watchdog_time,
        "watchdog_issues": watchdog_issues,
        "watchdog_restarts": restart_count,
    }


def _sample_stats(cursor) -> dict:
    """样本观察指标(仅统计当前模型版本，版本升级即观察期重置)"""
    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE model_version = ?",
                   (MODEL_VERSION,))
    total = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE hit >= 0 AND model_version = ?",
                   (MODEL_VERSION,))
    settled = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE hit = -1 AND model_version = ?",
                   (MODEL_VERSION,))
    unsettled = cursor.fetchone()[0]

    # 有完整收盘数据
    cursor.execute("""
        SELECT COUNT(*) FROM prediction_history p
        WHERE p.model_version = ?
          AND EXISTS (SELECT 1 FROM closing_odds c WHERE c.match_id = p.match_id)
    """, (MODEL_VERSION,))
    has_closing = cursor.fetchone()[0]

    return {
        "total_recommendations": total,
        "settled": settled,
        "unsettled": unsettled,
        "has_closing_data": has_closing,
        "no_closing_data": total - has_closing,
        "model_version": MODEL_VERSION,
    }


def _formal_progress(cursor) -> dict:
    """正式观察期门槛进度(仅统计 FORMAL_OBSERVATION_VERSIONS 内的版本)。

    验证期该集合为空 → 全部计数为0，正式观察期未开始。
    新数据(validation版本)为debug_sample，不计入此进度。
    """
    versions = FORMAL_OBSERVATION_VERSIONS
    if not versions:
        return {"total_recommendations": 0, "has_closing_data": 0, "quarter_count": 0,
                "formal_versions": []}

    placeholders = ",".join("?" * len(versions))

    cursor.execute(f"SELECT COUNT(*) FROM prediction_history WHERE model_version IN ({placeholders})",
                   versions)
    total = cursor.fetchone()[0]

    cursor.execute(f"""
        SELECT COUNT(*) FROM prediction_history p
        WHERE p.model_version IN ({placeholders})
          AND EXISTS (SELECT 1 FROM closing_odds c WHERE c.match_id = p.match_id)
    """, versions)
    has_closing = cursor.fetchone()[0]

    cursor.execute(f"SELECT asian_live, asian_open FROM prediction_history WHERE model_version IN ({placeholders})",
                   versions)
    from utils.odds_math import handicap_to_number
    quarter = 0
    for row in cursor.fetchall():
        hdp_str = row[0] or row[1]
        if not hdp_str:
            continue
        frac = abs(handicap_to_number(hdp_str)) % 1.0
        if abs(frac - 0.25) < 0.01 or abs(frac - 0.75) < 0.01:
            quarter += 1

    return {"total_recommendations": total, "has_closing_data": has_closing,
            "quarter_count": quarter, "formal_versions": versions}


def _settlement_breakdown(cursor) -> dict:
    """win/half_win/push/half_loss/loss分布"""
    # 基于match_result的handicap_result字段
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN handicap_result = 'home_cover' THEN 1 ELSE 0 END) as win,
            SUM(CASE WHEN handicap_result = 'half_win' THEN 1 ELSE 0 END) as half_win,
            SUM(CASE WHEN handicap_result = 'push' THEN 1 ELSE 0 END) as push,
            SUM(CASE WHEN handicap_result = 'half_loss' THEN 1 ELSE 0 END) as half_loss,
            SUM(CASE WHEN handicap_result = 'away_cover' THEN 1 ELSE 0 END) as loss,
            COUNT(*) as total
        FROM match_result
    """)
    row = cursor.fetchone()
    return {
        "win": row[0] or 0,
        "half_win": row[1] or 0,
        "push": row[2] or 0,
        "half_loss": row[3] or 0,
        "loss": row[4] or 0,
        "total": row[5] or 0,
    }


def _clv_distribution(cursor) -> dict:
    """正CLV/零CLV/负CLV/NULL分布"""
    cursor.execute("""
        SELECT
            SUM(CASE WHEN clv_handicap > 0 THEN 1 ELSE 0 END) as positive,
            SUM(CASE WHEN clv_handicap = 0 THEN 1 ELSE 0 END) as zero,
            SUM(CASE WHEN clv_handicap < 0 THEN 1 ELSE 0 END) as negative,
            SUM(CASE WHEN clv_handicap IS NULL THEN 1 ELSE 0 END) as null_count,
            AVG(CASE WHEN clv_handicap IS NOT NULL THEN clv_handicap END) as avg_clv
        FROM prediction_history
    """)
    row = cursor.fetchone()
    return {
        "positive": row[0] or 0,
        "zero": row[1] or 0,
        "negative": row[2] or 0,
        "null": row[3] or 0,
        "avg_clv": round(row[4], 4) if row[4] is not None else None,
    }


def _by_league(cursor) -> list:
    """按联赛统计样本数(仅当前模型版本)"""
    cursor.execute("""
        SELECT league, COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count
        FROM prediction_history
        WHERE model_version = ?
        GROUP BY league ORDER BY total DESC
    """, (MODEL_VERSION,))
    return [{"league": r[0], "total": r[1], "settled": r[2] or 0, "hit": r[3] or 0}
            for r in cursor.fetchall()]


def _by_handicap_type(cursor) -> dict:
    """按盘口类型统计: 整数/0.25/0.5/0.75/其他/NULL"""
    cursor.execute("SELECT asian_live, asian_open FROM prediction_history WHERE model_version = ?",
                   (MODEL_VERSION,))
    rows = cursor.fetchall()

    from utils.odds_math import handicap_to_number
    counts = {"integer": 0, "quarter_025": 0, "half_050": 0, "quarter_075": 0, "other": 0, "null": 0}

    for row in rows:
        hdp_str = row[0] or row[1]
        if not hdp_str:
            counts["null"] += 1
            continue
        val = abs(handicap_to_number(hdp_str))
        frac = val % 1.0
        if abs(frac) < 0.01:
            counts["integer"] += 1
        elif abs(frac - 0.25) < 0.01:
            counts["quarter_025"] += 1
        elif abs(frac - 0.5) < 0.01:
            counts["half_050"] += 1
        elif abs(frac - 0.75) < 0.01:
            counts["quarter_075"] += 1
        else:
            counts["other"] += 1

    return counts


def _by_level(cursor) -> list:
    """按推荐等级统计(仅当前模型版本)"""
    cursor.execute("""
        SELECT level, COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               AVG(crown_index) as avg_index
        FROM prediction_history
        WHERE model_version = ?
        GROUP BY level ORDER BY level
    """, (MODEL_VERSION,))
    return [{"level": r[0] or "NULL", "total": r[1], "settled": r[2] or 0,
             "hit": r[3] or 0, "avg_index": round(r[4], 1) if r[4] else None}
            for r in cursor.fetchall()]


def _by_model_version(cursor) -> list:
    """按模型版本统计"""
    cursor.execute("""
        SELECT model_version, COUNT(*) as total
        FROM prediction_history
        GROUP BY model_version ORDER BY total DESC
    """)
    return [{"version": r[0] or "NULL", "total": r[1]} for r in cursor.fetchall()]


def _null_tracking(cursor) -> dict:
    """NULL和旧版本记录追踪(不静默当0)"""
    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE model_version IS NULL OR model_version = ''")
    null_version = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE model_weights IS NULL OR model_weights = '' OR model_weights = '{}'")
    null_weights = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE ai_decision IS NULL OR ai_decision = ''")
    null_ai = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE odds_home_water IS NULL")
    null_water = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history WHERE clv_handicap IS NULL")
    null_clv = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM prediction_history")
    total = cursor.fetchone()[0]

    return {
        "total_records": total,
        "null_model_version": null_version,
        "null_model_weights": null_weights,
        "null_ai_decision": null_ai,
        "null_odds_water": null_water,
        "null_clv": null_clv,
        "complete_records": total - max(null_version, null_weights, null_ai, null_water),
    }


def _neutral_analysis(cursor) -> dict:
    """数据不足导致neutral的数量和原因"""
    cursor.execute("""
        SELECT COUNT(*) FROM prediction_history
        WHERE recommend = 'neutral' OR recommend IS NULL OR recommend = ''
    """)
    neutral_count = cursor.fetchone()[0]

    # 原因分析: 低完整度 vs 低盘口分
    cursor.execute("""
        SELECT COUNT(*) FROM prediction_history
        WHERE (recommend = 'neutral' OR recommend IS NULL OR recommend = '')
        AND data_completeness < 50
    """)
    low_completeness = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM prediction_history
        WHERE (recommend = 'neutral' OR recommend IS NULL OR recommend = '')
        AND data_completeness >= 50
    """)
    has_data_but_neutral = cursor.fetchone()[0]

    return {
        "total_neutral": neutral_count,
        "due_to_low_completeness": low_completeness,
        "has_data_but_neutral": has_data_but_neutral,
    }


def _near_threshold(cursor) -> list:
    """距离推荐门槛(75)1至3分的比赛及赛后表现"""
    cursor.execute("""
        SELECT match_id, home_team, away_team, league, crown_index, level, hit, result_score
        FROM prediction_history
        WHERE crown_index >= 72 AND crown_index < 75
        ORDER BY crown_index DESC
    """)
    return [{"match_id": r[0], "home": r[1], "away": r[2], "league": r[3],
             "crown_index": r[4], "level": r[5], "hit": r[6], "score": r[7]}
            for r in cursor.fetchall()]


# === 终端输出 ===

def print_observation(data: dict):
    """终端摘要输出"""
    h = data["run_health"]
    s = data["sample_stats"]

    print(f"\n{'═'*60}")
    print(f"  皇冠AI 观察期统计  {data['generated_at']}")
    print(f"{'═'*60}")

    print(f"\n  ┌─ 每日运行健康 ─────────────────────────────")
    print(f"  │ sync: {h['sync_matches']}场 | track: {h['track_odds_matches']}场有盘口 | timeline: +{h['timeline_new_records']}条")
    print(f"  │ analyze: {h['analyze_total']}场 → L2通过{h['l2_passed']} | A:{h['level_a']} B:{h['level_b']} C:{h['level_c']}")
    print(f"  │ closing: +{h['closing_odds_new']} | settled: {h['settled']} | 待结算: {h['unsettled']}")
    print(f"  │ report: {'✓' if h['report_generated'] else '✗'} | watchdog: {'✓' if h['watchdog_healthy'] else '✗'} ({h['watchdog_time'] or '?'}) 重启{h['watchdog_restarts']}次")
    if h['watchdog_issues']:
        for issue in h['watchdog_issues']:
            print(f"  │   ⚠ {issue}")
    print(f"  └──────────────────────────────────────────")

    print(f"\n  ┌─ 样本积累 ───────────────────────────────")
    print(f"  │ 总推荐: {s['total_recommendations']} | 已结算: {s['settled']} | 待结算: {s['unsettled']}")
    print(f"  │ 有收盘数据: {s['has_closing_data']} | 无收盘: {s['no_closing_data']}")
    sb = data["settlement_breakdown"]
    print(f"  │ 结算分布: W{sb['win']} HW{sb['half_win']} P{sb['push']} HL{sb['half_loss']} L{sb['loss']} (共{sb['total']})")
    clv = data["clv_distribution"]
    print(f"  │ CLV: 正{clv['positive']} 零{clv['zero']} 负{clv['negative']} NULL{clv['null']} 均值{clv['avg_clv']}")
    print(f"  └──────────────────────────────────────────")

    print(f"\n  ┌─ 按联赛 ─────────────────────────────────")
    for lg in data["by_league"][:8]:
        hr = f"{lg['hit']}/{lg['settled']}" if lg['settled'] > 0 else "-"
        print(f"  │ {lg['league']:<12} {lg['total']:>3}场 结算{lg['settled']:>2} 命中{hr}")
    print(f"  └──────────────────────────────────────────")

    ht = data["by_handicap_type"]
    print(f"\n  ┌─ 按盘口类型 ─────────────────────────────")
    print(f"  │ 整数:{ht['integer']} | 0.25:{ht['quarter_025']} | 0.5:{ht['half_050']} | 0.75:{ht['quarter_075']} | 其他:{ht['other']} | NULL:{ht['null']}")
    print(f"  └──────────────────────────────────────────")

    print(f"\n  ┌─ 按等级 ─────────────────────────────────")
    for lv in data["by_level"]:
        hr = f"{lv['hit']}/{lv['settled']}" if lv['settled'] > 0 else "-"
        print(f"  │ {lv['level']}: {lv['total']:>3}场 结算{lv['settled']:>2} 命中{hr} 均指数{lv['avg_index']}")
    print(f"  └──────────────────────────────────────────")

    nt = data["null_tracking"]
    print(f"\n  ┌─ NULL追踪(不静默当0) ────────────────────")
    print(f"  │ 总记录: {nt['total_records']} | 完整: {nt['complete_records']}")
    print(f"  │ NULL: version={nt['null_model_version']} weights={nt['null_model_weights']} ai={nt['null_ai_decision']} water={nt['null_odds_water']} clv={nt['null_clv']}")
    print(f"  └──────────────────────────────────────────")

    na = data["neutral_analysis"]
    print(f"\n  ┌─ Neutral分析 ────────────────────────────")
    print(f"  │ 总neutral: {na['total_neutral']} | 数据不足: {na['due_to_low_completeness']} | 有数据仍neutral: {na['has_data_but_neutral']}")
    print(f"  └──────────────────────────────────────────")

    near = data["near_threshold"]
    if near:
        print(f"\n  ┌─ 距门槛(75)1~3分: {len(near)}场 ─────────────────")
        for n in near[:5]:
            hit_str = {1: "✓", 0: "✗", -1: "?"}.get(n["hit"], "?")
            print(f"  │ {hit_str} {n['home']} vs {n['away']} [{n['league']}] 指数{n['crown_index']} {n['score'] or ''}")
        print(f"  └──────────────────────────────────────────")

    # 影子对照实验
    se = data.get("shadow_experiment", {})
    if se.get("total", 0) > 0:
        print(f"\n  ┌─ 影子对照: legacy vs consensus ────────────")
        print(f"  │ 总记录: {se['total']} | 已结算: {se['settled']} | 待结算: {se['unsettled']}")
        print(f"  │ 方向一致: {se['agree']} | 方向不一致: {se['disagree']}")
        if se['settled'] > 0:
            ld = se['legacy_dist']
            cd = se['consensus_dist']
            print(f"  │ legacy:    W{ld.get('win',0)} HW{ld.get('half_win',0)} P{ld.get('push',0)} HL{ld.get('half_loss',0)} L{ld.get('loss',0)} NB{ld.get('no_bet',0)} INV{ld.get('invalid',0)}")
            print(f"  │ consensus: W{cd.get('win',0)} HW{cd.get('half_win',0)} P{cd.get('push',0)} HL{cd.get('half_loss',0)} L{cd.get('loss',0)} NB{cd.get('no_bet',0)} INV{cd.get('invalid',0)}")
            print(f"  │ legacy PnL: {se['legacy_pnl']:+.1f} ({se['legacy_bet_count']}注) ROI={se['legacy_roi']}%")
            print(f"  │ consensus PnL: {se['consensus_pnl']:+.1f} ({se['consensus_bet_count']}注) ROI={se['consensus_roi']}%")
        else:
            print(f"  │ (尚无已结算数据)")
        print(f"  └──────────────────────────────────────────")

    # 观察期进度
    phase = data.get("observation_phase", "formal")
    fp = data.get("formal_progress", {})
    print(f"\n  ┌─ 观察期进度 (阶段: {phase}) ───────────────")
    if phase == "validation":
        print(f"  │ ⚠ 验证期: 正式观察期未开始，新数据为debug_sample不计入门槛")
        print(f"  │ 当前版本({MODEL_VERSION})验证样本: {s['total_recommendations']}场 (debug_sample)")
    targets = [
        ("总推荐≥300", fp.get('total_recommendations', 0), 300),
        ("已结算≥200(有收盘)", fp.get('has_closing_data', 0), 200),
        ("四分之一盘≥50", fp.get('quarter_count', 0), 50),
    ]
    for label, current, target in targets:
        pct = min(current / target * 100, 100)
        bar = '█' * int(pct / 5) + '░' * (20 - int(pct / 5))
        print(f"  │ {label:<20} {bar} {current}/{target}")
    print(f"  └──────────────────────────────────────────")
    print()


# === HTML报表 ===

def generate_observation_html(data: dict, output_dir: str = None) -> str:
    """生成observation_report.html"""
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

    h = data["run_health"]
    s = data["sample_stats"]
    sb = data["settlement_breakdown"]
    clv = data["clv_distribution"]
    ht = data["by_handicap_type"]
    nt = data["null_tracking"]
    na = data["neutral_analysis"]

    league_rows = "".join(
        f"<tr><td>{lg['league']}</td><td>{lg['total']}</td><td>{lg['settled']}</td><td>{lg['hit']}</td></tr>"
        for lg in data["by_league"]
    )
    level_rows = "".join(
        f"<tr><td>{lv['level']}</td><td>{lv['total']}</td><td>{lv['settled']}</td><td>{lv['hit']}</td><td>{lv['avg_index']}</td></tr>"
        for lv in data["by_level"]
    )
    version_rows = "".join(
        f"<tr><td>{v['version']}</td><td>{v['total']}</td></tr>"
        for v in data["by_model_version"]
    )
    near_rows = "".join(
        f"<tr><td>{n['home']} vs {n['away']}</td><td>{n['league']}</td><td>{n['crown_index']}</td><td>{n['hit']}</td><td>{n['score'] or ''}</td></tr>"
        for n in data["near_threshold"]
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>观察期统计 {data['generated_at']}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
h1 {{ color: #1a1a2e; font-size: 1.4em; }}
h2 {{ color: #16213e; font-size: 1.1em; margin-top: 25px; border-bottom: 2px solid #3498db; padding-bottom: 4px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 15px 0; }}
.card {{ background: white; border-radius: 8px; padding: 12px; text-align: center; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
.card .num {{ font-size: 1.6em; font-weight: bold; color: #2c3e50; }}
.card .lbl {{ font-size: 0.75em; color: #7f8c8d; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 6px; overflow: hidden; margin: 10px 0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
th {{ background: #2c3e50; color: white; padding: 8px 10px; font-size: 0.8em; text-align: left; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #ecf0f1; font-size: 0.85em; }}
.warn {{ background: #fff3cd; padding: 10px; border-radius: 6px; margin: 10px 0; font-size: 0.85em; }}
.ok {{ background: #d4edda; padding: 10px; border-radius: 6px; margin: 10px 0; font-size: 0.85em; }}
.footer {{ color: #b2bec3; font-size: 0.7em; margin-top: 30px; text-align: center; }}
</style></head><body>
<h1>观察期统计报告</h1>
<p style="color:#666;font-size:0.85em">生成时间: {data['generated_at']} | 只读统计，不修改任何数据</p>

<h2>每日运行健康</h2>
<div class="grid">
<div class="card"><div class="num">{h['sync_matches']}</div><div class="lbl">sync比赛</div></div>
<div class="card"><div class="num">{h['track_odds_matches']}</div><div class="lbl">track有盘口</div></div>
<div class="card"><div class="num">{h['timeline_new_records']}</div><div class="lbl">timeline新增</div></div>
<div class="card"><div class="num">{h['l2_passed']}</div><div class="lbl">L2通过</div></div>
<div class="card"><div class="num">{h['level_a']}/{h['level_b']}/{h['level_c']}</div><div class="lbl">A/B/C</div></div>
<div class="card"><div class="num">{h['settled']}</div><div class="lbl">已结算</div></div>
<div class="card"><div class="num">{h['unsettled']}</div><div class="lbl">待结算</div></div>
<div class="card"><div class="num">{'✓' if h['watchdog_healthy'] else '✗'}</div><div class="lbl">watchdog</div></div>
</div>

<h2>样本积累</h2>
<div class="grid">
<div class="card"><div class="num">{s['total_recommendations']}</div><div class="lbl">总推荐</div></div>
<div class="card"><div class="num">{s['settled']}</div><div class="lbl">已结算</div></div>
<div class="card"><div class="num">{s['has_closing_data']}</div><div class="lbl">有收盘数据</div></div>
<div class="card"><div class="num">{sb['win']}/{sb['half_win']}/{sb['push']}/{sb['half_loss']}/{sb['loss']}</div><div class="lbl">W/HW/P/HL/L</div></div>
<div class="card"><div class="num">{clv['positive']}/{clv['zero']}/{clv['negative']}</div><div class="lbl">CLV +/0/-</div></div>
<div class="card"><div class="num">{clv['avg_clv'] if clv['avg_clv'] is not None else '-'}</div><div class="lbl">CLV均值</div></div>
</div>

<h2>盘口类型分布</h2>
<div class="grid">
<div class="card"><div class="num">{ht['integer']}</div><div class="lbl">整数盘</div></div>
<div class="card"><div class="num">{ht['quarter_025']}</div><div class="lbl">0.25盘</div></div>
<div class="card"><div class="num">{ht['half_050']}</div><div class="lbl">0.5盘</div></div>
<div class="card"><div class="num">{ht['quarter_075']}</div><div class="lbl">0.75盘</div></div>
<div class="card"><div class="num">{ht['null']}</div><div class="lbl">NULL</div></div>
</div>

<h2>按联赛</h2>
<table><tr><th>联赛</th><th>总推荐</th><th>已结算</th><th>命中</th></tr>{league_rows}</table>

<h2>按等级</h2>
<table><tr><th>等级</th><th>总推荐</th><th>已结算</th><th>命中</th><th>均指数</th></tr>{level_rows}</table>

<h2>按模型版本</h2>
<table><tr><th>版本</th><th>记录数</th></tr>{version_rows}</table>

<h2>NULL追踪(不静默当0)</h2>
<div class="{'warn' if nt['null_model_version'] > 0 else 'ok'}">
model_version NULL: {nt['null_model_version']} | model_weights NULL: {nt['null_model_weights']} | 
ai_decision NULL: {nt['null_ai_decision']} | odds_water NULL: {nt['null_odds_water']} | 
CLV NULL: {nt['null_clv']}<br>
完整记录: {nt['complete_records']}/{nt['total_records']}
</div>

<h2>Neutral分析</h2>
<p>总neutral: {na['total_neutral']} | 数据不足: {na['due_to_low_completeness']} | 有数据仍neutral: {na['has_data_but_neutral']}</p>

<h2>距门槛(75)1~3分</h2>
<table><tr><th>比赛</th><th>联赛</th><th>指数</th><th>命中</th><th>比分</th></tr>{near_rows}</table>

<h2>观察期进度</h2>
<div class="grid">
<div class="card"><div class="num">{s['total_recommendations']}/300</div><div class="lbl">总推荐</div></div>
<div class="card"><div class="num">{s['has_closing_data']}/200</div><div class="lbl">有收盘数据</div></div>
<div class="card"><div class="num">{ht['quarter_025']+ht['quarter_075']}/50</div><div class="lbl">四分之一盘</div></div>
</div>

<div class="footer">皇冠AI观察期 | 只读统计 | 不修改权重/阈值/推荐方向 | {data['generated_at']}</div>
</body></html>"""

    path = os.path.join(output_dir, "observation_report.html")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    log.info(f"[观察] 报表: {path}")
    return path
