#!/usr/bin/env python3
"""
皇冠AI赛事研判系统 - 手动运行入口(纯参数解析，不含业务逻辑)

所有业务逻辑在 pipeline/daily_run.py 中。

用法:
  python3 main.py              完整流程(同步+盘口+分析+报表)
  python3 main.py --track      仅更新盘口
  python3 main.py --changes    显示盘口变化
  python3 main.py --analyze    仅分析(不重新同步)
  python3 main.py --settle     手动结算
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    args = sys.argv[1:]

    if '--track' in args:
        from pipeline.daily_run import track_odds
        track_odds()

    elif '--changes' in args:
        from pipeline.odds_tracker import detect_odds_changes
        changes = detect_odds_changes()
        if not changes:
            print("暂无盘口变化记录")
            return
        print(f"\n盘口变化 ({len(changes)}场):")
        for c in sorted(changes, key=lambda x: -x.get('significance', 0))[:15]:
            print(f"  {c.get('match_info', '')}")
            print(f"    {c['change_type']}: {c.get('old_handicap','')}→{c.get('new_handicap','')} | 信号:{c['signal']} 强度:{c['significance']}")

    elif '--analyze' in args:
        from pipeline.daily_run import analyze_matches
        result = analyze_matches(hours_ahead=24)
        print(f"\n分析完成: {result['analyzed']}场 | A:{result['level_a']} B:{result['level_b']} C:{result['level_c']}")

    elif '--settle' in args:
        from pipeline.daily_run import settle_matches
        settle_matches()

    else:
        # 默认: 完整流程
        from pipeline.daily_run import run_full
        run_full()


if __name__ == "__main__":
    main()
