"""
皇冠AI赛事研判系统 - 全自动赛果结算 v1.2
凌晨自动运行: API获取赛果→写match_result→结算预测→计算CLV→模型贡献分析

用法:
  python3 settle.py              自动结算昨天比赛
  python3 settle.py --date 2026-07-21  指定日期
  python3 settle.py --all        结算所有未结算
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
from utils.database import (
    get_connection, get_unsettled_predictions, settle_prediction,
    get_hit_stats, save_match_result, get_match_result,
    save_model_contribution, save_performance_log,
)
from utils.logger import log
from pipeline.odds_tracker import settle_match_clv


def auto_settle(target_date: str = None, settle_all: bool = False):
    """
    全自动结算流程:
    1. 获取未结算预测
    2. API-Football获取赛果
    3. 写入match_result表
    4. 结算prediction_history
    5. 计算CLV
    6. 模型贡献分析
    7. 更新performance_log
    """
    if not target_date:
        target_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')

    print(f"\n{'═'*50}")
    print(f"  皇冠AI 自动结算 v1.2")
    print(f"  目标日期: {target_date}")
    print(f"{'═'*50}\n")

    # 获取未结算预测
    unsettled = get_unsettled_predictions()
    if not unsettled:
        print("  无未结算预测。")
        return {"settled": 0, "hit": 0}

    # 筛选目标
    if settle_all:
        target_preds = unsettled
    else:
        target_preds = [p for p in unsettled if _match_date(p, target_date)]
        if not target_preds:
            # 扩展搜索范围(前后1天)
            alt = (datetime.strptime(target_date, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
            target_preds = [p for p in unsettled if _match_date(p, alt)]

    if not target_preds:
        print(f"  {target_date} 无待结算比赛。未结算总数: {len(unsettled)}")
        return {"settled": 0, "hit": 0}

    print(f"  待结算: {len(target_preds)}场")

    # API-Football获取赛果
    from scraper.apifootball_data import APIFootballClient
    client = APIFootballClient()
    if not client.api_key:
        print("  ✗ API-Football不可用，无法自动结算。")
        return {"settled": 0, "hit": 0, "error": "no_api_key"}

    # 队名映射
    try:
        from pipeline.team_enrich import TEAM_NAME_MAP
    except ImportError:
        TEAM_NAME_MAP = {}

    settled_count = 0
    hit_count = 0
    results_summary = []

    for pred in target_preds:
        home_cn = pred['home_team']
        away_cn = pred['away_team']
        home_en = TEAM_NAME_MAP.get(home_cn, home_cn)
        away_en = TEAM_NAME_MAP.get(away_cn, away_cn)

        # 查找赛果
        result = _find_match_result(client, home_en, away_en, target_date)
        if not result:
            continue

        home_goals = result['home_goals']
        away_goals = result['away_goals']
        score_str = f"{home_goals}-{away_goals}"

        # 判断胜者
        if home_goals > away_goals:
            winner = "home"
        elif home_goals < away_goals:
            winner = "away"
        else:
            winner = "draw"

        # 让球结果
        handicap_result = _calc_handicap_result(pred, home_goals, away_goals)
        # 大小球结果
        ou_result = _calc_ou_result(pred, home_goals, away_goals)

        # 写入match_result表
        save_match_result(pred['match_id'], home_goals, away_goals, winner,
                         handicap_result, ou_result, source="api-football")

        # 判断命中(唯一结算函数: 按推荐方向+盘口+比分)
        from utils.odds_math import settle_asian_handicap
        recommend = pred.get('recommend', '')
        asian_line = pred.get('asian_live') or pred.get('asian_open') or ''
        hit_result = settle_asian_handicap(recommend, asian_line, home_goals, away_goals)
        # 整数hit向后兼容: win/half_win=1命中, loss/half_loss=0未中, push/no_bet/invalid=2不参与命中率
        if hit_result in ("win", "half_win"):
            hit = 1
            error_reason = ""
        elif hit_result in ("loss", "half_loss"):
            hit = 0
            error_reason = _analyze_error(pred, winner, score_str)
        else:
            hit = 2  # push/no_bet/invalid 不计入命中率
            error_reason = ""

        # 结算预测
        settle_prediction(pred['match_id'], winner, score_str, hit, error_reason,
                          hit_result=hit_result)

        # 计算CLV
        settle_match_clv(pred['match_id'])

        # 模型贡献分析
        _analyze_model_contribution(pred, hit)

        # L4: 结果验证层
        _save_validation_record(pred, hit, winner, score_str, handicap_result)

        # 影子对照实验结算
        _settle_shadow_experiment(pred, home_goals, away_goals)

        settled_count += 1
        if hit == 1:
            hit_count += 1

        icon = "✓" if hit == 1 else "✗"
        print(f"  {icon} {home_cn} {score_str} {away_cn} | 推荐:{recommend} 实际:{winner}")
        if error_reason:
            print(f"    错因: {error_reason}")

        results_summary.append({
            "match_id": pred['match_id'], "hit": hit,
            "home": home_cn, "away": away_cn, "score": score_str,
        })

    # 汇总
    print(f"\n  {'─'*44}")
    if settled_count > 0:
        print(f"  结算: {settled_count}场 | 命中: {hit_count} | 命中率: {hit_count/settled_count*100:.1f}%")
    else:
        print("  未找到匹配赛果。")

    # 分级统计
    stats = get_hit_stats()
    if stats['total'] > 0:
        print(f"\n  累计统计:")
        for lv in ['A', 'B', 'C']:
            s = stats['by_level'].get(lv)
            if s:
                print(f"    {lv}级: {s['total']}场 命中{s['hit']} {s['hit_rate']}%")

    # CLV统计
    _print_clv_stats()

    # 更新performance_log
    _update_performance_log(target_date, settled_count, hit_count)

    print(f"\n{'═'*50}")
    return {"settled": settled_count, "hit": hit_count, "results": results_summary}


def _match_date(pred: dict, target_date: str) -> bool:
    """判断预测是否属于目标日期"""
    kickoff = pred.get('kickoff') or ''
    # 格式: "07月21日 20:00" 或 "2026-07-21 20:00"
    if target_date in kickoff:
        return True
    # 中文日期格式
    import re
    m = re.match(r'(\d{1,2})月(\d{1,2})日', kickoff)
    if m:
        d = f"{int(m.group(1)):02d}月{int(m.group(2)):02d}日"
        tm = datetime.strptime(target_date, '%Y-%m-%d')
        target_cn = f"{tm.month:02d}月{tm.day:02d}日"
        return d == target_cn
    return False


def _find_match_result(client, home_en: str, away_en: str, date_str: str):
    """从API-Football查找比赛结果"""
    for offset in [0, -1, 1]:
        d = (datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=offset)).strftime('%Y-%m-%d')
        data = client._request("fixtures", {"date": d, "status": "FT"})
        if not data:
            continue
        for fixture in data.get("response", []):
            fh = fixture.get("teams", {}).get("home", {}).get("name", "")
            fa = fixture.get("teams", {}).get("away", {}).get("name", "")
            if fh == home_en and fa == away_en:
                goals = fixture.get("goals", {})
                return {"home_goals": goals.get("home", 0), "away_goals": goals.get("away", 0)}
    return None


def _calc_handicap_result(pred: dict, home_goals: int, away_goals: int) -> str:
    """
    计算让球结果(支持整数盘/半球盘/四分之一盘)
    
    返回值:
      home_cover  - 主队赢盘(全赢)
      away_cover  - 客队赢盘(全输)
      push        - 走盘(整数盘恰好让平)
      half_win    - 半赢(四分之一盘，一半赢一半走)
      half_loss   - 半输(四分之一盘，一半输一半走)
      ""          - 无盘口数据
    """
    from utils.odds_math import handicap_to_number
    asian = pred.get('asian_live') or pred.get('asian_open') or ''
    hdp = handicap_to_number(asian)
    if hdp == 0 and not asian:
        return ""

    # 净胜球差(主队视角)
    diff = home_goals - away_goals
    # 让球后的边际: 正=主队覆盖, 负=客队覆盖
    margin = diff - hdp

    # 检测是否为四分之一盘(x.25 或 x.75)
    is_quarter = abs(round(abs(hdp) * 4)) % 2 == 1

    if is_quarter:
        # 四分之一盘: 先检查±0.25(半赢/半输)，再检查全赢/全输
        if abs(margin - 0.25) < 0.01:
            return "half_win"    # 一半赢一半走
        elif abs(margin + 0.25) < 0.01:
            return "half_loss"   # 一半输一半走
        elif margin > 0.01:
            return "home_cover"
        elif margin < -0.01:
            return "away_cover"
        else:
            return "push"
    else:
        # 整数盘/半球盘: 无半赢半输
        if margin > 0.01:
            return "home_cover"
        elif margin < -0.01:
            return "away_cover"
        else:
            return "push"


def _calc_ou_result(pred: dict, home_goals: int, away_goals: int) -> str:
    """计算大小球结果"""
    # 暂无大小球数据时返回空
    return ""


def _analyze_model_contribution(pred: dict, hit: int):
    """分析模型贡献(哪个模型对结果贡献最大)"""
    scores = {
        "strength": pred.get('strength_score') or 0,
        "handicap": pred.get('handicap_score') or 0,
        "squad": pred.get('squad_score') or 0,
        "market": pred.get('market_score') or 0,
        "ai": pred.get('ai_score') or 0,
    }

    # 找最高分模型
    top_model = max(scores, key=scores.get) if any(scores.values()) else ""
    total = sum(scores.values()) or 1
    top_contribution = round(scores[top_model] / total * 100, 1) if top_model else 0

    # 归因: 各模型占比
    attribution = {k: round(v / total * 100, 1) for k, v in scores.items()}

    save_model_contribution(pred['match_id'], {
        "hit": hit,
        "strength_score": scores["strength"],
        "handicap_score": scores["handicap"],
        "squad_score": scores["squad"],
        "market_score": scores["market"],
        "ai_score": scores["ai"],
        "top_model": top_model,
        "top_contribution": top_contribution,
        "attribution": attribution,
    })


def _save_validation_record(pred: dict, hit: int, winner: str, score_str: str, handicap_result: str):
    """L4: 写入结果验证记录"""
    from utils.database import save_validation_record, get_closing_odds, get_odds_profile

    match_id = pred['match_id']

    # CLV
    clv_hdp = None
    clv_water = None
    try:
        from utils.database import calc_clv
        clv = calc_clv(match_id)
        if clv:
            clv_hdp = clv.get("clv_handicap")
            clv_water = clv.get("clv_water")
    except Exception:
        pass

    # 盘口画像
    odds_pattern = ""
    try:
        profile = get_odds_profile(match_id)
        if profile:
            odds_pattern = profile.get("pattern_type", "")
    except Exception:
        pass

    # 赢盘判断
    cover = None
    if handicap_result == "home_cover" and pred.get('recommend') == 'home':
        cover = 1
    elif handicap_result == "away_cover" and pred.get('recommend') == 'away':
        cover = 1
    elif handicap_result in ("home_cover", "away_cover"):
        cover = 0
    # push或无盘口时cover=None

    save_validation_record(match_id, {
        "league": pred.get("league", ""),
        "level": pred.get("level", ""),
        "crown_index": pred.get("crown_index"),
        "data_completeness": pred.get("data_completeness"),
        "strength_score": pred.get("strength_score"),
        "handicap_score": pred.get("handicap_score"),
        "squad_score": pred.get("squad_score"),
        "market_score": pred.get("market_score"),
        "ai_score": pred.get("ai_score"),
        "recommend_direction": pred.get("recommend", ""),
        "actual_result": winner,
        "result_score": score_str,
        "hit": hit,
        "cover": cover,
        "clv_handicap": clv_hdp,
        "clv_water": clv_water,
        "odds_pattern": odds_pattern,
        "recommendation_reason": "",
    })


def _settle_shadow_experiment(pred: dict, home_goals: int, away_goals: int):
    """
    结算影子对照实验(幂等: 已结算则跳过)。

    legacy与consensus方向均调用唯一结算函数 settle_asian_handicap，
    按分析时盘口(asian_live→asian_open)与比分结算，支持半赢/半输。
    """
    from utils.database import get_connection, settle_experiment
    from utils.odds_math import settle_asian_handicap, hit_to_pnl

    match_id = pred['match_id']
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT legacy_recommend, consensus_recommend, settled_at
        FROM recommendation_experiments WHERE match_id = ?
    """, (match_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return  # 无实验记录
    if row["settled_at"]:
        return  # 已结算，幂等跳过

    asian_line = pred.get('asian_live') or pred.get('asian_open') or ''

    legacy_hit = settle_asian_handicap(row["legacy_recommend"], asian_line, home_goals, away_goals)
    consensus_hit = settle_asian_handicap(row["consensus_recommend"], asian_line, home_goals, away_goals)

    legacy_pnl = hit_to_pnl(legacy_hit)
    consensus_pnl = hit_to_pnl(consensus_hit)

    settle_experiment(match_id, legacy_hit, consensus_hit, legacy_pnl, consensus_pnl)


def _analyze_error(pred: dict, actual: str, score_str: str) -> str:
    """分析预测错误原因"""
    reasons = []
    crown_index = pred.get('crown_index', 0)
    strength = pred.get('strength_score', 0)
    handicap = pred.get('handicap_score', 0)
    market = pred.get('market_score', 0)
    completeness = pred.get('data_completeness', 0)

    if handicap and handicap < 60:
        reasons.append("盘口模型信号弱")
    if strength and strength < 60:
        reasons.append("实力评估不足")
    if market and market < 50:
        reasons.append("市场信号异常")
    if crown_index >= 75:
        reasons.append("高指数误判")
    if completeness < 80:
        reasons.append(f"数据完整度{completeness:.0f}%")
    if not reasons:
        reasons.append("正常波动")
    return "；".join(reasons)


def _print_clv_stats():
    """打印CLV统计"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT AVG(clv_handicap) as avg_clv,
                   SUM(CASE WHEN clv_handicap > 0 THEN 1 ELSE 0 END) as pos,
                   COUNT(*) as total
            FROM prediction_history WHERE hit >= 0 AND clv_handicap IS NOT NULL
        """)
        row = dict(cursor.fetchone())
        conn.close()
        if row['total'] and row['total'] > 0:
            print(f"\n  CLV: 平均{row['avg_clv']:+.3f} | 正CLV {row['pos']}/{row['total']} ({row['pos']/row['total']*100:.0f}%)")
    except Exception:
        pass


def _update_performance_log(date_str: str, settled: int, hit: int):
    """更新当日performance_log"""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) as total, AVG(crown_index) as avg_idx
            FROM prediction_history WHERE predicted_at LIKE ?
        """, (f"{date_str}%",))
        row = dict(cursor.fetchone())
        conn.close()

        save_performance_log(date_str, {
            "matches_analyzed": row['total'] or 0,
            "settled_count": settled,
            "hit_count": hit,
            "miss_count": settled - hit,
            "hit_rate": round(hit / settled * 100, 1) if settled > 0 else 0,
            "avg_crown_index": round(row['avg_idx'], 1) if row['avg_idx'] else 0,
        })
    except Exception:
        pass


if __name__ == "__main__":
    target = None
    all_mode = '--all' in sys.argv
    if '--date' in sys.argv:
        idx = sys.argv.index('--date')
        if idx + 1 < len(sys.argv):
            target = sys.argv[idx + 1]
    auto_settle(target, settle_all=all_mode)
