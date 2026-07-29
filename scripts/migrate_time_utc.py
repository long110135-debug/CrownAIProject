#!/usr/bin/env python3
"""
皇冠AI - 时间字段统一UTC迁移

将各表naive时间字段迁移为 timezone-aware UTC ISO 8601。
分类迁移(不盲加8小时):
  legacy_cst_naive → 减8h转UTC
  legacy_utc_naive → 标+00:00
  ambiguous        → 不自动迁移，输出清单

用法:
  python3 scripts/migrate_time_utc.py --dry-run   # 只统计，不修改
  python3 scripts/migrate_time_utc.py --execute    # 备份后迁移可安全转换的记录
"""
import sys
import os
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.database import get_connection, DB_PATH
from utils.timeutil import classify_legacy_time, migrate_naive_to_utc

# 待迁移字段: (表, 字段, 默认来源提示)
TIME_FIELDS = [
    ("matches", "match_time", ""),            # 中文格式→ambiguous, ISO→cst
    ("matches", "created_at", "cst"),
    ("matches", "updated_at", "cst"),
    ("prediction_history", "kickoff", ""),
    ("prediction_history", "predicted_at", "cst"),
    ("prediction_history", "settled_at", "cst"),
    ("prediction_history", "prematch_at", "cst"),
    ("odds_timeline", "record_time", "cst"),
    ("closing_odds", "closing_time", "cst"),
    ("recommendation_experiments", "created_at", "cst"),
    ("recommendation_experiments", "settled_at", "cst"),
    ("recommendation_experiments", "prematch_at", "cst"),
    ("match_result", "settled_at", "cst"),
]


def _source_hint(default_hint):
    return "legacy_utc_naive" if default_hint == "utc" else ""


def dry_run():
    conn = get_connection()
    cur = conn.cursor()
    print("=== 时间迁移 DRY-RUN (不修改数据) ===\n")
    total_by_class = {"aware": 0, "legacy_cst_naive": 0, "legacy_utc_naive": 0, "ambiguous": 0}
    ambiguous_samples = []
    for table, field, hint in TIME_FIELDS:
        try:
            cur.execute(f"SELECT rowid, {field} FROM {table} WHERE {field} IS NOT NULL AND {field} != ''")
        except Exception as e:
            print(f"  {table}.{field}: 跳过({e})")
            continue
        counts = {"aware": 0, "legacy_cst_naive": 0, "legacy_utc_naive": 0, "ambiguous": 0}
        for row in cur.fetchall():
            cls = classify_legacy_time(row[1], _source_hint(hint))
            counts[cls] += 1
            total_by_class[cls] += 1
            if cls == "ambiguous" and len(ambiguous_samples) < 15:
                ambiguous_samples.append((table, field, row[0], row[1]))
        print(f"  {table}.{field}: aware={counts['aware']} cst_naive={counts['legacy_cst_naive']} "
              f"utc_naive={counts['legacy_utc_naive']} ambiguous={counts['ambiguous']}")
    conn.close()

    print(f"\n=== 汇总 ===")
    print(f"  已aware(无需迁移): {total_by_class['aware']}")
    print(f"  可安全迁移(cst_naive): {total_by_class['legacy_cst_naive']}")
    print(f"  可安全迁移(utc_naive): {total_by_class['legacy_utc_naive']}")
    print(f"  ambiguous(不自动迁移): {total_by_class['ambiguous']}")
    if ambiguous_samples:
        print(f"\n=== ambiguous 清单(前{len(ambiguous_samples)}条) ===")
        for t, f, rid, v in ambiguous_samples:
            print(f"  {t}.{f} rowid={rid}: {repr(v)}")
    return total_by_class


def execute():
    # 备份
    backup = f"{DB_PATH}.bak_time_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy(DB_PATH, backup)
    print(f"已备份数据库 → {backup}\n")

    conn = get_connection()
    cur = conn.cursor()
    print("=== 时间迁移 EXECUTE ===\n")
    total_migrated = 0
    total_ambiguous = 0
    for table, field, hint in TIME_FIELDS:
        try:
            cur.execute(f"SELECT rowid, {field} FROM {table} WHERE {field} IS NOT NULL AND {field} != ''")
        except Exception:
            continue
        rows = cur.fetchall()
        migrated = 0
        ambiguous = 0
        for row in rows:
            cls = classify_legacy_time(row[1], _source_hint(hint))
            if cls in ("legacy_cst_naive", "legacy_utc_naive"):
                new_val, ok = migrate_naive_to_utc(row[1], cls)
                if ok:
                    cur.execute(f"UPDATE {table} SET {field} = ? WHERE rowid = ?", (new_val, row[0]))
                    migrated += 1
            elif cls == "ambiguous":
                ambiguous += 1
        conn.commit()
        total_migrated += migrated
        total_ambiguous += ambiguous
        print(f"  {table}.{field}: 迁移{migrated}条, ambiguous保留{ambiguous}条")
    conn.close()
    print(f"\n=== 完成: 共迁移{total_migrated}条, ambiguous保留{total_ambiguous}条(需人工处理) ===")
    print(f"备份: {backup}")


if __name__ == "__main__":
    if "--execute" in sys.argv:
        execute()
    else:
        dry_run()
