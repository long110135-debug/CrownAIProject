"""测试crown_odds_collector标准化: 联赛名/日期/match_id/去重一致性"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.crown_odds_collector import (
    normalize_league, normalize_date, build_match_id, CROWN_LEAGUE_MAP
)


class TestLeagueNormalization(unittest.TestCase):
    """联赛名标准化"""

    def test_all_major_leagues(self):
        """五大联赛全部有映射"""
        self.assertEqual(normalize_league("英格兰超级联赛"), "英超")
        self.assertEqual(normalize_league("西班牙甲组联赛"), "西甲")
        self.assertEqual(normalize_league("意大利甲组联赛"), "意甲")
        self.assertEqual(normalize_league("德国甲组联赛"), "德甲")
        self.assertEqual(normalize_league("法国甲组联赛"), "法甲")

    def test_nordic_leagues(self):
        """北欧联赛"""
        self.assertEqual(normalize_league("瑞典超级联赛"), "瑞超")
        self.assertEqual(normalize_league("芬兰超级联赛"), "芬超")
        self.assertEqual(normalize_league("挪威超级联赛"), "挪超")
        self.assertEqual(normalize_league("丹麦超级联赛"), "丹超")

    def test_secondary_leagues(self):
        """二级联赛"""
        self.assertEqual(normalize_league("英格兰冠军联赛"), "英冠")
        self.assertEqual(normalize_league("西班牙乙组联赛"), "西乙")
        self.assertEqual(normalize_league("德国乙组联赛"), "德乙")

    def test_unknown_passthrough(self):
        """未知联赛原样返回"""
        self.assertEqual(normalize_league("未知联赛XYZ"), "未知联赛XYZ")
        self.assertEqual(normalize_league(""), "")

    def test_all_mappings_non_empty(self):
        """所有映射值非空"""
        for crown_name, short_name in CROWN_LEAGUE_MAP.items():
            self.assertTrue(short_name, f"{crown_name} 映射为空")
            self.assertNotIn(" ", short_name, f"{crown_name} 映射含空格: '{short_name}'")

    def test_no_duplicate_short_names(self):
        """不同皇冠名不应映射到同一短名(除瑞典超甲)"""
        from collections import Counter
        values = list(CROWN_LEAGUE_MAP.values())
        counts = Counter(values)
        for name, count in counts.items():
            if count > 1:
                # 允许: 瑞典超级联赛/瑞典超级甲组联赛 → 瑞超
                keys = [k for k, v in CROWN_LEAGUE_MAP.items() if v == name]
                self.assertTrue(all("瑞典" in k for k in keys),
                              f"非瑞典联赛重复映射到 '{name}': {keys}")


class TestDateNormalization(unittest.TestCase):
    """日期格式标准化"""

    def test_chinese_format(self):
        """'07月28日' → 'YYYY-07-28'"""
        result = normalize_date("07月28日")
        self.assertRegex(result, r"^\d{4}-07-28$")

    def test_single_digit_month_day(self):
        """'1月5日' → 'YYYY-01-05'"""
        result = normalize_date("1月5日")
        self.assertRegex(result, r"^\d{4}-01-05$")

    def test_double_digit(self):
        """'12月31日' → 'YYYY-12-31'"""
        result = normalize_date("12月31日")
        self.assertRegex(result, r"^\d{4}-12-31$")

    def test_iso_passthrough(self):
        """已是ISO格式原样返回"""
        self.assertEqual(normalize_date("2026-07-28"), "2026-07-28")

    def test_empty_string(self):
        self.assertEqual(normalize_date(""), "")

    def test_garbage(self):
        """无法解析的格式原样返回"""
        self.assertEqual(normalize_date("unknown"), "unknown")


class TestMatchIdGeneration(unittest.TestCase):
    """match_id生成规则"""

    def test_standard_format(self):
        """CROWN_{短名}_{主队}_{客队}_{ISO日期}"""
        mid = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "07月28日")
        self.assertTrue(mid.startswith("CROWN_英超_阿森纳_切尔西_"))
        self.assertIn("-07-28", mid)

    def test_nordic_match_id(self):
        """北欧联赛match_id"""
        mid = build_match_id("瑞典超级联赛", "卡尔马", "马尔默", "07月28日")
        self.assertTrue(mid.startswith("CROWN_瑞超_卡尔马_马尔默_"))

    def test_consistency(self):
        """相同输入 → 相同match_id"""
        mid1 = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "08月15日")
        self.assertEqual(mid1, mid2)

    def test_different_dates_different_ids(self):
        """不同日期 → 不同match_id(防延期重赛)"""
        mid1 = build_match_id("英超", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("英超", "阿森纳", "切尔西", "08月16日")
        self.assertNotEqual(mid1, mid2)

    def test_different_leagues_different_ids(self):
        """不同联赛同队名 → 不同match_id"""
        mid1 = build_match_id("英格兰超级联赛", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("西班牙甲组联赛", "阿森纳", "切尔西", "08月15日")
        self.assertNotEqual(mid1, mid2)

    def test_home_away_order_matters(self):
        """主客顺序不同 → 不同match_id"""
        mid1 = build_match_id("英超", "阿森纳", "切尔西", "08月15日")
        mid2 = build_match_id("英超", "切尔西", "阿森纳", "08月15日")
        self.assertNotEqual(mid1, mid2)


class TestCollectorAndSnapshotConsistency(unittest.TestCase):
    """collector路径和snapshot路径生成相同match_id"""

    def test_same_match_id_both_paths(self):
        """同一场比赛通过collector和直接构造产生相同match_id"""
        # collector路径
        mid_collector = build_match_id("瑞典超级联赛", "卡尔马", "马尔默", "07月28日")

        # 手动构造(模拟旧snapshot路径标准化后)
        from scraper.crown_odds_collector import normalize_league, normalize_date
        league = normalize_league("瑞典超级联赛")
        date = normalize_date("07月28日")
        mid_manual = f"CROWN_{league}_卡尔马_马尔默_{date}"

        self.assertEqual(mid_collector, mid_manual)

    def test_chinese_alias_consistency(self):
        """中文联赛别名标准化一致"""
        # 皇冠返回"瑞典超级联赛"，系统应统一为"瑞超"
        mid1 = build_match_id("瑞典超级联赛", "A", "B", "01月01日")
        mid2 = build_match_id("瑞典超级甲组联赛", "A", "B", "01月01日")
        # 两者都映射到"瑞超"
        self.assertIn("瑞超", mid1)
        self.assertIn("瑞超", mid2)


class TestCollectorNoBusinessLogic(unittest.TestCase):
    """collector只做标准化+写入，不做业务判断"""

    def test_no_model_import(self):
        import inspect
        from scraper import crown_odds_collector
        src = inspect.getsource(crown_odds_collector)
        self.assertNotIn("StrengthModel", src)
        self.assertNotIn("HandicapModel", src)
        self.assertNotIn("calc_crown_index", src)

    def test_no_recommendation_logic(self):
        import inspect
        from scraper import crown_odds_collector
        src = inspect.getsource(crown_odds_collector)
        self.assertNotIn("generate_recommendation", src)
        self.assertNotIn("filter_by_recommendation", src)


if __name__ == "__main__":
    unittest.main()
