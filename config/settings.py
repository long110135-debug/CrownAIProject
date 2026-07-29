"""
皇冠AI赛事研判系统 - 全局配置
"""
import os
from pathlib import Path

# === 项目路径 ===
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "output"
DB_PATH = DATA_DIR / "crown.db"

# 确保目录存在
DATA_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

# === 模型权重(唯一定义处，模型文件从这里读取) ===
MODEL_WEIGHTS = {
    "strength": 0.25,    # 实力模型
    "handicap": 0.30,    # 盘口模型（核心）
    "squad": 0.15,       # 阵容模型
    "market": 0.20,      # 市场模型
    "ai_referee": 0.10,  # AI裁判
}
assert abs(sum(MODEL_WEIGHTS.values()) - 1.0) < 1e-9, \
    f"MODEL_WEIGHTS之和必须为1.0，当前为{sum(MODEL_WEIGHTS.values())}"

# === 皇冠指数公式权重 ===
CROWN_INDEX_WEIGHTS = {
    "handicap_change": 35,   # 盘口变化
    "water_change": 25,      # 水位变化
    "strength_match": 20,    # 实力匹配
    "market_anomaly": 20,    # 市场异常
}

# === 推荐等级阈值 ===
RECOMMEND_THRESHOLDS = {
    "A": 80,   # 皇冠指数 >= 80 → A级 ★★★★★
    "B": 60,   # 皇冠指数 >= 60 → B级 ★★★★
    "C": 0,    # 其余 → C级 观察
}

# === 盘口变化信号 ===
HANDICAP_SIGNALS = {
    "升盘": {"direction": "home", "strength": "positive"},   # 市场增强主队
    "降盘": {"direction": "away", "strength": "positive"},   # 市场增强客队
    "升水": {"direction": "away", "strength": "warning"},    # 主队水位升高=资金流向客队
    "降水": {"direction": "home", "strength": "positive"},   # 主队水位降低=资金流向主队
}

# === 抓取配置 ===
SCRAPER_CONFIG = {
    "timeout": 15,
    "retry_count": 3,
    "retry_delay": 2,
    "request_interval": 1.5,  # 请求间隔(秒)，避免被封
    "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

# === AI配置 ===
AI_CONFIG = {
    "provider": "qwen",  # qwen / deepseek
    "model": "qwen-max",
    "temperature": 0.3,
    "max_tokens": 2000,
}

# === 每日运行配置 ===
DAILY_CONFIG = {
    "max_recommend": 5,      # 每日最多推荐场次
    "max_risk_alert": 3,     # 每日最多风险提示
    "min_crown_index": 40,   # 最低入选皇冠指数
    "report_time": "10:00",  # 报表生成时间
}

# === 版本 ===
VERSION = "Crown_v2.0.0"
# MODEL_VERSION 标记预测记录的模型逻辑版本。
# 2.0 = 重大逻辑修订(时区UTC→CST、赔率格式归一化为亚洲盘、盘口方向语义修复、
#       ai_referee退出方向投票、asian_open存真开盘)。观察期计数从本版本重新起算，
#       旧CrownAI_1.0记录保留为历史但不计入新观察期。
MODEL_VERSION = "CrownAI_2.0"

# === 观察期阶段 ===
# validation = 验证期: 新数据为debug_sample，不计入正式观察期门槛，正式观察期未开始。
# formal     = 正式观察期: 数据计入300/200/50/30门槛。
OBSERVATION_PHASE = "validation"
# 计入正式观察期门槛的模型版本集合。验证期为空 → 正式进度恒0/300。
# 升级某版本为正式时，将其加入此集合(如 ["CrownAI_2.1"])。
FORMAL_OBSERVATION_VERSIONS = []
