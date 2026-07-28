"""
皇冠AI赛事研判系统 - 任务锁
防止track和analyze并发运行导致数据不一致。

使用SQLite表实现分布式锁(单进程环境足够)。
"""
import time
import os
from datetime import datetime
from utils.database import get_connection
from utils.logger import log

# 锁超时(秒): 超过此时间视为死锁，自动释放
LOCK_TIMEOUT = 300  # 5分钟


def _ensure_lock_table():
    """确保锁表存在"""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_locks (
            task_name TEXT PRIMARY KEY,
            locked_at TEXT,
            pid INTEGER,
            expires_at TEXT
        )
    """)
    conn.commit()
    conn.close()


def acquire_lock(task_name: str) -> bool:
    """
    尝试获取任务锁。
    
    返回True=获取成功，False=被其他任务占用。
    自动清理过期锁(防死锁)。
    """
    _ensure_lock_table()
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    expires = datetime.fromtimestamp(now.timestamp() + LOCK_TIMEOUT)

    try:
        # 清理过期锁
        cursor.execute("DELETE FROM task_locks WHERE expires_at < ?",
                      (now.strftime('%Y-%m-%d %H:%M:%S'),))

        # 检查是否被占用
        cursor.execute("SELECT task_name, pid FROM task_locks WHERE task_name = ?",
                      (task_name,))
        existing = cursor.fetchone()
        if existing:
            conn.close()
            log.info(f"[锁] {task_name} 被占用 (PID={existing['pid']})，跳过")
            return False

        # 检查互斥: 写同表的不能同时跑
        # track写closing_odds+prediction_history(CLV), analyze写prediction_history, settle写两者
        mutex_map = {
            "track": {"analyze", "settle"},
            "analyze": {"track", "settle"},
            "settle": {"track", "analyze"},
        }
        mutex_tasks = mutex_map.get(task_name, set())
        for mutex_task in mutex_tasks:
            cursor.execute("SELECT pid FROM task_locks WHERE task_name = ?",
                          (mutex_task,))
            if cursor.fetchone():
                conn.close()
                log.info(f"[锁] {task_name} 与 {mutex_task} 互斥，跳过")
                return False

        # 获取锁
        cursor.execute("""
            INSERT OR REPLACE INTO task_locks (task_name, locked_at, pid, expires_at)
            VALUES (?, ?, ?, ?)
        """, (task_name, now.strftime('%Y-%m-%d %H:%M:%S'), os.getpid(),
              expires.strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
        conn.close()
        return True

    except Exception as e:
        conn.close()
        log.warning(f"[锁] 获取{task_name}锁异常: {e}")
        return False


def release_lock(task_name: str):
    """释放任务锁"""
    try:
        conn = get_connection()
        conn.execute("DELETE FROM task_locks WHERE task_name = ? AND pid = ?",
                    (task_name, os.getpid()))
        conn.commit()
        conn.close()
    except Exception:
        pass


class TaskLock:
    """上下文管理器: with TaskLock('track'): ..."""

    def __init__(self, task_name: str):
        self.task_name = task_name
        self.acquired = False

    def __enter__(self):
        self.acquired = acquire_lock(self.task_name)
        if not self.acquired:
            raise LockConflictError(f"{self.task_name} 被占用")
        return self

    def __exit__(self, *args):
        if self.acquired:
            release_lock(self.task_name)


class LockConflictError(Exception):
    """锁冲突"""
    pass
