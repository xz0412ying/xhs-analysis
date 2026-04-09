"""
页面图表数据封装服务
"""
import pymysql
from config import DB_CONFIG


def get_connection():
    """创建数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def get_dashboard_stats():
    """
    获取仪表板统计数据
    
    Returns:
        dict: 统计数据
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM posts")
            post_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("SELECT COUNT(*) AS cnt FROM comments")
            comment_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("SELECT COUNT(*) AS cnt FROM risk_issues")
            risk_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT COUNT(*) AS total_cnt,
                       SUM(CASE WHEN sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt
                FROM comments
                WHERE sentiment_label IS NOT NULL
            """)
            row = cursor.fetchone()
            total_cnt = row["total_cnt"] or 0
            negative_cnt = row["negative_cnt"] or 0
            negative_ratio = round((negative_cnt / total_cnt * 100), 2) if total_cnt else 0

            return {
                "post_count": post_count,
                "comment_count": comment_count,
                "risk_count": risk_count,
                "negative_ratio": negative_ratio
            }
    finally:
        conn.close()


def get_risk_distribution():
    """
    获取风险分布数据
    
    Returns:
        list: 风险分布列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.risk_id, r.risk_name, COUNT(*) AS cnt
                FROM post_risk_map m
                JOIN risk_issues r ON m.risk_id = r.risk_id
                GROUP BY r.risk_id, r.risk_name
                ORDER BY cnt DESC, r.risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_sentiment_overview():
    """
    获取情感概览数据
    
    Returns:
        list: 情感分布列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sentiment_label, COUNT(*) AS cnt
                FROM comments
                WHERE sentiment_label IS NOT NULL
                GROUP BY sentiment_label
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_sentiment_distribution():
    """
    获取风险-情感分布数据
    
    Returns:
        list: 风险-情感分布列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    r.risk_name,
                    c.sentiment_label,
                    COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE c.sentiment_label IS NOT NULL
                GROUP BY r.risk_name, c.sentiment_label
                ORDER BY r.risk_name
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_negative_rate():
    """
    获取风险消极率数据
    
    Returns:
        list: 风险消极率列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    r.risk_name,
                    COUNT(*) AS total_cnt,
                    SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt,
                    ROUND(
                        SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
                        2
                    ) AS negative_rate
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE c.sentiment_label IS NOT NULL
                GROUP BY r.risk_name
                HAVING COUNT(*) > 0
                ORDER BY negative_rate DESC, total_cnt DESC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_trend_monthly(limit=5):
    """
    获取风险时间趋势数据
    
    Args:
        limit: 限制返回的风险数量
        
    Returns:
        list: 风险时间趋势列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.risk_name, COUNT(*) AS cnt
                FROM post_risk_map m
                JOIN risk_issues r ON m.risk_id = r.risk_id
                GROUP BY r.risk_name
                ORDER BY cnt DESC, r.risk_id ASC
                LIMIT %s
            """, (limit,))
            top_risks = cursor.fetchall()
            
            if not top_risks:
                return []
            
            risk_names = [r["risk_name"] for r in top_risks]
            placeholders = ",".join(["%s"] * len(risk_names))
            sql = f"""
                SELECT
                    DATE_FORMAT(p.publish_time, '%%Y-%%m') AS month_label,
                    r.risk_name,
                    COUNT(*) AS cnt
                FROM posts p
                JOIN post_risk_map m ON p.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE p.publish_time IS NOT NULL
                  AND r.risk_name IN ({placeholders})
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m'), r.risk_name
                ORDER BY month_label ASC
            """
            cursor.execute(sql, risk_names)
            return cursor.fetchall()
    finally:
        conn.close()
