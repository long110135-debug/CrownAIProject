"""
皇冠AI赛事研判系统 - 唯一业务流程入口 v1.3

所有分析逻辑只在这里。
scheduler.py 和 main.py 都只是调用本模块的函数。

职责:
  sync_today()       同步今日赛事
  track_odds()       更新盘口时间线
  analyze_matches()  三层过滤 + 五模型分析 + 推荐
  close_odds()       锁定临场收盘赔率
  settle_matches()   赛果结算
  generate_reports() 日报 + CLV报表
  run_full()         完整流程(手动一键)
"""
import time
from datetime import datetime, timedelta
from typing import List, Optional

from utils.logger import log
from utils.database import (
    get_connection, save_match, save_prediction,
    save_filter_funnel, save_performance_log, get_latest_odds,
)
from config.settings import MODEL_VERSION


# === 队名映射 ===
def _get_team_maps():
    from pipeline.team_enrich import TEAM_NAME_MAP
    en_to_cn = {v: k for k, v in TEAM_NAME_MAP.items()}
    return TEAM_NAME_MAP, en_to_cn


# ═══════════════════════════════════════════
# 1. 同步今日赛事
# ═══════════════════════════════════════════

def sync_today() -> int:
    """从API-Football同步今日全部目标联赛赛事，返回同步场次"""
    from scraper.apifootball_data import APIFootballClient, ALL_LEAGUE_IDS
    _, en_to_cn = _get_team_maps()

    today = datetime.now().strftime('%Y-%m-%d')
    now = datetime.now()
    season = now.year if now.month >= 7 else now.year - 1
    nordic_leagues = {113, 114, 244, 103, 119}

    client = APIFootballClient()
    if not client.api_key:
        log.error("[sync] API-Football不可用")
        return 0

    count = 0
    for lid, name in ALL_LEAGUE_IDS.items():
        try:
            s = now.year if lid in nordic_leagues else season
            data = client._request('fixtures', {'date': today, 'league': lid, 'season': s})
            if data and data.get('results', 0) > 0:
                for f in data['response']:
                    home_en = f['teams']['home']['name']
                    away_en = f['teams']['away']['name']
                    home_cn = en_to_cn.get(home_en, home_en)
                    away_cn = en_to_cn.get(away_en, away_en)
                    kickoff = client._format_time(f['fixture']['date'])
                    match_id = f"CROWN_{name}_{home_cn}_{away_cn}_{today}"

                    save_match({
                        'match_id': match_id, 'league': name, 'league_tier': 1,
                        'home_team': home_cn, 'away_team': away_cn,
                        'match_time': kickoff, 'status': 'pending',
                    })
                    count += 1
        except Exception as e:
            log.warning(f"[sync] {name} 获取失败: {e}")

    log.info(f"[sync] 同步完成: {count}场 ({today})")
    return count


# ═══════════════════════════════════════════
# 2. 更新盘口时间线
# ═══════════════════════════════════════════

