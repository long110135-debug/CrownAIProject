"""
皇冠AI赛事研判系统 - 每日模型报告 v1.2
自动生成每日Performance Report HTML:
- 分析场次/推荐数/A级B级
- 命中率(按等级)
- CLV统计
- 模型贡献分析
- 盘口画像分布
- 需要优化的模型提示
"""
import os
from datetime import datetime
from typing import Optional
from utils.database import (
    get_connection, get_performance_summary, get_model_contribution_stats,
    save_performance_log,
)
from utils.logger import log


def generate_daily_report(date_str: str = None, output_dir: str = None) -> Optional[str]:
    """生成每日模型报告HTML"""
    if not date_str:
        date_str = datetime.now().strftime('%Y-%m-%d')
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

    # 收集数据
    data = _collect_daily_data(date_str)
    if not data:
        return None

    html = _build_report_html(data, date_str)
    path = os.path.join(output_dir, f"daily_report_{date_str}.html")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    log.info(f"[日报] 生成: {path}")
    return path


def _collect_daily_data(date_str: str) -> Optional[dict]:
    """收集每日报告数据"""
    conn = get_connection()
    cursor = conn.cursor()

    # 当日分析统计
    cursor.execute("""
        SELECT COUNT(*) as total,
               AVG(crown_index) as avg_index,
               AVG(data_completeness) as avg_comp
        FROM prediction_history WHERE predicted_at LIKE ?
    """, (f"{date_str}%",))
    today_stats = dict(cursor.fetchone())

    # 当日结算统计
    cursor.execute("""
        SELECT COUNT(*) as settled,
               SUM(CASE WHEN hit IN (0, 1) THEN 1 ELSE 0 END) as decided,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               AVG(CASE WHEN clv_handicap IS NOT NULL THEN clv_handicap END) as avg_clv
        FROM prediction_history WHERE settled_at LIKE ?
    """, (f"{date_str}%",))
    settle_stats = dict(cursor.fetchone())

    # 按等级
    cursor.execute("""
        SELECT level, COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               SUM(CASE WHEN hit IN (0, 1) THEN 1 ELSE 0 END) as decided,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count
        FROM prediction_history WHERE predicted_at LIKE ?
        GROUP BY level
    """, (f"{date_str}%",))
    by_level = {r['level'] or '?': dict(r) for r in cursor.fetchall()}

    conn.close()

    # 模型贡献(全局)
    contribution = get_model_contribution_stats(30)

    # 盘口画像分布
    try:
        from pipeline.odds_profile import get_pattern_stats
        pattern_stats = get_pattern_stats()
    except Exception:
        pattern_stats = {"total": 0, "distribution": {}}

    total = today_stats['total'] or 0
    if total == 0:
        return None

    settled = settle_stats['settled'] or 0
    decided = settle_stats['decided'] or 0
    hit = settle_stats['hit_count'] or 0

    return {
        "date": date_str,
        "matches_analyzed": total,
        "avg_crown_index": round(today_stats['avg_index'], 1) if today_stats['avg_index'] else 0,
        "avg_completeness": round(today_stats['avg_comp'], 1) if today_stats['avg_comp'] else 0,
        "settled": settled,
        "hit": hit,
        "miss": decided - hit,
        "hit_rate": round(hit / decided * 100, 1) if decided > 0 else None,
        "avg_clv": settle_stats['avg_clv'],
        "by_level": by_level,
        "contribution": contribution,
        "pattern_stats": pattern_stats,
    }


def _build_report_html(data: dict, date_str: str) -> str:
    """构建HTML报告"""
    now = datetime.now().strftime('%H:%M')

    # 等级表
    level_rows = ""
    for lv in ['A', 'B', 'C', '?']:
        info = data['by_level'].get(lv)
        if not info:
            continue
        name = lv if lv != '?' else '未分级'
        settled = info['settled'] or 0
        decided = info['decided'] or 0
        hit = info['hit_count'] or 0
        hr = f"{hit/decided*100:.0f}%" if decided > 0 else "-"
        level_rows += f"<tr><td><strong>{name}</strong></td><td>{info['total']}</td><td>{settled}</td><td>{hit}</td><td>{hr}</td></tr>"

    # 模型贡献
    contrib = data['contribution']
    avg_scores = contrib.get('avg_scores', {})
    top_dist = contrib.get('top_model_distribution', {})
    model_names = {'strength': '实力', 'handicap': '盘口', 'squad': '阵容', 'market': '市场', 'ai': 'AI裁判'}

    model_rows = ""
    for key, cn in model_names.items():
        score = avg_scores.get(key, 0)
        dist = top_dist.get(key, {})
        top_count = dist.get('count', 0)
        hit_when_top = dist.get('hit_when_top', 0)
        model_rows += f"<tr><td>{cn}</td><td>{score}</td><td>{top_count}</td><td>{hit_when_top}</td></tr>"

    # 盘口画像
    patterns = data['pattern_stats'].get('distribution', {})
    pattern_str = " | ".join(f"{k}: {v['count']}场" for k, v in patterns.items()) if patterns else "暂无数据"

    # 优化建议
    suggestions = _generate_suggestions(data, avg_scores)

    hit_rate_str = f"{data['hit_rate']}%" if data['hit_rate'] is not None else "待结算"
    clv_str = f"{data['avg_clv']:+.3f}" if data['avg_clv'] is not None else "暂无"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>每日模型报告 {date_str}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; background: #f5f6fa; }}
