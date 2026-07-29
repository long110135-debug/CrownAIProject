"""统一时间工具测试
覆盖: UTC存储与北京时间展示; 北京时间跨日对应UTC范围;
naive旧UTC迁移; naive旧CST迁移; ambiguous不自动迁移。
"""
import sys
import os
import unittest
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.timeutil import (
    now_utc, utc_iso, to_shanghai, format_shanghai, parse_to_aware,
    shanghai_day_to_utc_range, today_utc_range, today_shanghai,
    classify_legacy_time, migrate_naive_to_utc, is_already_aware,
    UTC, SHANGHAI,
)


class TestUtcStorageDisplay(unittest.TestCase):
    """UTC存储 + 北京时间展示"""

    def test_now_utc_is_aware(self):
        self.assertIsNotNone(now_utc().tzinfo)
        self.assertEqual(now_utc().utcoffset(), timedelta(0))

    def test_utc_iso_format(self):
        dt = datetime(2026, 7, 29, 5, 30, 0, tzinfo=UTC)
        self.assertEqual(utc_iso(dt), "2026-07-29T05:30:00+00:00")

    def test_utc_iso_naive_treated_as_utc(self):
        dt = datetime(2026, 7, 29, 5, 30, 0)  # naive
        self.assertEqual(utc_iso(dt), "2026-07-29T05:30:00+00:00")

    def test_to_shanghai_conversion(self):
        # UTC 05:30 = 北京 13:30
        dt = datetime(2026, 7, 29, 5, 30, 0, tzinfo=UTC)
        sh = to_shanghai(dt)
        self.assertEqual(sh.hour, 13)
        self.assertEqual(sh.minute, 30)

    def test_format_shanghai(self):
        dt = datetime(2026, 7, 29, 5, 30, 0, tzinfo=UTC)
        self.assertEqual(format_shanghai(dt, "%Y-%m-%d %H:%M"), "2026-07-29 13:30")

    def test_parse_to_aware_iso_with_tz(self):
        dt = parse_to_aware("2026-07-29T05:30:00+00:00")
        self.assertEqual(dt, datetime(2026, 7, 29, 5, 30, tzinfo=UTC))

    def test_parse_to_aware_naive_iso_as_utc(self):
        dt = parse_to_aware("2026-07-29 05:30:00")
        self.assertEqual(dt.tzinfo, UTC)
        self.assertEqual(dt.hour, 5)


class TestShanghaiDayUtcRange(unittest.TestCase):
    """北京时间跨日对应UTC范围"""

    def test_beijing_day_to_utc_range(self):
        # 北京2026-07-29全天 = UTC 2026-07-28T16:00 ~ 2026-07-29T15:59:59
        start, end = shanghai_day_to_utc_range("2026-07-29")
        self.assertEqual(start, "2026-07-28T16:00:00+00:00")
        self.assertEqual(end, "2026-07-29T15:59:59+00:00")

    def test_utc_range_covers_beijing_midnight(self):
        # 北京00:30 (UTC前一日16:30) 应落在该北京日的UTC范围内
        start, end = shanghai_day_to_utc_range("2026-07-29")
        # 北京2026-07-29 00:30 = UTC 2026-07-28T16:30
        beijing_early = datetime(2026, 7, 29, 0, 30, tzinfo=SHANGHAI).astimezone(UTC)
        self.assertGreaterEqual(beijing_early.isoformat(timespec="seconds"), start)
        self.assertLessEqual(beijing_early.isoformat(timespec="seconds"), end)

    def test_today_utc_range_returns_tuple(self):
        start, end = today_utc_range()
        self.assertIn("+00:00", start)
        self.assertIn("+00:00", end)
        self.assertLess(start, end)

    def test_today_shanghai_format(self):
        self.assertRegex(today_shanghai(), r"^\d{4}-\d{2}-\d{2}$")


class TestLegacyMigrationClassification(unittest.TestCase):
    """旧记录分类与迁移"""

    def test_classify_aware(self):
        self.assertEqual(classify_legacy_time("2026-07-29T05:30:00+00:00"), "aware")

    def test_classify_cst_naive(self):
        # naive ISO 默认视为北京时间
        self.assertEqual(classify_legacy_time("2026-07-29 13:30:00"), "legacy_cst_naive")

    def test_classify_utc_naive_with_hint(self):
        self.assertEqual(classify_legacy_time("2026-07-29 05:30:00", "utc"), "legacy_utc_naive")

    def test_classify_chinese_ambiguous(self):
        self.assertEqual(classify_legacy_time("08月21日 15:00"), "ambiguous")

    def test_classify_empty_ambiguous(self):
        self.assertEqual(classify_legacy_time(""), "ambiguous")
        self.assertEqual(classify_legacy_time(None), "ambiguous")

    def test_migrate_cst_naive_subtracts_8h(self):
        # 北京13:30 → UTC 05:30
        new_val, migrated = migrate_naive_to_utc("2026-07-29 13:30:00", "legacy_cst_naive")
        self.assertTrue(migrated)
        self.assertEqual(new_val, "2026-07-29T05:30:00+00:00")

    def test_migrate_utc_naive_marks_tz(self):
        new_val, migrated = migrate_naive_to_utc("2026-07-29 05:30:00", "legacy_utc_naive")
        self.assertTrue(migrated)
        self.assertEqual(new_val, "2026-07-29T05:30:00+00:00")

    def test_migrate_ambiguous_unchanged(self):
        new_val, migrated = migrate_naive_to_utc("08月21日 15:00", "ambiguous")
        self.assertFalse(migrated)
        self.assertEqual(new_val, "08月21日 15:00")

    def test_migrate_aware_unchanged(self):
        new_val, migrated = migrate_naive_to_utc("2026-07-29T05:30:00+00:00", "aware")
        self.assertFalse(migrated)

    def test_is_already_aware(self):
        self.assertTrue(is_already_aware("2026-07-29T05:30:00+00:00"))
        self.assertTrue(is_already_aware("2026-07-29T05:30:00Z"))
        self.assertFalse(is_already_aware("2026-07-29 05:30:00"))


if __name__ == "__main__":
    unittest.main()
