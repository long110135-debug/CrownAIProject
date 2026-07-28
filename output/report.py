"""
皇冠AI赛事研判系统 - HTML报表生成
输出每日推荐报表，包含A/B/C级推荐、风险提示、皇冠指数详情
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from utils.logger import log
from config.settings import OUTPUT_DIR, MODEL_VERSION


def generate_html_report(ranked: dict, results: List[dict], date: str) -> str:
    """
    生成HTML报表
    
    参数:
    - ranked: rank_recommendations()的输出
    - results: 所有分析结果
    - date: 日期字符串
    
    返回: 报表文件路径
    """
    html = _build_html(ranked, results, date)

    output_path = OUTPUT_DIR / f"crown_report_{date}.html"
    output_path.write_text(html, encoding="utf-8")
    log.info(f"报表已生成: {output_path}")
    return str(output_path)


def _build_html(ranked: dict, results: List[dict], date: str) -> str:
    """构建完整HTML"""
    a_cards = _render_recommendation_cards(ranked.get("a_level", []), "A")
    b_cards = _render_recommendation_cards(ranked.get("b_level", []), "B")
    c_cards = _render_recommendation_cards(ranked.get("c_level", []), "C")
    risk_cards = _render_risk_cards(ranked.get("risk_alerts", []))
    summary_stats = _render_summary(ranked, results)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>皇冠AI赛事研判 - {date}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
            background: #0a0e1a;
            color: #e0e6ed;
            min-height: 100vh;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        
        .header {{
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid #1e2a3a;
            margin-bottom: 30px;
        }}
        .header h1 {{
            font-size: 28px;
            background: linear-gradient(135deg, #f0c27f, #fc5c7d);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        .header .subtitle {{
            color: #7a8ba0;
            font-size: 14px;
        }}
        .header .version {{
            color: #4a5568;
            font-size: 12px;
            margin-top: 4px;
        }}
        
        .summary {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 30px;
        }}
        .stat-card {{
            background: #131a2a;
            border-radius: 12px;
            padding: 16px;
            text-align: center;
            border: 1px solid #1e2a3a;
        }}
        .stat-card .number {{
            font-size: 28px;
            font-weight: 700;
            color: #f0c27f;
        }}
        .stat-card .label {{
            font-size: 12px;
            color: #7a8ba0;
            margin-top: 4px;
        }}
        
        .section {{
            margin-bottom: 30px;
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
            padding-left: 12px;
            border-left: 3px solid #f0c27f;
        }}
        .section-title.risk {{
            border-left-color: #fc5c7d;
        }}
        
        .match-card {{
            background: #131a2a;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 12px;
            border: 1px solid #1e2a3a;
            transition: border-color 0.2s;
        }}
        .match-card:hover {{
            border-color: #f0c27f44;
        }}
        .match-card.level-a {{
            border-left: 3px solid #f0c27f;
        }}
        .match-card.level-b {{
            border-left: 3px solid #6c9ce8;
        }}
        .match-card.level-c {{
            border-left: 3px solid #4a5568;
        }}
        .match-card.risk {{
            border-left: 3px solid #fc5c7d;
        }}
        
        .card-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }}
        .match-name {{
            font-size: 16px;
            font-weight: 600;
        }}
        .league-tag {{
            font-size: 11px;
            background: #1e2a3a;
            padding: 3px 8px;
            border-radius: 4px;
            color: #7a8ba0;
        }}
        
        .card-body {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
        }}
        .info-item {{
            display: flex;
            flex-direction: column;
        }}
        .info-label {{
            font-size: 11px;
            color: #7a8ba0;
            margin-bottom: 2px;
        }}
        .info-value {{
            font-size: 14px;
            font-weight: 500;
        }}
        
        .crown-index {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .index-bar {{
            flex: 1;
            height: 6px;
            background: #1e2a3a;
            border-radius: 3px;
            overflow: hidden;
        }}
        .index-fill {{
            height: 100%;
            border-radius: 3px;
            transition: width 0.3s;
        }}
        .index-fill.high {{ background: linear-gradient(90deg, #f0c27f, #fc5c7d); }}
        .index-fill.mid {{ background: #6c9ce8; }}
        .index-fill.low {{ background: #4a5568; }}
        
        .stars {{
            color: #f0c27f;
            font-size: 14px;
        }}
        
        .reasoning {{
            margin-top: 12px;
            padding-top: 12px;
            border-top: 1px solid #1e2a3a;
            font-size: 13px;
            color: #9aa8b8;
            line-height: 1.5;
        }}
        
        .risk-badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }}
        .risk-low {{ background: #1a3a2a; color: #4ade80; }}
        .risk-mid {{ background: #3a3a1a; color: #fbbf24; }}
        .risk-high {{ background: #3a1a1a; color: #f87171; }}
        
        .footer {{
            text-align: center;
            padding: 20px 0;
            color: #4a5568;
            font-size: 12px;
            border-top: 1px solid #1e2a3a;
            margin-top: 30px;
        }}
        
        .empty-state {{
            text-align: center;
            padding: 40px;
            color: #4a5568;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>皇冠AI赛事研判系统</h1>
            <div class="subtitle">{date} 每日研判报告</div>
            <div class="version">{MODEL_VERSION} | 生成时间: {datetime.now().strftime("%H:%M:%S")}</div>
        </div>
        
        {summary_stats}
        
        <div class="section">
            <div class="section-title">A级推荐 ★★★★★</div>
            {a_cards if a_cards else '<div class="empty-state">今日无A级推荐</div>'}
        </div>
        
        <div class="section">
            <div class="section-title">B级推荐 ★★★★</div>
            {b_cards if b_cards else '<div class="empty-state">今日无B级推荐</div>'}
        </div>
        
        <div class="section">
            <div class="section-title">C级观察</div>
            {c_cards if c_cards else '<div class="empty-state">今日无C级观察</div>'}
        </div>
        
        <div class="section">
            <div class="section-title risk">风险提示</div>
            {risk_cards if risk_cards else '<div class="empty-state">今日无明显风险</div>'}
        </div>
        
        <div class="footer">
            皇冠AI赛事研判系统 | 仅供研究参考，不构成任何投注建议<br>
            数据来源: 皇冠盘口 | 模型版本: {MODEL_VERSION}
        </div>
    </div>
</body>
</html>"""


