#!/usr/bin/env python3
"""
皇冠AI赛事研判系统 - 定时任务入口(纯分发，不含业务逻辑)

所有业务逻辑在 pipeline/daily_run.py 中。
本文件只负责: 解析命令 → 获取锁 → 调用 daily_run → 释放锁。

用法:
  python3 scheduler.py sync        同步今日赛事
  python3 scheduler.py track       更新盘口
  python3 scheduler.py analyze     分析即将开赛的比赛
  python3 scheduler.py close       锁定临场收盘赔率
  python3 scheduler.py settle      结算已结束比赛
  python3 scheduler.py report      生成日报+CLV报表
  python3 scheduler.py watchdog    健康检查
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime
from utils.logger import log
from utils.database import get_connection
from utils.task_lock import TaskLock, LockConflictError


def cmd_sync():
    from pipeline.daily_run import sync_today
    sync_today()


def cmd_track():
    from pipeline.daily_run import track_odds
    try:
        with TaskLock("track"):
            track_odds()
    except LockConflictError:
        log.info("[track] 锁冲突，跳过本次")


def cmd_analyze():
    from pipeline.daily_run import analyze_matches
    try:
        with TaskLock("analyze"):
            analyze_matches(hours_ahead=6)
    except LockConflictError:
        log.info("[analyze] 锁冲突，跳过本次")


def cmd_close():
    from pipeline.daily_run import close_odds
    try:
        with TaskLock("close"):
            close_odds()
    except LockConflictError:
        log.info("[close] 锁冲突，跳过本次")


def cmd_settle():
    from pipeline.daily_run import settle_matches
    try:
        with TaskLock("settle"):
            settle_matches()
    except LockConflictError:
        log.info("[settle] 锁冲突，跳过本次")


def cmd_report():
    from pipeline.daily_run import generate_reports
    generate_reports()


# === Watchdog (含防重启风暴) ===

WATCHDOG_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "data", "watchdog_state.json")
MAX_RESTARTS_PER_WINDOW = 3
WINDOW_MINUTES = 30


def cmd_watchdog():
    """健康检查 + 防重启风暴"""
    issues = []

    # 1. 数据库
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
    except Exception as e:
        issues.append(f"数据库异常: {e}")

    # 2. API-Football
    try:
        from scraper.apifootball_data import APIFootballClient
        client = APIFootballClient()
        if not client.api_key:
            issues.append("API-Football密钥缺失")
    except Exception as e:
        issues.append(f"API-Football: {e}")

    # 3. 皇冠账号
    try:
        from scraper.hga_scraper import get_hga_credentials
        user, pwd = get_hga_credentials()
        if not user or not pwd:
            issues.append("皇冠账号未配置")
    except Exception as e:
        issues.append(f"皇冠账号: {e}")

    # 4. 今日赛事是否已抓取
    today = datetime.now().strftime('%Y-%m-%d')
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM matches WHERE match_time LIKE ?", (f"{today}%",))
    today_count = cursor.fetchone()[0]
    conn.close()
    if today_count == 0 and datetime.now().hour >= 8:
        issues.append("今日赛事未抓取(0场)")

    # 5. 守护进程是否存活
    import subprocess
    ps = subprocess.run(['pgrep', '-f', 'crown_daemon'], capture_output=True, text=True)
    daemon_alive = bool(ps.stdout.strip())
    if not daemon_alive:
        issues.append("皇冠守护进程未运行")

    # 输出
    if issues:
        log.warning(f"[Watchdog] {len(issues)}个问题:")
        for i in issues:
            log.warning(f"  ✗ {i}")
        _write_status(False, issues)

        # 尝试重启守护进程(带防风暴保护)
        if not daemon_alive:
            _try_restart_daemon()
    else:
        log.info("[Watchdog] 全部正常 ✓")
        _write_status(True, [])
        _reset_restart_count()


def _try_restart_daemon():
    """重启守护进程(30分钟内最多3次)"""
    state = _load_watchdog_state()
    now = datetime.now()

    # 清理窗口外的记录
    restarts = [t for t in state.get("restarts", [])
                if (now - datetime.fromisoformat(t)).total_seconds() < WINDOW_MINUTES * 60]

    if len(restarts) >= MAX_RESTARTS_PER_WINDOW:
        log.warning(f"[Watchdog] {WINDOW_MINUTES}分钟内已重启{len(restarts)}次，进入冷却，不再重启")
        state["cooldown_until"] = now.isoformat()
        _save_watchdog_state(state)
        return

    # 检查是否在冷却期
    cooldown = state.get("cooldown_until")
    if cooldown and now < datetime.fromisoformat(cooldown):
        log.info("[Watchdog] 冷却期中，跳过重启")
        return

    # 执行重启(先确认进程确实不存在)
    import subprocess
    ps = subprocess.run(['pgrep', '-f', 'crown_daemon'], capture_output=True, text=True)
    if ps.stdout.strip():
        log.info("[Watchdog] 守护进程实际存活，跳过重启")
        return

    log.info("[Watchdog] 尝试重启守护进程...")
    subprocess.Popen(
        ['launchctl', 'kickstart', '-k', f'gui/{os.getuid()}/com.crownai.daemon'],
        capture_output=True
    )
    restarts.append(now.isoformat())
    state["restarts"] = restarts
    _save_watchdog_state(state)


def _reset_restart_count():
    """健康时重置重启计数"""
    state = _load_watchdog_state()
    if state.get("restarts"):
        state["restarts"] = []
        state.pop("cooldown_until", None)
        _save_watchdog_state(state)


def _load_watchdog_state() -> dict:
    try:
        with open(WATCHDOG_STATE_FILE, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"restarts": []}


def _save_watchdog_state(state: dict):
    os.makedirs(os.path.dirname(WATCHDOG_STATE_FILE), exist_ok=True)
    with open(WATCHDOG_STATE_FILE, 'w') as f:
        json.dump(state, f, ensure_ascii=False)


def _write_status(healthy: bool, issues: list):
    status = {
        "time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "healthy": healthy,
        "issues": issues,
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "health_status.json")
    with open(path, 'w') as f:
        json.dump(status, f, ensure_ascii=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'watchdog'
    commands = {
        'sync': cmd_sync,
        'track': cmd_track,
        'analyze': cmd_analyze,
        'close': cmd_close,
        'settle': cmd_settle,
        'report': cmd_report,
        'watchdog': cmd_watchdog,
    }
    if cmd in commands:
        commands[cmd]()
    else:
        print(f"未知命令: {cmd}")
        print(f"可用: {', '.join(commands.keys())}")
