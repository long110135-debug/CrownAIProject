"""
皇冠AI赛事研判系统 - CLV分析仪表盘 v1.2
生成CLV统计HTML报表:
- 按等级(A/B/C)统计平均CLV
- 按联赛统计CLV
- 时间趋势
- 正CLV比例
- 核心结论: A级长期CLV>0 = 盘口判断领先市场
"""
import os
from datetime import datetime
from typing import Optional
from utils.database import get_connection
from utils.logger import log


def generate_clv_report(output_dir: str = None) -> Optional[str]:
    """生成CLV分析HTML报表"""
    if not output_dir:
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")

    stats = _collect_clv_stats()
    if not stats or stats['total_settled'] == 0:
        log.info("[CLV] 无已结算数据，跳过报表")
        return None

    html = _build_html(stats)
    today = datetime.now().strftime('%Y-%m-%d')
    path = os.path.join(output_dir, f"clv_report_{today}.html")
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    log.info(f"[CLV] 报表已生成: {path}")
    return path


def _collect_clv_stats() -> dict:
    """收集CLV统计数据"""
    conn = get_connection()
    cursor = conn.cursor()

    # 总体CLV
    cursor.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               AVG(CASE WHEN clv_handicap IS NOT NULL THEN clv_handicap END) as avg_clv_hdp,
               AVG(CASE WHEN clv_water IS NOT NULL THEN clv_water END) as avg_clv_water,
               SUM(CASE WHEN clv_handicap > 0 THEN 1 ELSE 0 END) as positive_clv,
               SUM(CASE WHEN clv_handicap IS NOT NULL THEN 1 ELSE 0 END) as has_clv
        FROM prediction_history
    """)
    overall = dict(cursor.fetchone())

    # 按等级
    cursor.execute("""
        SELECT level,
               COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               SUM(CASE WHEN hit IN (0, 1) THEN 1 ELSE 0 END) as decided,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               AVG(CASE WHEN clv_handicap IS NOT NULL THEN clv_handicap END) as avg_clv,
               SUM(CASE WHEN clv_handicap > 0 THEN 1 ELSE 0 END) as pos_clv,
               SUM(CASE WHEN clv_handicap IS NOT NULL THEN 1 ELSE 0 END) as has_clv
        FROM prediction_history
        GROUP BY level ORDER BY level
    """)
    by_level = [dict(r) for r in cursor.fetchall()]

    # 按联赛
    cursor.execute("""
        SELECT league,
               COUNT(*) as total,
               SUM(CASE WHEN hit >= 0 THEN 1 ELSE 0 END) as settled,
               SUM(CASE WHEN hit IN (0, 1) THEN 1 ELSE 0 END) as decided,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count,
               AVG(CASE WHEN clv_handicap IS NOT NULL THEN clv_handicap END) as avg_clv
        FROM prediction_history
        GROUP BY league ORDER BY total DESC LIMIT 15
    """)
    by_league = [dict(r) for r in cursor.fetchall()]

    # 按周趋势
    cursor.execute("""
        SELECT strftime('%Y-W%W', predicted_at) as week,
               COUNT(*) as total,
               AVG(CASE WHEN clv_handicap IS NOT NULL THEN clv_handicap END) as avg_clv,
               SUM(CASE WHEN hit IN (0, 1) THEN 1 ELSE 0 END) as decided,
               SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) as hit_count
        FROM prediction_history
        GROUP BY week ORDER BY week DESC LIMIT 12
    """)
    weekly = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "total_settled": overall["settled"] or 0,
        "avg_clv_handicap": overall["avg_clv_hdp"],
        "avg_clv_water": overall["avg_clv_water"],
        "positive_clv": overall["positive_clv"] or 0,
        "has_clv": overall["has_clv"] or 0,
        "by_level": by_level,
        "by_league": by_league,
        "weekly": weekly,
    }


def _build_html(stats: dict) -> str:
    """构建HTML报表"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    avg_clv = stats['avg_clv_handicap']
    pos_rate = round(stats['positive_clv'] / stats['has_clv'] * 100, 1) if stats['has_clv'] else 0

    # 等级表格
    level_rows = ""
    for lv in stats['by_level']:
        name = lv['level'] or '未分级'
        settled = lv['settled'] or 0
        decided = lv['decided'] or 0
        hit = lv['hit_count'] or 0
        hr = round(hit / decided * 100, 1) if decided else 0
        clv = lv['avg_clv']
        clv_str = f"{clv:+.3f}" if clv is not None else "-"
        clv_class = "positive" if clv and clv > 0 else "negative" if clv and clv < 0 else ""
        pos = lv['pos_clv'] or 0
        has = lv['has_clv'] or 0
        pos_str = f"{pos}/{has}" if has else "-"
        level_rows += f"""<tr>
            <td><strong>{name}</strong></td>
            <td>{lv['total']}</td><td>{settled}</td><td>{hit}</td><td>{hr}%</td>
            <td class="{clv_class}">{clv_str}</td><td>{pos_str}</td>
        </tr>"""

    # 联赛表格
    league_rows = ""
    for lg in stats['by_league']:
        settled = lg['settled'] or 0
        decided = lg['decided'] or 0
        hit = lg['hit_count'] or 0
        hr = round(hit / decided * 100, 1) if decided else 0
        clv = lg['avg_clv']
        clv_str = f"{clv:+.3f}" if clv is not None else "-"
        clv_class = "positive" if clv and clv > 0 else "negative" if clv and clv < 0 else ""
        league_rows += f"""<tr>
            <td>{lg['league']}</td><td>{lg['total']}</td><td>{settled}</td>
            <td>{hr}%</td><td class="{clv_class}">{clv_str}</td>
        </tr>"""

    # 核心结论
    a_level = next((l for l in stats['by_level'] if l['level'] == 'A'), None)
    conclusion = ""
    if a_level and a_level['avg_clv'] is not None:
        if a_level['avg_clv'] > 0:
            conclusion = f'<div class="conclusion good">A级平均CLV {a_level["avg_clv"]:+.3f} — 盘口判断领先市场，模型有正向预测力</div>'
        else:
            conclusion = f'<div class="conclusion bad">A级平均CLV {a_level["avg_clv"]:+.3f} — 盘口判断落后于市场，需要优化盘口模型</div>'

    avg_clv_str = f"{avg_clv:+.3f}" if avg_clv is not None else "暂无"

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>CLV分析仪表盘 - {now}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f8f9fa; }}
h1 {{ color: #1a1a2e; font-size: 1.5em; }}
h2 {{ color: #16213e; font-size: 1.2em; margin-top: 30px; }}
.summary {{ display: flex; gap: 20px; flex-wrap: wrap; margin: 20px 0; }}
.card {{ background: white; border-radius: 12px; padding: 20px; flex: 1; min-width: 150px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); text-align: center; }}
.card .value {{ font-size: 2em; font-weight: bold; color: #0f3460; }}
.card .label {{ color: #666; font-size: 0.85em; margin-top: 5px; }}
table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.06); margin: 15px 0; }}
th {{ background: #0f3460; color: white; padding: 10px 12px; text-align: left; font-size: 0.85em; }}
td {{ padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 0.9em; }}
tr:hover {{ background: #f0f4ff; }}
.positive {{ color: #27ae60; font-weight: bold; }}
.negative {{ color: #e74c3c; font-weight: bold; }}
.conclusion {{ padding: 15px 20px; border-radius: 8px; margin: 20px 0; font-weight: bold; }}
.conclusion.good {{ background: #d4edda; color: #155724; }}
.conclusion.bad {{ background: #f8d7da; color: #721c24; }}
.footer {{ color: #999; font-size: 0.8em; margin-top: 40px; text-align: center; }}
</style></head><body>
<h1>CLV分析仪表盘</h1>
<p style="color:#666">Closing Line Value — 预测时盘口 vs 收盘盘口 | 生成时间: {now}</p>

{conclusion}

<div class="summary">
    <div class="card"><div class="value">{avg_clv_str}</div><div class="label">平均CLV(盘口)</div></div>
    <div class="card"><div class="value">{pos_rate}%</div><div class="label">正CLV比例</div></div>
    <div class="card"><div class="value">{stats['total_settled']}</div><div class="label">已结算场次</div></div>
    <div class="card"><div class="value">{stats['has_clv']}</div><div class="label">有CLV数据</div></div>
</div>

<h2>按推荐等级</h2>
<table><tr><th>等级</th><th>总场</th><th>已结算</th><th>命中</th><th>命中率</th><th>平均CLV</th><th>正CLV</th></tr>
{level_rows}</table>

<h2>按联赛</h2>
<table><tr><th>联赛</th><th>总场</th><th>已结算</th><th>命中率</th><th>平均CLV</th></tr>
{league_rows}</table>

<div class="footer">皇冠AI赛事研判系统 v1.2 | CLV>0 = 拿到比收盘更好的价格 = 长期盈利指标</div>
</body></html>"""