def _render_recommendation_cards(recs: List[dict], level: str) -> str:
    """渲染推荐卡片"""
    if not recs:
        return ""

    cards = []
    for rec in recs:
        level_class = f"level-{level.lower()}"
        stars = "★" * rec.get("stars", 0) + "☆" * (5 - rec.get("stars", 0))
        crown_index = rec.get("crown_index", 0)
        index_class = "high" if crown_index >= 75 else ("mid" if crown_index >= 55 else "low")
        risk_class = {"低": "risk-low", "中": "risk-mid", "高": "risk-high", "极高": "risk-high"}.get(
            rec.get("risk_level", "中"), "risk-mid"
        )

        card = f"""
        <div class="match-card {level_class}">
            <div class="card-header">
                <span class="match-name">{rec.get('home_team', '')} vs {rec.get('away_team', '')}</span>
                <span class="league-tag">{rec.get('league', '')}</span>
            </div>
            <div class="card-body">
                <div class="info-item">
                    <span class="info-label">方向</span>
                    <span class="info-value">{rec.get('direction_label', '')}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">盘口</span>
                    <span class="info-value">{rec.get('handicap', '-')}</span>
                </div>
                <div class="info-item">
                    <span class="info-label">皇冠指数</span>
                    <div class="crown-index">
                        <span class="info-value">{crown_index}</span>
                        <div class="index-bar">
                            <div class="index-fill {index_class}" style="width: {crown_index}%"></div>
                        </div>
                    </div>
                </div>
                <div class="info-item">
                    <span class="info-label">可信度 / 风险</span>
                    <span class="info-value">
                        {rec.get('confidence', 0)}% 
                        <span class="risk-badge {risk_class}">{rec.get('risk_level', '-')}</span>
                    </span>
                </div>
            </div>
            <div class="reasoning">
                <span class="stars">{stars}</span> {rec.get('reasoning', '')}
            </div>
        </div>"""
        cards.append(card)

    return "\n".join(cards)


def _render_risk_cards(alerts: List[dict]) -> str:
    """渲染风险提示卡片"""
    if not alerts:
        return ""

    cards = []
    for rec in alerts:
        card = f"""
        <div class="match-card risk">
            <div class="card-header">
                <span class="match-name">⚠️ {rec.get('home_team', '')} vs {rec.get('away_team', '')}</span>
                <span class="league-tag">{rec.get('league', '')}</span>
            </div>
            <div class="reasoning">
                风险等级: {rec.get('risk_level', '高')} | {rec.get('reasoning', '')}
            </div>
        </div>"""
        cards.append(card)

    return "\n".join(cards)


def _render_summary(ranked: dict, results: List[dict]) -> str:
    """渲染汇总统计"""
    total = ranked.get("total_matches", len(results))
    a_count = ranked.get("a_count", 0)
    b_count = ranked.get("b_count", 0)
    risk_count = len(ranked.get("risk_alerts", []))

    return f"""
    <div class="summary">
        <div class="stat-card">
            <div class="number">{total}</div>
            <div class="label">分析场次</div>
        </div>
        <div class="stat-card">
            <div class="number">{a_count}</div>
            <div class="label">A级推荐</div>
        </div>
        <div class="stat-card">
            <div class="number">{b_count}</div>
            <div class="label">B级推荐</div>
        </div>
        <div class="stat-card">
            <div class="number">{risk_count}</div>
            <div class="label">风险提示</div>
        </div>
    </div>"""
