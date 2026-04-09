"""
配置文件：集中管理数据库和DeepSeek API配置
"""
import os


# =========================
# 数据库配置
# =========================
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", "123456"),
    "database": os.getenv("DB_NAME", "xiaohongshu_analysis"),
    "charset": os.getenv("DB_CHARSET", "utf8mb4"),
    "cursorclass": os.getenv("DB_CURSOR_CLASS", "pymysql.cursors.DictCursor")
}


# =========================
# DeepSeek API配置
# =========================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-03214af033c741ad8dbc45e59976a27e")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


# =========================
# 其他配置
# =========================
# 单个帖子内容截断，避免 prompt 太长
MAX_CONTENT_LEN = 800

# 风险数量范围
MIN_RISK_COUNT = 5
MAX_RISK_COUNT = 8

# 是否每次重跑时清空旧映射
CLEAR_OLD_POST_RISK_MAP = True

# 是否每次重跑时清空 risk_issues 表
CLEAR_OLD_RISK_ISSUES = True
