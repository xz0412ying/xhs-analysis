import os
import pymysql

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

DEEPSEEK_API_KEY = os.getenv("", "").strip()
DEEPSEEK_BASE_URL = os.getenv("", "https://api.deepseek.com").strip()
DEEPSEEK_MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")

TASK_STATUS = {
    "PENDING": "PENDING",
    "RUNNING": "RUNNING",
    "SUCCESS": "SUCCESS",
    "FAILED": "FAILED"
}

TASK_STEPS = {
    "INIT": "任务初始化",
    "CREATED": "任务已创建",
    "CRAWLING": "爬取评论",
    "STORING": "写入数据库",
    "THEME": "主题分析",
    "SENTIMENT": "情感分析",
    "RISK": "风险判断",
    "DONE": "分析完成",
    "ERROR": "执行失败"
}