def track_odds() -> int:
    """从API-Football获取盘口写入时间线，返回更新场次"""
    from scraper.apifootball_data import APIFootballClient
    from scraper.apifootball_odds import fetch_odds_for_fixture
    from scraper.crown_odds_collector import save_api_odds
    from pipeline.odds_tracker import detect_odds_changes, lock_closing_odds

    client = APIFootballClient()
    if not client.api_key:
        log.warning("[track] API-Football不可用")
        return 0

    from utils.timeutil import today_utc_range
    utc_start, utc_end = today_utc_range()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT match_id, home_team, away_team, league FROM matches
        WHERE status = 'pending' AND match_time >= ? AND match_time <= ?
    """, (utc_start, utc_end))
    pending = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not pending:
        return 0

    odds_count = 0
    for m in pending:
        # 用比赛自身UTC日期查询fixture(match_time为UTC ISO, 前10字符=UTC日期)
        match_date = str(m.get('match_time', ''))[:10]
        fixture_id = _resolve_fixture_id(client, m, match_date)
        if fixture_id:
            odds = fetch_odds_for_fixture(client, fixture_id)
            if odds and odds.get("handicap"):
                source = f"api-football({odds.get('bookmaker', '')})"
                if save_api_odds(m['match_id'], odds, source=source):
                    odds_count += 1
        time.sleep(0.5)

    log.info(f"[track] API-Football盘口: {odds_count}/{len(pending)}场")

    # 检测变化 + 锁定收盘
    try:
        changes = detect_odds_changes()
        if changes:
            log.info(f"[track] 盘口变化: {len(changes)}场")
    except Exception as e:
        log.warning(f"[track] 变化检测异常: {e}")

    try:
        lock_closing_odds(hours_before_kickoff=1.0)
    except Exception as e:
        log.warning(f"[track] 收盘锁定异常: {e}")

    return odds_count


# ═══════════════════════════════════════════
# 3. 三层过滤 + 五模型分析 + 推荐
# ═══════════════════════════════════════════

def analyze_matches(hours_ahead: int = 6) -> dict:
    """
    分析即将开赛的比赛(三层过滤)
    
    返回: {
        "analyzed": int,
        "level_a": int, "level_b": int, "level_c": int,
        "l2_rejected": int,
        "results": [analysis...],
    }
    """
    from models.strength_model import StrengthModel
    from models.handicap_model import HandicapModel
    from models.squad_model import SquadModel
    from models.market_model import MarketModel
    from models.ai_referee import AIRefereeModel
    from pipeline.crown_score import calc_crown_index
    from pipeline.match_filter import filter_by_data_quality, filter_by_recommendation_quality
    from utils.timeutil import now_utc

    now = now_utc()
    window = now + timedelta(hours=hours_ahead)

    # 获取pending比赛
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM matches WHERE status = 'pending'")
    pending = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # 时间窗口过滤
    to_check = []
    for m in pending:
        kickoff = _parse_time(m['match_time'])
        if kickoff and now < kickoff <= window:
            to_check.append(m)

    if not to_check:
        log.info(f"[analyze] 无{hours_ahead}小时内开赛的比赛")
        return {"analyzed": 0, "level_a": 0, "level_b": 0, "level_c": 0, "l2_rejected": 0, "results": []}

    log.info(f"[analyze] {hours_ahead}小时内开赛: {len(to_check)}场")

    # === Layer 2: 数据过滤 ===
    l2_passed = []
    l2_rejected = []
    for m in to_check:
        result = filter_by_data_quality(m['match_id'], m)
        if result["pass"]:
            m["_data_quality"] = result["score"]
            l2_passed.append(m)
        else:
            l2_rejected.append((m['home_team'], m['away_team'], result["reasons"]))

    log.info(f"[L2] {len(to_check)}场 → {len(l2_passed)}场通过, {len(l2_rejected)}场数据不足")
    for home, away, reasons in l2_rejected[:5]:
        log.info(f"  淘汰: {home} vs {away} ({'; '.join(reasons)})")

    if not l2_passed:
        return {"analyzed": 0, "level_a": 0, "level_b": 0, "level_c": 0,
                "l2_rejected": len(l2_rejected), "results": []}

    # === 五模型分析 ===
    from utils.database import get_team_stats
    sm, hm, sqm, mm, ai = StrengthModel(), HandicapModel(), SquadModel(), MarketModel(), AIRefereeModel()
    results = []
    a_count = b_count = c_count = 0

    for m in l2_passed:
        match_id = m['match_id']
        odds_data = _build_odds_data(match_id)

        # 预取球队数据注入模型(模型自身不访问DB)
        home_stats = get_team_stats(m['home_team'], m['league'])
        away_stats = get_team_stats(m['away_team'], m['league'])

        mi = {'match_id': match_id, 'home_team': m['home_team'], 'away_team': m['away_team'],
              'league': m['league'], 'match_time': m['match_time'], 'odds': odds_data,
              'odds_history': [], 'home_stats': home_stats or {}, 'away_stats': away_stats or {},
              'home_squad': {}, 'away_squad': {}}

        sr = sm.analyze(mi)
        hr = hm.analyze(mi)
        sqr = sqm.analyze(mi)
        mr = mm.analyze(mi)
        model_results = {'strength': sr, 'handicap': hr, 'squad': sqr, 'market': mr}
        mi['model_results'] = model_results
        mi['strength_direction'] = sr.get('direction', 'neutral')
        ar = ai.analyze(mi)
        model_results['ai_referee'] = ar
        crown = calc_crown_index(model_results, odds_data)

        completeness = 40 + (40 if odds_data['asian_handicap'] else 0) + (10 if sr.get('direction') != 'neutral' else 0)

        analysis = {'match_id': match_id, 'home_team': m['home_team'], 'away_team': m['away_team'],
                    'league': m['league'], 'match_time': m['match_time'],
                    'model_version': MODEL_VERSION, 'model_results': model_results,
                    'crown_index': crown['crown_index'], 'crown_rating': crown['rating'],
                    'crown_breakdown': crown['breakdown'], 'odds': odds_data,
                    'data_completeness': completeness,
                    'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

        # === Layer 3: 推荐过滤 ===
        l3 = filter_by_recommendation_quality(analysis)
        if l3["pass"]:
            level = "A" if crown['crown_index'] >= 80 else "B"
            if level == "A":
                a_count += 1
            else:
                b_count += 1
            log.info(f"  ★ [{level}] {m['home_team']} vs {m['away_team']} 指数:{crown['crown_index']} 一致性:{l3['model_agreement']:.0%}")
        else:
            level = "C"
            c_count += 1
            log.info(f"  ○ [C] {m['home_team']} vs {m['away_team']} 指数:{crown['crown_index']} ({'; '.join(l3['reasons'][:2])})")

        analysis['level'] = level
        results.append(analysis)

        # 写入prediction_history(含当时完整快照)
        from config.settings import MODEL_WEIGHTS
        save_prediction({'match_id': match_id, 'league': m['league'],
            'home_team': m['home_team'], 'away_team': m['away_team'],
            'kickoff': m['match_time'],
            'asian_open': odds_data.get('open_handicap', ''),
            'asian_live': odds_data.get('current_handicap', ''),
            'crown_index': crown['crown_index'],
            'strength_score': sr.get('score', 0), 'handicap_score': hr.get('score', 0),
            'market_score': mr.get('score', 0), 'squad_score': sqr.get('score', 0),
            'ai_score': ar.get('score', 0), 'data_completeness': completeness,
            'recommend': sr.get('direction', 'neutral'), 'level': level,
            'confidence': crown['crown_index'],
            'model_version': MODEL_VERSION,
            'model_weights': MODEL_WEIGHTS,
            'ai_decision': ar.get('details', {}).get('decision', ''),
            'odds_home_water': odds_data.get('home_odds', 0),
            'odds_away_water': odds_data.get('away_odds', 0)})

        # === 影子对照实验: 记录legacy vs consensus ===
        from pipeline.recommender import _consensus_direction
        from utils.database import save_experiment
        legacy_dir = sr.get('direction', 'neutral')
        consensus_dir = _consensus_direction(model_results)
        consensus_reason = _build_consensus_reason(model_results, consensus_dir)
        save_experiment({
            'match_id': match_id,
            'model_version': MODEL_VERSION,
            'legacy_recommend': legacy_dir,
            'consensus_recommend': consensus_dir,
            'consensus_weights': MODEL_WEIGHTS,
            'consensus_reason': consensus_reason,
        })

    log.info(f"[analyze] 完成: {len(results)}场 (A:{a_count} B:{b_count} C:{c_count}, L2淘汰:{len(l2_rejected)})")

    # 保存漏斗统计
    _save_funnel(len(to_check), len(l2_passed), len(results), a_count, b_count, c_count)

    return {"analyzed": len(results), "level_a": a_count, "level_b": b_count,
            "level_c": c_count, "l2_rejected": len(l2_rejected), "results": results}


# ═══════════════════════════════════════════
# 4. 锁定收盘赔率
# ═══════════════════════════════════════════

def close_odds():
    """锁定开赛前1小时的收盘赔率"""
    from pipeline.odds_tracker import lock_closing_odds
    log.info("[close] 锁定临场收盘赔率...")
    lock_closing_odds(hours_before_kickoff=1.0)


# ═══════════════════════════════════════════
# 4.5 临场二次分析(开赛前15~45分钟)
# ═══════════════════════════════════════════

def prematch_analyze(window_min: int = 45, window_max: int = 15) -> dict:
    """
    临场二次分析: 对已有首次分析、即将开赛的比赛，用最新盘口重跑五模型。

    只更新 prematch_* 列，不覆盖首次分析结果，不触碰结算字段。

    参数:
        window_min: 窗口上限(开赛前N分钟开始触发)，默认45
        window_max: 窗口下限(开赛前N分钟截止)，默认15

    返回: {"updated": int, "matches": [...]}
    """
    from models.strength_model import StrengthModel
    from models.handicap_model import HandicapModel
    from models.squad_model import SquadModel
    from models.market_model import MarketModel
    from models.ai_referee import AIRefereeModel
    from pipeline.crown_score import calc_crown_index
    from pipeline.recommender import _consensus_direction
    from utils.database import (
        get_team_stats, save_prematch_update, save_prematch_experiment,
        get_latest_odds,
    )
    from scraper.apifootball_data import APIFootballClient

    from utils.timeutil import now_utc

    now = now_utc()
    today = now.strftime('%Y-%m-%d')

    # 计算时间窗口: 开赛前 window_min ~ window_max 分钟
    win_start = now + timedelta(minutes=window_max)   # 最近的比赛(15分钟后)
    win_end = now + timedelta(minutes=window_min)     # 最远的比赛(45分钟后)

    # 找出已有首次分析、未结算、未做过临场分析的pending比赛，再用aware时间过滤窗口
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT m.match_id, m.league, m.home_team, m.away_team, m.match_time
        FROM matches m
        JOIN prediction_history p ON m.match_id = p.match_id
        WHERE m.status = 'pending'
          AND p.settled_at IS NULL
          AND p.prematch_at IS NULL
    """)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    candidates = []
    for m in rows:
        kickoff = _parse_time(m['match_time'])
        if kickoff and win_start <= kickoff <= win_end:
            candidates.append(m)

    if not candidates:
        log.info(f"[prematch] 无{window_max}~{window_min}分钟内待二次分析的比赛")
        return {"updated": 0, "matches": []}

    log.info(f"[prematch] 临场窗口: {len(candidates)}场待二次分析")

    # 初始化模型
    sm, hm, sqm, mm, ai = StrengthModel(), HandicapModel(), SquadModel(), MarketModel(), AIRefereeModel()
    client = APIFootballClient()
    updated = []

    for m in candidates:
        match_id = m['match_id']

        # Step 1: 强制刷新最新盘口(写入timeline)
        _prematch_refresh_odds(client, m, today)

        # Step 2: 用最新盘口(含真实开盘→当前变动)重跑五模型
        odds_data = _build_odds_data(match_id)
        if not odds_data.get('asian_handicap'):
            log.info(f"  跳过 {m['home_team']} vs {m['away_team']}: 无盘口数据")
            continue

        home_stats = get_team_stats(m['home_team'], m['league'])
        away_stats = get_team_stats(m['away_team'], m['league'])

        mi = {'match_id': match_id, 'home_team': m['home_team'], 'away_team': m['away_team'],
              'league': m['league'], 'match_time': m['match_time'], 'odds': odds_data,
              'odds_history': [], 'home_stats': home_stats or {}, 'away_stats': away_stats or {},
              'home_squad': {}, 'away_squad': {}}

        sr = sm.analyze(mi)
        hr = hm.analyze(mi)
        sqr = sqm.analyze(mi)
        mr = mm.analyze(mi)
        model_results = {'strength': sr, 'handicap': hr, 'squad': sqr, 'market': mr}
        mi['model_results'] = model_results
        mi['strength_direction'] = sr.get('direction', 'neutral')
        ar = ai.analyze(mi)
        model_results['ai_referee'] = ar
        crown = calc_crown_index(model_results, odds_data)

        # Step 3: 写入prematch列(不覆盖首次分析)
        prematch_rec = {
            'prematch_at': now.strftime('%Y-%m-%d %H:%M:%S'),
            'prematch_handicap': odds_data.get('asian_handicap', ''),
            'prematch_home_water': odds_data.get('home_odds', 0),
            'prematch_away_water': odds_data.get('away_odds', 0),
            'prematch_crown_index': crown['crown_index'],
            'prematch_recommend': sr.get('direction', 'neutral'),
            'prematch_strength_score': sr.get('score', 0),
            'prematch_handicap_score': hr.get('score', 0),
            'prematch_market_score': mr.get('score', 0),
        }
        save_prematch_update(match_id, prematch_rec)

        # Step 4: 更新影子实验临场共识
        consensus_dir = _consensus_direction(model_results)
        consensus_reason = _build_consensus_reason(model_results, consensus_dir)
        save_prematch_experiment(match_id, consensus_dir, consensus_reason)

        updated.append({
            'match_id': match_id,
            'home_team': m['home_team'],
            'away_team': m['away_team'],
            'prematch_handicap': odds_data.get('asian_handicap', ''),
            'prematch_crown_index': crown['crown_index'],
            'prematch_recommend': sr.get('direction', 'neutral'),
            'consensus': consensus_dir,
        })

        log.info(f"  ✓ {m['home_team']} vs {m['away_team']} | "
                 f"盘口:{odds_data.get('asian_handicap', '')} "
                 f"主水:{odds_data.get('home_odds', '')} "
                 f"指数:{crown['crown_index']} "
                 f"legacy:{sr.get('direction', 'neutral')} "
                 f"consensus:{consensus_dir}")

    log.info(f"[prematch] 完成: {len(updated)}场临场更新")
    return {"updated": len(updated), "matches": updated}