h1 {{ color: #2c3e50; font-size: 1.4em; }}
h2 {{ color: #34495e; font-size: 1.1em; margin-top: 25px; border-bottom: 2px solid #3498db; padding-bottom: 5px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin: 15px 0; }}
.stat {{ background: white; border-radius: 10px; padding: 15px; text-align: center; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}
.stat .num {{ font-size: 1.8em; font-weight: bold; color: #2980b9; }}
.stat .lbl {{ font-size: 0.8em; color: #7f8c8d; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; margin: 10px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.06); }}
th {{ background: #2c3e50; color: white; padding: 8px 10px; font-size: 0.85em; text-align: left; }}
td {{ padding: 7px 10px; border-bottom: 1px solid #ecf0f1; font-size: 0.9em; }}
.suggestion {{ background: #ffeaa7; border-radius: 8px; padding: 12px 16px; margin: 10px 0; font-size: 0.9em; }}
.pattern {{ background: #dfe6e9; border-radius: 6px; padding: 10px; font-size: 0.85em; margin: 10px 0; }}
.footer {{ color: #b2bec3; font-size: 0.75em; margin-top: 30px; text-align: center; }}
</style></head><body>
<h1>每日模型报告 — {date_str}</h1>

<div class="grid">
    <div class="stat"><div class="num">{data['matches_analyzed']}</div><div class="lbl">分析场次</div></div>
    <div class="stat"><div class="num">{data['settled']}</div><div class="lbl">已结算</div></div>
    <div class="stat"><div class="num">{hit_rate_str}</div><div class="lbl">命中率</div></div>
    <div class="stat"><div class="num">{clv_str}</div><div class="lbl">平均CLV</div></div>
    <div class="stat"><div class="num">{data['avg_crown_index']}</div><div class="lbl">平均指数</div></div>
    <div class="stat"><div class="num">{data['avg_completeness']}%</div><div class="lbl">数据完整度</div></div>
</div>

<h2>按等级</h2>
<table><tr><th>等级</th><th>推荐</th><th>已结算</th><th>命中</th><th>命中率</th></tr>
{level_rows}</table>

<h2>模型贡献(30天)</h2>
<table><tr><th>模型</th><th>平均分</th><th>主导次数</th><th>主导时命中</th></tr>
{model_rows}</table>

<h2>盘口画像分布</h2>
<div class="pattern">{pattern_str}</div>

<h2>优化建议</h2>
{suggestions}

<div class="footer">皇冠AI v1.2 | 生成时间: {date_str} {now} | V1.3目标: 30天连续运行不修改模型</div>
</body></html>"""


def _generate_suggestions(data: dict, avg_scores: dict) -> str:
    """根据数据生成优化建议"""
    suggestions = []

    # 找最弱模型
    if avg_scores:
        weakest = min(avg_scores, key=avg_scores.get)
        weakest_score = avg_scores[weakest]
        names = {'strength': '实力模型', 'handicap': '盘口模型', 'squad': '阵容模型', 'market': '市场模型', 'ai': 'AI裁判'}
        if weakest_score < 60:
            suggestions.append(f"⚠️ {names.get(weakest, weakest)}平均分仅{weakest_score}，建议优先优化")

    # 命中率低
    if data['hit_rate'] is not None and data['hit_rate'] < 50 and data['settled'] >= 5:
        suggestions.append(f"⚠️ 命中率{data['hit_rate']}%偏低(样本{data['settled']}场)，检查推荐阈值是否过松")

    # CLV为负
    if data['avg_clv'] is not None and data['avg_clv'] < -0.1:
        suggestions.append(f"⚠️ CLV={data['avg_clv']:+.3f}，盘口判断落后市场，考虑增加盘口追踪频次")

    # 数据完整度低
    if data['avg_completeness'] < 70:
        suggestions.append(f"📊 数据完整度{data['avg_completeness']}%，API-Football球队数据获取可能有问题")

    if not suggestions:
        suggestions.append("✅ 各项指标正常，继续积累数据")

    return "".join(f'<div class="suggestion">{s}</div>' for s in suggestions)


def auto_daily_report():
    """自动日报(供LaunchAgent调用)"""
    from pipeline.odds_profile import generate_all_profiles
    # 先生成盘口画像
    generate_all_profiles()
    # 再生成报告
    path = generate_daily_report()
    if path:
        os.system(f'open "{path}"')
    return path
