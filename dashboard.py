"""
皇冠AI赛事研判系统 - 命中率仪表盘
统计A/B/C各级推荐的命中率，生成可视化报表
用法: python3 dashboard.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.database import get_hit_stats, get_recent_predictions
from datetime import datetime


def print_dashboard():
    """打印命中率仪表盘"""
    stats = get_hit_stats()

    print(f"\n{'═'*50}")
    print(f"  皇冠AI 命中率仪表盘")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*50}\n")

    if stats['total'] == 0:
        print("  暂无已结算的预测记录。")
        print("  等待比赛结束后运行 python3 settle.py 结算。")
        print(f"\n{'═'*50}")
        return

    # 总体
    print(f"  总计: {stats['total']}场 | 命中{stats['hit']} | 命中率 {stats['hit_rate']}%")
    print(f"\n  {'─'*44}")

    # 分级
    for level in ['A', 'B', 'C']:
        lv = stats['by_level'].get(level)
        if not lv:
            print(f"  {level}级: 暂无数据")
            continue
        bar_len = int(lv['hit_rate'] / 5)  # 20格满
        bar = '█' * bar_len + '░' * (20 - bar_len)
        print(f"  {level}级: {lv['total']:>3}场 | 命中{lv['hit']:>2} | {bar} {lv['hit_rate']}%")

    print(f"\n{'═'*50}")

    # 诊断
    a = stats['by_level'].get('A', {})
    b = stats['by_level'].get('B', {})
    if a.get('total', 0) >= 10 and b.get('total', 0) >= 10:
        if a.get('hit_rate', 0) <= b.get('hit_rate', 0):
            print("\n  ⚠ 警告: A级命中率未明显高于B级")
            print("  → 皇冠指数权重可能需要调整")
        else:
            diff = a['hit_rate'] - b['hit_rate']
            print(f"\n  ✓ A级比B级高 {diff:.1f}个百分点，分级有效")

    # 最近7天明细
    recent = get_recent_predictions(days=7)
    settled = [r for r in recent if r['hit'] >= 0]
    if settled:
        print(f"\n  最近7天已结算: {len(settled)}场")
        hits = sum(1 for r in settled if r['hit'] == 1)
        print(f"  命中: {hits}/{len(settled)} ({hits/len(settled)*100:.1f}%)")

    print()


def generate_dashboard_html():
    """生成HTML仪表盘"""
    stats = get_hit_stats()
    recent = get_recent_predictions(days=30)
    settled = [r for r in recent if r['hit'] >= 0]

    today = datetime.now().strftime('%Y-%m-%d')
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output', f'dashboard_{today}.html')

    rows_html = ""
    for r in settled[:50]:
        hit_icon = "✓" if r['hit'] == 1 else "✗"
        hit_color = "#4ade80" if r['hit'] == 1 else "#f87171"
        level_color = {"A": "#f0c27f", "B": "#6c9ce8", "C": "#666"}.get(r['level'], "#666")
        rows_html += f"""
        <tr>
            <td>{r['predicted_at'][:10]}</td>
            <td>{r['league']}</td>
            <td>{r['home_team']} vs {r['away_team']}</td>
            <td style="color:{level_color};font-weight:bold">{r['level']}</td>
            <td>{r['recommend']}</td>
            <td>{r['crown_index']}</td>
            <td>{r['result_score'] or '-'}</td>
            <td style="color:{hit_color};font-weight:bold">{hit_icon}</td>
            <td>{r['error_reason'] or '-'}</td>
        </tr>"""

    a = stats['by_level'].get('A', {'total': 0, 'hit': 0, 'hit_rate': 0})
    b = stats['by_level'].get('B', {'total': 0, 'hit': 0, 'hit_rate': 0})
    c = stats['by_level'].get('C', {'total': 0, 'hit': 0, 'hit_rate': 0})

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>皇冠AI仪表盘 {today}</title>
<style>
body {{ font-family: -apple-system, sans-serif; background: #0a0e1a; color: #e0e6ed; padding: 20px; }}
.container {{ max-width: 1000px; margin: 0 auto; }}
h1 {{ text-align: center; background: linear-gradient(135deg, #f0c27f, #fc5c7d); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
.stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }}
.stat {{ background: #131a2a; border-radius: 12px; padding: 16px; text-align: center; border: 1px solid #1e2a3a; }}
.stat .num {{ font-size: 28px; font-weight: bold; color: #f0c27f; }}
.stat .label {{ font-size: 12px; color: #7a8ba0; margin-top: 4px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 20px; font-size: 13px; }}
th {{ background: #1a2235; padding: 8px; text-align: left; }}
td {{ padding: 6px 8px; border-bottom: 1px solid #1e2a3a; }}
</style></head><body>
<div class="container">
<h1>皇冠AI 命中率仪表盘</h1>
<p style="text-align:center;color:#7a8ba0">{today}</p>
<div class="stats">
  <div class="stat"><div class="num">{stats['total']}</div><div class="label">总场次</div></div>
  <div class="stat"><div class="num">{stats['hit_rate']}%</div><div class="label">总命中率</div></div>
  <div class="stat"><div class="num">{a.get('hit_rate',0)}%</div><div class="label">A级 ({a.get('total',0)}场)</div></div>
  <div class="stat"><div class="num">{b.get('hit_rate',0)}%</div><div class="label">B级 ({b.get('total',0)}场)</div></div>
</div>
<table>
<tr><th>日期</th><th>联赛</th><th>比赛</th><th>级别</th><th>推荐</th><th>指数</th><th>比分</th><th>命中</th><th>错因</th></tr>
{rows_html}
</table>
</div></body></html>"""

    os.makedirs(os.path.dirname(html_path), exist_ok=True)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"仪表盘: {html_path}")
    return html_path


if __name__ == "__main__":
    print_dashboard()
    generate_dashboard_html()