def _prematch_refresh_odds(client, match: dict, date_str: str) -> Optional[dict]:
    """临场强制刷新一次盘口数据，返回最新odds dict或None"""
    try:
        from scraper.apifootball_odds import fetch_odds_for_fixture
        from scraper.crown_odds_collector import save_api_odds

        fixture_id = _resolve_fixture_id(client, match, date_str)
        if not fixture_id:
            return None
        odds = fetch_odds_for_fixture(client, fixture_id)
        if odds and odds.get("handicap"):
            source = f"api-football({odds.get('bookmaker', '')})"
            save_api_odds(match['match_id'], odds, source=source)
            return odds
    except Exception as e:
        log.warning(f"[prematch] 盘口刷新失败 {match['home_team']}: {e}")
    return None


# ═══════════════════════════════════════════
# 5. 赛果结算
# ═══════════════════════════════════════════

def settle_matches(target_date: str = None):
    """结算已结束比赛"""
    from settle import auto_settle
    log.info("[settle] 自动结算...")
    auto_settle(target_date)


# ═══════════════════════════════════════════
# 6. 报表生成
# ═══════════════════════════════════════════

def generate_reports():
    """生成日报 + CLV报表 + 盘口画像"""
    from pipeline.daily_report import generate_daily_report
    from pipeline.clv_analysis import generate_clv_report
    from pipeline.odds_profile import generate_all_profiles

    log.info("[report] 生成报表...")
    generate_all_profiles()
    generate_daily_report()
    generate_clv_report()
    log.info("[report] 报表完成")


