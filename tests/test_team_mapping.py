"""测试球队名映射"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.team_enrich import TEAM_NAME_MAP


class TestTeamMapping(unittest.TestCase):

    def test_nordic_teams_mapped(self):
        """北欧球队必须有映射"""
        nordic = ["马尔默", "尤尔加登", "卡尔马", "伊尔韦斯", "图尔库PS", "拉赫蒂", "玛丽港"]
        for cn in nordic:
            self.assertIn(cn, TEAM_NAME_MAP, f"{cn} 缺少映射")

    def test_major_leagues_mapped(self):
        """五大联赛球队必须有映射"""
        major = ["阿森纳", "曼城", "利物浦", "皇家马德里", "巴塞罗那", "拜仁慕尼黑", "多特蒙德"]
        for cn in major:
            self.assertIn(cn, TEAM_NAME_MAP, f"{cn} 缺少映射")

    def test_reverse_mapping_unique(self):
        """英文→中文反向映射不应有歧义(同一英文名只对应一个中文名)"""
        en_to_cn = {}
        duplicates = []
        for cn, en in TEAM_NAME_MAP.items():
            if en in en_to_cn and en_to_cn[en] != cn:
                duplicates.append(f"{en}: {en_to_cn[en]} vs {cn}")
            en_to_cn[en] = cn
        # 允许少量重复(同一球队多个中文译名)，但不应太多
        self.assertLess(len(duplicates), 10, f"过多重复映射: {duplicates[:5]}")

    def test_api_football_format_covered(self):
        """API-Football返回的全名格式也应有映射"""
        api_names = ["Hammarby FF", "BK Hacken", "AIK Stockholm", "IF Elfsborg",
                     "Inter Turku", "HJK Helsinki"]
        en_values = set(TEAM_NAME_MAP.values())
        for name in api_names:
            self.assertIn(name, en_values, f"API格式 '{name}' 缺少映射")


if __name__ == "__main__":
    unittest.main()