# ═══════════════════════════════════════════
# 7. 完整流程(手动一键)
# ═══════════════════════════════════════════

def run_full(target_leagues: List[str] = None):
    """
    完整流程: 同步→盘口→分析→报表
    供main.py手动调用
    """
    from config.settings import VERSION

    print(f"\n{'='*50}")
    print(f"  皇冠AI赛事研判系统 {VERSION}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}\n")

    # Step 1: 同步
    print("=== Step 1: 同步今日赛事 ===")
    count = sync_today()
    print(f"  同步: {count}场")

    # Step 2: 盘口
    print("\n=== Step 2: 更新盘口 ===")
    odds_count = track_odds()
    print(f"  盘口更新: {odds_count}场")

    # Step 3: 分析(24小时窗口)
    print("\n=== Step 3: 三层过滤 + 模型分析 ===")
    result = analyze_matches(hours_ahead=24)
    print(f"  分析: {result['analyzed']}场 | A:{result['level_a']} B:{result['level_b']} C:{result['level_c']}")

    # Step 4: 报表
    print("\n=== Step 4: 生成报表 ===")
    generate_reports()

    # 保存performance_log
    today = datetime.now().strftime('%Y-%m-%d')
    save_performance_log(today, {
        "matches_analyzed": result['analyzed'],
        "recommendations_a": result['level_a'],
        "recommendations_b": result['level_b'],
        "notes": f"同步{count}场, 盘口{odds_count}场, L2淘汰{result['l2_rejected']}场",
    })

    print(f"\n{'='*50}")
    print(f"  完成! 分析{result['analyzed']}场, A级{result['level_a']}个")
    print(f"{'='*50}")

    return result


# ═══════════════════════════════════════════
# 内部工具
# ═══════════════════════════════════════════

def _resolve_fixture_id(client, match: dict, date_str: str):
    """通过API-Football查找比赛的fixture_id"""
    from scraper.apifootball_data import ALL_LEAGUE_IDS
    cn_to_en, _ = _get_team_maps()

    league_name = match.get('league', '')
    league_id = None
    for lid, name in ALL_LEAGUE_IDS.items():
        if name == league_name:
            league_id = lid
            break
    if not league_id:
        return None

    home_en = cn_to_en.get(match['home_team'], match['home_team'])
    away_en = cn_to_en.get(match['away_team'], match['away_team'])

    now = datetime.now()
    season = now.year if league_id in {113, 114, 244, 103, 119} else (now.year if now.month >= 7 else now.year - 1)

    data = client._request('fixtures', {'date': date_str, 'league': league_id, 'season': season})
    if data and data.get('response'):
        for f in data['response']:
            fh = f['teams']['home']['name']
            fa = f['teams']['away']['name']
            if fh == home_en and fa == away_en:
                return f['fixture']['id']
            if home_en.lower() in fh.lower() and away_en.lower() in fa.lower():
                return f['fixture']['id']
    return None


from utils.helpers import parse_match_time as _parse_time


def _build_odds_data(match_id: str) -> dict:
    """
    从odds_timeline构建真实odds_data(含开盘→当前的盘口变动)。

    替代旧的硬编码(change_type='不变'/open_handicap=''/over_under='')。
    用utils.odds_math.compute_change(升盘/降盘判断的唯一实现)计算真实变动类型，
    让handicap模型和crown_index反映真实盘口变化，解除72.5的管线天花板。
    """
    from utils.database import get_opening_odds, get_latest_odds
    from utils.odds_math import compute_change

    latest = get_latest_odds(match_id)
    if not latest:
        return {
            'asian_handicap': '', 'home_odds': 0.95, 'away_odds': 0.95,
            'open_handicap': '', 'current_handicap': '',
            'change_type': '不变', 'over_under': '', 'over_odds': 0, 'under_odds': 0,
        }

    opening = get_opening_odds(match_id) or latest

    curr_hdp = latest.get('handicap', '') or ''
    open_hdp = opening.get('handicap', '') or ''
    curr_hw = latest.get('home_water') or 0.95
    open_hw = opening.get('home_water') or 0.95
    curr_aw = latest.get('away_water') or 0.95
    open_aw = opening.get('away_water') or 0.95

    change = compute_change(open_hdp, curr_hdp, open_hw, curr_hw, open_aw, curr_aw)

    return {
        'asian_handicap': curr_hdp,
        'home_odds': curr_hw,
        'away_odds': curr_aw,
        'open_handicap': open_hdp,
        'current_handicap': curr_hdp,
        'change_type': change.get('change_type', '不变'),
        'over_under': latest.get('over_line', '') or '',
        'over_odds': latest.get('over_water', 0) or 0,
        'under_odds': latest.get('under_water', 0) or 0,
    }


def _build_consensus_reason(model_results: dict, consensus_dir: str) -> str:
    """
    构建共识原因字符串，记录每个模型的投票详情。
    格式: 每模型方向+权重+有效票 | 总有效权重 | 胜出权重 | 是否平票 | neutral是否参与
    """
    from config.settings import MODEL_WEIGHTS
    parts = []
    home_w = away_w = draw_w = 0.0
    total_effective = 0.0

    for name in ("strength", "handicap", "squad", "market", "ai_referee"):
        result = model_results.get(name, {})
        if not isinstance(result, dict):
            parts.append(f"{name}:missing")
            continue
        direction = result.get("direction", "neutral")
        confidence = result.get("confidence", 0) / 100
        weight = MODEL_WEIGHTS.get(name, 0.1)
        effective = weight * confidence

        # ai_referee是裁决模型，direction为多数票复制，不计入方向投票(仅记录)
        if name == "ai_referee":
            parts.append(f"{name}:{direction}(excluded_referee)")
            continue

        if direction == "home":
            home_w += effective
        elif direction == "away":
            away_w += effective
        elif direction == "draw":
            draw_w += effective
        # neutral不参与投票

        if direction != "neutral":
            total_effective += effective
        parts.append(f"{name}:{direction}(w={weight},eff={effective:.3f})")

    winner_w = max(home_w, away_w, draw_w)
    is_tie = sum(1 for w in (home_w, away_w, draw_w) if abs(w - winner_w) < 0.001) > 1

    parts.append(f"total_eff={total_effective:.3f}")
    parts.append(f"winner={consensus_dir}(w={winner_w:.3f})")
    parts.append(f"tie={'Y' if is_tie else 'N'}")
    parts.append("neutral_excluded")

    return " | ".join(parts)


def _save_funnel(after_l1, after_l2, after_l3, a, b, c):
    """保存漏斗统计"""
    try:
        from utils.timeutil import today_shanghai, today_utc_range
        today = today_shanghai()  # log_date用北京自然日
        utc_start, utc_end = today_utc_range()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM matches WHERE match_time >= ? AND match_time <= ?",
                       (utc_start, utc_end))
        total = cursor.fetchone()[0]
        conn.close()
        save_filter_funnel(today, {
            "total_synced": total, "after_l1": after_l1, "after_l2": after_l2,
            "after_l3": after_l3, "level_a": a, "level_b": b, "level_c": c,
        })
    except Exception:
        pass
