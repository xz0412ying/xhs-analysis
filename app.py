from flask import Flask, render_template, jsonify
import pymysql

app = Flask(__name__)

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

def get_connection():
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print("数据库连接失败：", e)
        raise


def get_all_risks():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name, risk_desc
                FROM risk_type
                ORDER BY risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_posts_by_risk(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险相关的帖子
            try:
                cursor.execute("""
                    SELECT p.post_id, p.title, p.publish_time
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                    ORDER BY p.post_id ASC
                """, (risk_id,))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_posts_by_risk: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


# =========================
# Dashboard
# =========================

def get_dashboard_stats():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM posts")
            post_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("SELECT COUNT(*) AS cnt FROM comments")
            comment_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("SELECT COUNT(*) AS cnt FROM risk_type")
            risk_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM comments
                WHERE sentiment_label IS NOT NULL
            """)
            labeled_comment_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT
                    COUNT(*) AS total_cnt,
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
                "labeled_comment_count": labeled_comment_count,
                "negative_ratio": negative_ratio
            }
    finally:
        conn.close()


def get_risk_distribution():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险分布数据
            try:
                cursor.execute("""
                    SELECT r.risk_id, r.risk_name, COUNT(*) AS cnt
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    JOIN risk_type r ON tb.risk_id = r.risk_id
                    GROUP BY r.risk_id, r.risk_name
                    ORDER BY cnt DESC, r.risk_id ASC
                """)
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_distribution: {e}")
                pass
            
            # 如果没有数据或表不存在，返回所有风险类型，计数为0
            cursor.execute("""
                SELECT risk_id, risk_name, 0 AS cnt
                FROM risk_type
                ORDER BY risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_sentiment_overview():
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
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险情感分布数据
            try:
                cursor.execute("""
                    SELECT
                        r.risk_name,
                        c.sentiment_label,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    JOIN risk_type r ON tb.risk_id = r.risk_id
                    WHERE c.sentiment_label IS NOT NULL
                    GROUP BY r.risk_name, c.sentiment_label
                    ORDER BY r.risk_name
                """)
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_sentiment_distribution: {e}")
                pass
            
            # 如果没有数据或表不存在，返回所有风险类型和情感标签的组合，计数为0
            # 先获取所有风险类型
            cursor.execute("SELECT risk_name FROM risk_type ORDER BY risk_id ASC")
            risks = cursor.fetchall()
            
            # 情感标签列表
            sentiments = ['积极', '中性', '消极']
            
            # 生成所有组合
            result = []
            for risk in risks:
                for sentiment in sentiments:
                    result.append({
                        'risk_name': risk['risk_name'],
                        'sentiment_label': sentiment,
                        'cnt': 0
                    })
            
            return result
    finally:
        conn.close()


def get_risk_negative_rate():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险数据
            try:
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
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    JOIN risk_type r ON tb.risk_id = r.risk_id
                    WHERE c.sentiment_label IS NOT NULL
                    GROUP BY r.risk_name
                    HAVING COUNT(*) > 0
                    ORDER BY negative_rate DESC, total_cnt DESC
                """)
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_negative_rate: {e}")
                pass
            
            # 如果没有数据或表不存在，返回所有风险类型，消极率为0
            cursor.execute("""
                SELECT risk_name, 0 AS total_cnt, 0 AS negative_cnt, 0.00 AS negative_rate
                FROM risk_type
                ORDER BY risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_top_risks(limit=5):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险数据
            try:
                cursor.execute("""
                    SELECT r.risk_name, COUNT(*) AS cnt
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    JOIN risk_type r ON tb.risk_id = r.risk_id
                    GROUP BY r.risk_name
                    ORDER BY cnt DESC, r.risk_id ASC
                    LIMIT %s
                """, (limit,))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_top_risks: {e}")
                pass
            
            # 如果没有数据或表不存在，返回前几个风险类型
            cursor.execute("""
                SELECT risk_name, 0 AS cnt
                FROM risk_type
                ORDER BY risk_id ASC
                LIMIT %s
            """, (limit,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_trend_monthly(limit=5):
    top_risks = get_top_risks(limit)
    risk_names = [r["risk_name"] for r in top_risks]
    if not risk_names:
        return []

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险趋势数据
            try:
                placeholders = ",".join(["%s"] * len(risk_names))
                sql = f"""
                    SELECT
                        DATE_FORMAT(p.publish_time, '%%Y-%%m') AS month_label,
                        r.risk_name,
                        COUNT(*) AS cnt
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    JOIN risk_type r ON tb.risk_id = r.risk_id
                    WHERE p.publish_time IS NOT NULL
                      AND r.risk_name IN ({placeholders})
                    GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m'), r.risk_name
                    ORDER BY month_label ASC
                """
                cursor.execute(sql, risk_names)
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_trend_monthly: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_hot_posts(limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            try:
                cursor.execute("""
                    SELECT
                        p.post_id,
                        p.title,
                        p.publish_time,
                        COUNT(c.comment_id) AS comment_cnt,
                        COALESCE(SUM(c.like_count), 0) AS total_like,
                        GROUP_CONCAT(DISTINCT r.risk_name ORDER BY r.risk_id SEPARATOR '、') AS risks
                    FROM posts p
                    LEFT JOIN comments c ON p.post_id = c.post_id
                    LEFT JOIN post_risk_map prm ON p.post_id = prm.post_id
                    LEFT JOIN risk_type r ON prm.risk_id = r.risk_id
                    GROUP BY p.post_id, p.title, p.publish_time
                    ORDER BY comment_cnt DESC, total_like DESC, p.post_id ASC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
            except Exception:
                # 如果 post_risk_map 表不存在，使用简化查询
                cursor.execute("""
                    SELECT
                        p.post_id,
                        p.title,
                        p.publish_time,
                        COUNT(c.comment_id) AS comment_cnt,
                        COALESCE(SUM(c.like_count), 0) AS total_like,
                        NULL AS risks
                    FROM posts p
                    LEFT JOIN comments c ON p.post_id = c.post_id
                    GROUP BY p.post_id, p.title, p.publish_time
                    ORDER BY comment_cnt DESC, total_like DESC, p.post_id ASC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
    finally:
        conn.close()


def get_risk_cooccurrence_matrix():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name
                FROM risk_type
                ORDER BY risk_id ASC
            """)
            risks = cursor.fetchall()

            if not risks:
                return {"risks": [], "values": []}

            risk_ids = [r["risk_id"] for r in risks]
            risk_names = [r["risk_name"] for r in risks]

            try:
                cursor.execute("""
                    SELECT
                        a.risk_id AS risk_a,
                        b.risk_id AS risk_b,
                        COUNT(*) AS cnt
                    FROM post_risk_map a
                    JOIN post_risk_map b
                      ON a.post_id = b.post_id
                    GROUP BY a.risk_id, b.risk_id
                """)
                rows = cursor.fetchall()

                values = []
                for row in rows:
                    if row["risk_a"] in risk_ids and row["risk_b"] in risk_ids:
                        x = risk_ids.index(row["risk_a"])
                        y = risk_ids.index(row["risk_b"])
                        values.append([x, y, row["cnt"]])
            except Exception:
                # 如果 post_risk_map 表不存在，返回空值
                values = []

            return {
                "risks": risk_names,
                "values": values
            }
    finally:
        conn.close()


def get_risk_heat_scatter():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险热度散点图数据
            try:
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
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    JOIN risk_type r ON tb.risk_id = r.risk_id
                    WHERE c.sentiment_label IS NOT NULL
                    GROUP BY r.risk_name
                    HAVING COUNT(*) > 0
                    ORDER BY total_cnt DESC
                """)
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_heat_scatter: {e}")
                pass
            
            # 如果没有数据或表不存在，返回所有风险类型，计数为0，消极率为0
            cursor.execute("""
                SELECT risk_name, 0 AS total_cnt, 0 AS negative_cnt, 0.00 AS negative_rate
                FROM risk_type
                ORDER BY risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


# =========================
# Risk Detail
# =========================

def get_risk_detail(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name, risk_desc
                FROM risk_type
                WHERE risk_id = %s
            """, (risk_id,))
            risk = cursor.fetchone()

            try:
                # 尝试使用帖子表和主题表的关联来获取风险详情数据
                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                """, (risk_id,))
                post_count = cursor.fetchone()["cnt"] or 0

                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                """, (risk_id,))
                comment_count = cursor.fetchone()["cnt"] or 0

                cursor.execute("""
                    SELECT COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND c.attitude_type IS NOT NULL
                """, (risk_id,))
                labeled_attitude_count = cursor.fetchone()["cnt"] or 0

                cursor.execute("""
                    SELECT
                        COUNT(*) AS total_cnt,
                        SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND c.sentiment_label IS NOT NULL
                """, (risk_id,))
                row = cursor.fetchone()
                total_cnt = row["total_cnt"] or 0
                negative_cnt = row["negative_cnt"] or 0
                negative_ratio = round((negative_cnt / total_cnt * 100), 2) if total_cnt else 0
            except Exception as e:
                print(f"Error in get_risk_detail: {e}")
                # 如果表不存在或查询失败，返回默认值
                post_count = 0
                comment_count = 0
                labeled_attitude_count = 0
                negative_ratio = 0

            return {
                "risk": risk,
                "post_count": post_count,
                "comment_count": comment_count,
                "labeled_attitude_count": labeled_attitude_count,
                "negative_ratio": negative_ratio
            }
    finally:
        conn.close()


def get_risk_sentiment_summary(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险情感摘要
            try:
                cursor.execute("""
                    SELECT c.sentiment_label, COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND c.sentiment_label IS NOT NULL
                    GROUP BY c.sentiment_label
                """, (risk_id,))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_sentiment_summary: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_risk_attitude_summary(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险态度摘要
            try:
                cursor.execute("""
                    SELECT c.attitude_type, COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND c.attitude_type IS NOT NULL
                    GROUP BY c.attitude_type
                    ORDER BY cnt DESC
                """, (risk_id,))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_attitude_summary: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_risk_theme_summary(risk_id, limit=10):
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            try:
                cursor.execute("""
                    SELECT p.bertopic_theme, COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.bertopic_theme IS NOT NULL
                      AND p.bertopic_theme <> ''
                    GROUP BY p.bertopic_theme
                    ORDER BY cnt DESC
                    LIMIT %s
                """, (risk_id, limit))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_theme_summary: {e}")
                pass
            
            return []
    finally:
        conn.close()


def get_risk_trend_detail(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险趋势详情
            try:
                cursor.execute("""
                    SELECT DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt, COUNT(*) AS cnt
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.publish_time IS NOT NULL
                    GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m')
                    ORDER BY dt ASC
                """, (risk_id,))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_trend_detail: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_risk_negative_trend_detail(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险消极趋势详情
            try:
                cursor.execute("""
                    SELECT
                        DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt,
                        SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.publish_time IS NOT NULL
                      AND c.sentiment_label IS NOT NULL
                    GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m')
                    ORDER BY dt ASC
                """, (risk_id,))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_negative_trend_detail: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_risk_attitude_trend(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险的态度类型时间演化数据
            try:
                cursor.execute("""
                    SELECT
                        DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt,
                        c.attitude_type,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND c.attitude_type IS NOT NULL
                      AND p.publish_time IS NOT NULL
                    GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m'), c.attitude_type
                    ORDER BY dt ASC, cnt DESC
                """, (risk_id,))
                # 只返回数量最多的前5个态度类型
                results = cursor.fetchall()
                if not results:
                    return []
                
                # 统计每个态度类型的总数量
                attitude_counts = {}
                for item in results:
                    attitude = item['attitude_type']
                    attitude_counts[attitude] = attitude_counts.get(attitude, 0) + item['cnt']
                
                # 按总数量排序，取前5个
                top_attitudes = sorted(attitude_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                top_attitude_names = [attitude for attitude, _ in top_attitudes]
                
                # 只返回前5个态度类型的数据
                filtered_results = [item for item in results if item['attitude_type'] in top_attitude_names]
                return filtered_results
            except Exception as e:
                print(f"Error in get_risk_attitude_trend: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_sentiment_trend():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试获取情感时间演化趋势数据
            try:
                # 使用帖子表的发布时间
                cursor.execute("""
                    SELECT
                        DATE_FORMAT(p.publish_time, '%Y-%m') AS month_label,
                        c.sentiment_label,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    WHERE c.sentiment_label IS NOT NULL
                      AND p.publish_time IS NOT NULL
                    GROUP BY DATE_FORMAT(p.publish_time, '%Y-%m'), c.sentiment_label
                    ORDER BY month_label ASC, cnt DESC
                """)
                results = cursor.fetchall()
                if results:
                    return results
            except Exception as e:
                print(f"Error in get_sentiment_trend: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_attitude_trend():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试获取态度类型时间演化趋势数据
            try:
                # 使用帖子表的发布时间
                cursor.execute("""
                    SELECT
                        DATE_FORMAT(p.publish_time, '%Y-%m') AS month_label,
                        c.attitude_type,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    WHERE c.attitude_type IS NOT NULL
                      AND p.publish_time IS NOT NULL
                    GROUP BY DATE_FORMAT(p.publish_time, '%Y-%m'), c.attitude_type
                    ORDER BY month_label ASC, cnt DESC
                """)
                results = cursor.fetchall()
                
                # 只返回数量最多的前5个态度类型
                if not results:
                    return []
                
                # 统计每个态度类型的总数量
                attitude_counts = {}
                for item in results:
                    attitude = item['attitude_type']
                    attitude_counts[attitude] = attitude_counts.get(attitude, 0) + item['cnt']
                
                # 按总数量排序，取前5个
                top_attitudes = sorted(attitude_counts.items(), key=lambda x: x[1], reverse=True)[:5]
                top_attitude_names = [attitude for attitude, _ in top_attitudes]
                
                # 只返回前5个态度类型的数据
                filtered_results = [item for item in results if item['attitude_type'] in top_attitude_names]
                return filtered_results
            except Exception as e:
                print(f"Error in get_attitude_trend: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_risk_hot_posts(risk_id, limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试使用帖子表和主题表的关联来获取风险相关的热门帖子
            try:
                cursor.execute("""
                    SELECT
                        p.post_id,
                        p.title,
                        p.publish_time,
                        COUNT(c.comment_id) AS comment_cnt,
                        COALESCE(SUM(c.like_count), 0) AS total_like
                    FROM posts p
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    LEFT JOIN comments c ON p.post_id = c.post_id
                    WHERE tb.risk_id = %s
                    GROUP BY p.post_id, p.title, p.publish_time
                    ORDER BY comment_cnt DESC, total_like DESC, p.post_id ASC
                    LIMIT %s
                """, (risk_id, limit))
                result = cursor.fetchall()
                if result:
                    return result
            except Exception as e:
                print(f"Error in get_risk_hot_posts: {e}")
                pass
            
            # 如果没有数据或表不存在，返回空列表
            return []
    finally:
        conn.close()


def get_all_themes():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DISTINCT bertopic_theme
                FROM posts
                WHERE bertopic_theme IS NOT NULL
                  AND bertopic_theme <> ''
                ORDER BY bertopic_theme ASC
            """)
            return [row['bertopic_theme'] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_risk_themes(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT theme
                FROM theme_bertopic
                WHERE risk_id = %s
                  AND theme IS NOT NULL
                  AND theme <> ''
                ORDER BY theme ASC
            """, (risk_id,))
            return [row['theme'] for row in cursor.fetchall()]
    finally:
        conn.close()


def get_theme_posts(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT p.post_id, p.title, p.publish_time
                FROM posts p
                WHERE p.bertopic_theme = %s
                ORDER BY p.post_id ASC
            """, (theme,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_theme_detail(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 获取主题相关的帖子数量
            cursor.execute("""
                SELECT COUNT(*) AS post_count
                FROM posts
                WHERE bertopic_theme = %s
            """, (theme,))
            post_count = cursor.fetchone()["post_count"] or 0

            # 获取主题相关的评论数量
            cursor.execute("""
                SELECT COUNT(*) AS comment_count
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE p.bertopic_theme = %s
            """, (theme,))
            comment_count = cursor.fetchone()["comment_count"] or 0

            # 获取主题的情感分布
            cursor.execute("""
                SELECT c.sentiment_label, COUNT(*) AS cnt
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE p.bertopic_theme = %s
                  AND c.sentiment_label IS NOT NULL
                GROUP BY c.sentiment_label
            """, (theme,))
            sentiment_dist = cursor.fetchall()

            return {
                "theme": theme,
                "post_count": post_count,
                "comment_count": comment_count,
                "sentiment_dist": sentiment_dist
            }
    finally:
        conn.close()


def get_theme_trend(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt,
                    COUNT(*) AS cnt
                FROM posts p
                WHERE p.bertopic_theme = %s
                  AND p.publish_time IS NOT NULL
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m')
                ORDER BY dt ASC
            """, (theme,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_theme_attitude(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.attitude_type, COUNT(*) AS cnt
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE p.bertopic_theme = %s
                  AND c.attitude_type IS NOT NULL
                GROUP BY c.attitude_type
                ORDER BY cnt DESC
            """, (theme,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_theme_negative_trend(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt,
                    COUNT(*) AS cnt
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE p.bertopic_theme = %s
                  AND c.sentiment_label = '消极'
                  AND p.publish_time IS NOT NULL
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m')
                ORDER BY dt ASC
            """, (theme,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_theme_attitude_trend(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt,
                    c.attitude_type,
                    COUNT(*) AS cnt
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE p.bertopic_theme = %s
                  AND c.attitude_type IS NOT NULL
                  AND p.publish_time IS NOT NULL
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m'), c.attitude_type
                ORDER BY dt ASC, cnt DESC
            """, (theme,))
            # 只返回数量最多的前5个态度类型
            results = cursor.fetchall()
            if not results:
                return []
            
            # 统计每个态度类型的总数量
            attitude_counts = {}
            for item in results:
                attitude = item['attitude_type']
                attitude_counts[attitude] = attitude_counts.get(attitude, 0) + item['cnt']
            
            # 按总数量排序，取前5个
            top_attitudes = sorted(attitude_counts.items(), key=lambda x: x[1], reverse=True)[:5]
            top_attitude_names = [attitude for attitude, _ in top_attitudes]
            
            # 只返回前5个态度类型的数据
            filtered_results = [item for item in results if item['attitude_type'] in top_attitude_names]
            return filtered_results
    finally:
        conn.close()


def get_risk_theme_attitude_matrix(risk_id, theme_limit=8):
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            try:
                cursor.execute("""
                    SELECT p.bertopic_theme
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.bertopic_theme IS NOT NULL
                      AND p.bertopic_theme <> ''
                    GROUP BY p.bertopic_theme
                    ORDER BY COUNT(*) DESC
                    LIMIT %s
                """, (risk_id, theme_limit))
                top_theme_rows = cursor.fetchall()
                top_themes = [row["bertopic_theme"] for row in top_theme_rows]

                if not top_themes:
                    return {"themes": [], "attitudes": [], "values": []}

                placeholders = ",".join(["%s"] * len(top_themes))
                sql = f"""
                    SELECT
                        p.bertopic_theme,
                        c.attitude_type,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.bertopic_theme IN ({placeholders})
                      AND c.attitude_type IS NOT NULL
                    GROUP BY p.bertopic_theme, c.attitude_type
                    ORDER BY p.bertopic_theme, c.attitude_type
                """
                cursor.execute(sql, [risk_id] + top_themes)
                rows = cursor.fetchall()

                attitudes = sorted(list({row["attitude_type"] for row in rows if row["attitude_type"]}))
                values = []
                for row in rows:
                    if row["bertopic_theme"] in top_themes and row["attitude_type"] in attitudes:
                        x = top_themes.index(row["bertopic_theme"])
                        y = attitudes.index(row["attitude_type"])
                        values.append([x, y, row["cnt"]])

                return {
                    "themes": top_themes,
                    "attitudes": attitudes,
                    "values": values
                }
            except Exception as e:
                print(f"Error in get_risk_theme_attitude_matrix: {e}")
                return {"themes": [], "attitudes": [], "values": []}
    finally:
        conn.close()


def get_risk_theme_sentiment_distribution(risk_id, theme_limit=8):
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            try:
                cursor.execute("""
                    SELECT p.bertopic_theme
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.bertopic_theme IS NOT NULL
                      AND p.bertopic_theme <> ''
                    GROUP BY p.bertopic_theme
                    ORDER BY COUNT(*) DESC
                    LIMIT %s
                """, (risk_id, theme_limit))
                top_theme_rows = cursor.fetchall()
                top_themes = [row["bertopic_theme"] for row in top_theme_rows]

                if not top_themes:
                    return []

                placeholders = ",".join(["%s"] * len(top_themes))
                sql = f"""
                    SELECT
                        p.bertopic_theme,
                        c.sentiment_label,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN posts p ON c.post_id = p.post_id
                    JOIN theme_bertopic tb ON p.bertopic_theme = tb.theme
                    WHERE tb.risk_id = %s
                      AND p.bertopic_theme IN ({placeholders})
                      AND c.sentiment_label IS NOT NULL
                    GROUP BY p.bertopic_theme, c.sentiment_label
                    ORDER BY p.bertopic_theme, c.sentiment_label
                """
                cursor.execute(sql, [risk_id] + top_themes)
                return cursor.fetchall()
            except Exception as e:
                print(f"Error in get_risk_theme_sentiment_distribution: {e}")
                return []
    finally:
        conn.close()


# =========================
# Post Detail
# =========================

def get_post_detail(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT post_id, title, publish_time, content, bertopic_theme
                FROM posts
                WHERE post_id = %s
            """, (post_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def get_post_risks(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            # 尝试查询，如果表不存在则返回空列表
            try:
                cursor.execute("""
                    SELECT r.risk_id, r.risk_name
                    FROM post_risk_map m
                    JOIN risk_type r ON m.risk_id = r.risk_id
                    WHERE m.post_id = %s
                    ORDER BY r.risk_id ASC
                """, (post_id,))
                return cursor.fetchall()
            except Exception:
                return []
    finally:
        conn.close()


def get_post_sentiment_summary(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sentiment_label, COUNT(*) AS cnt
                FROM comments
                WHERE post_id = %s
                  AND sentiment_label IS NOT NULL
                GROUP BY sentiment_label
            """, (post_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_attitude_summary(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT attitude_type, COUNT(*) AS cnt
                FROM comments
                WHERE post_id = %s
                  AND attitude_type IS NOT NULL
                GROUP BY attitude_type
                ORDER BY cnt DESC
            """, (post_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_theme_summary(post_id, limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT assigned_theme, COUNT(*) AS cnt
                FROM comments
                WHERE post_id = %s
                  AND assigned_theme IS NOT NULL
                  AND assigned_theme <> ''
                GROUP BY assigned_theme
                ORDER BY cnt DESC
                LIMIT %s
            """, (post_id, limit))
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_theme_sentiment_distribution(post_id, theme_limit=8):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT assigned_theme
                FROM (
                    SELECT assigned_theme, COUNT(*) AS cnt
                    FROM comments
                    WHERE post_id = %s
                      AND assigned_theme IS NOT NULL
                      AND assigned_theme <> ''
                    GROUP BY assigned_theme
                    ORDER BY cnt DESC
                    LIMIT %s
                ) t
            """, (post_id, theme_limit))
            top_theme_rows = cursor.fetchall()
            top_themes = [row["assigned_theme"] for row in top_theme_rows]

            if not top_themes:
                return []

            placeholders = ",".join(["%s"] * len(top_themes))
            sql = f"""
                SELECT assigned_theme, sentiment_label, COUNT(*) AS cnt
                FROM comments
                WHERE post_id = %s
                  AND assigned_theme IN ({placeholders})
                  AND sentiment_label IS NOT NULL
                GROUP BY assigned_theme, sentiment_label
                ORDER BY assigned_theme, sentiment_label
            """
            cursor.execute(sql, [post_id] + top_themes)
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_theme_attitude_matrix(post_id, theme_limit=8):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT assigned_theme
                FROM (
                    SELECT assigned_theme, COUNT(*) AS cnt
                    FROM comments
                    WHERE post_id = %s
                      AND assigned_theme IS NOT NULL
                      AND assigned_theme <> ''
                    GROUP BY assigned_theme
                    ORDER BY cnt DESC
                    LIMIT %s
                ) t
            """, (post_id, theme_limit))
            top_theme_rows = cursor.fetchall()
            top_themes = [row["assigned_theme"] for row in top_theme_rows]

            if not top_themes:
                return {"themes": [], "attitudes": [], "values": []}

            placeholders = ",".join(["%s"] * len(top_themes))
            sql = f"""
                SELECT assigned_theme, attitude_type, COUNT(*) AS cnt
                FROM comments
                WHERE post_id = %s
                  AND assigned_theme IN ({placeholders})
                  AND attitude_type IS NOT NULL
                GROUP BY assigned_theme, attitude_type
                ORDER BY assigned_theme, attitude_type
            """
            cursor.execute(sql, [post_id] + top_themes)
            rows = cursor.fetchall()

            attitudes = sorted(list({row["attitude_type"] for row in rows if row["attitude_type"]}))
            values = []
            for row in rows:
                if row["assigned_theme"] in top_themes and row["attitude_type"] in attitudes:
                    x = top_themes.index(row["assigned_theme"])
                    y = attitudes.index(row["attitude_type"])
                    values.append([x, y, row["cnt"]])

            return {
                "themes": top_themes,
                "attitudes": attitudes,
                "values": values
            }
    finally:
        conn.close()


def get_post_comments(post_id, limit=15):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT comment_id, comment_content, like_count, assigned_theme, sentiment_label, attitude_type
                FROM comments
                WHERE post_id = %s
                ORDER BY like_count DESC, comment_id ASC
                LIMIT %s
            """, (post_id, limit))
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_wordcloud_data(post_id, limit=50):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.comment_content
                FROM comments c
                WHERE c.post_id = %s
                  AND c.comment_content IS NOT NULL
                  AND c.comment_content <> ''
            """, (post_id,))
            comments = cursor.fetchall()
            all_text = " ".join([row[0] for row in comments])
            
            return extract_top_words(all_text, limit)
    finally:
        conn.close()


def get_theme_wordcloud_data(theme, limit=50):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.comment_content
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                WHERE p.bertopic_theme = %s
                  AND c.comment_content IS NOT NULL
                  AND c.comment_content <> ''
            """, (theme,))
            comments = cursor.fetchall()
            all_text = " ".join([row[0] for row in comments])
            
            return extract_top_words(all_text, limit)
    finally:
        conn.close()


import re
import jieba

def extract_top_words(text, limit=50):
    stopwords = set([
        "的", "了", "和", "是", "就", "都", "而", "及", "与", "着", "或", "一个", "没有", "我们", "你们",
        "他们", "它们", "这个", "那个", "这些", "那些", "什么", "怎么", "为什么", "因为", "所以",
        "但是", "然而", "可是", "不过", "虽然", "如果", "要是", "只要", "只有", "就", "才", "都",
        "很", "非常", "特别", "十分", "太", "更", "最", "还", "也", "又", "再", "已经", "曾经",
        "正在", "将要", "会", "能", "可以", "应该", "必须", "需要", "可能", "应该", "要", "不",
        "没有", "别", "不要", "不能", "不会", "不想", "不敢", "不必", "不用", "小红书", "AI", "ai",
        "人工智能", "自己", "觉得", "认为", "知道", "说", "看", "听", "想", "做", "有", "在", "到",
        "上", "下", "来", "去", "过", "回", "出", "进", "给", "拿", "放", "开", "关", "走", "跑",
        "跳", "飞", "吃", "喝", "睡", "玩", "学", "写", "读", "看", "听", "说", "唱", "跳", "笑"
    ])
    
    words = jieba.cut(text)
    word_counts = {}
    
    for word in words:
        word = word.strip()
        if len(word) >= 2 and word not in stopwords:
            word_counts[word] = word_counts.get(word, 0) + 1
    
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    
    return [{"word": word, "count": count} for word, count in sorted_words]


# =========================
# Routes
# =========================

@app.route("/")
def dashboard():
    risks = get_all_risks()
    stats = get_dashboard_stats()
    hot_posts = get_hot_posts(10)
    themes = get_all_themes()
    return render_template(
        "dashboard.html",
        page_title="总分析页",
        risks=risks,
        themes=themes,
        current_page="dashboard",
        current_risk_id=None,
        current_post_id=None,
        posts_for_sidebar=[],
        stats=stats,
        hot_posts=hot_posts,
        risk_themes=[]
    )


@app.route("/risk/<int:risk_id>")
def risk_detail(risk_id):
    risks = get_all_risks()
    posts_for_sidebar = get_posts_by_risk(risk_id)
    detail = get_risk_detail(risk_id)
    hot_posts = get_risk_hot_posts(risk_id, 10)
    risk_themes = get_risk_themes(risk_id)
    return render_template(
        "risk_detail.html",
        page_title="单风险分析",
        risks=risks,
        current_page="risk",
        current_risk_id=risk_id,
        current_post_id=None,
        posts_for_sidebar=posts_for_sidebar,
        risk_detail=detail,
        hot_posts=hot_posts,
        risk_themes=risk_themes
    )


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    risks = get_all_risks()
    post = get_post_detail(post_id)
    post_risks = get_post_risks(post_id)

    posts_for_sidebar = []
    current_risk_id = None
    risk_themes = []
    if post_risks:
        current_risk_id = post_risks[0]["risk_id"]
        posts_for_sidebar = get_posts_by_risk(current_risk_id)
        risk_themes = get_risk_themes(current_risk_id)

    return render_template(
        "post_detail.html",
        page_title="单帖子分析",
        risks=risks,
        current_page="post",
        current_risk_id=current_risk_id,
        current_post_id=post_id,
        posts_for_sidebar=posts_for_sidebar,
        post=post,
        post_risks=post_risks,
        comments=get_post_comments(post_id, 15),
        risk_themes=risk_themes
    )


def get_theme_distribution():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    bertopic_theme as theme,
                    COUNT(*) as cnt
                FROM
                    posts
                WHERE
                    bertopic_theme IS NOT NULL
                    AND bertopic_theme <> ''
                GROUP BY
                    bertopic_theme
                ORDER BY
                    cnt DESC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_theme_risk_id(theme):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id
                FROM theme_bertopic
                WHERE theme = %s
                LIMIT 1
            """, (theme,))
            result = cursor.fetchone()
            return result['risk_id'] if result else None
    finally:
        conn.close()


@app.route("/theme/<theme>")
def theme_detail(theme):
    risks = get_all_risks()
    themes = get_all_themes()
    posts_for_sidebar = get_theme_posts(theme)
    detail = get_theme_detail(theme)
    current_risk_id = get_theme_risk_id(theme)
    risk_themes = get_risk_themes(current_risk_id) if current_risk_id else []
    return render_template(
        "theme_detail.html",
        page_title="主题分析",
        risks=risks,
        themes=themes,
        current_page="theme",
        current_risk_id=current_risk_id,
        current_theme=theme,
        current_post_id=None,
        posts_for_sidebar=posts_for_sidebar,
        theme_detail=detail,
        risk_themes=risk_themes
    )


@app.route("/themes")
def themes_overview():
    risks = get_all_risks()
    themes = get_all_themes()
    # 获取统计信息
    stats = get_dashboard_stats()
    return render_template(
        "themes_overview.html",
        page_title="总主题分析",
        risks=risks,
        themes=themes,
        current_page="themes",
        current_risk_id=None,
        current_post_id=None,
        posts_for_sidebar=[],
        stats=stats,
        risk_themes=[]
    )


# =========================
# APIs
# =========================

@app.route("/api/risk_distribution")
def api_risk_distribution():
    return jsonify(get_risk_distribution())


@app.route("/api/sentiment_overview")
def api_sentiment_overview():
    return jsonify(get_sentiment_overview())


@app.route("/api/risk_sentiment_distribution")
def api_risk_sentiment_distribution():
    return jsonify(get_risk_sentiment_distribution())


@app.route("/api/risk_negative_rate")
def api_risk_negative_rate():
    return jsonify(get_risk_negative_rate())


@app.route("/api/risk_trend")
def api_risk_trend():
    return jsonify(get_risk_trend_monthly(5))


@app.route("/api/risk_cooccurrence")
def api_risk_cooccurrence():
    return jsonify(get_risk_cooccurrence_matrix())


@app.route("/api/risk_heat_scatter")
def api_risk_heat_scatter():
    return jsonify(get_risk_heat_scatter())


@app.route("/api/risk/<int:risk_id>/sentiment")
def api_risk_sentiment(risk_id):
    return jsonify(get_risk_sentiment_summary(risk_id))


@app.route("/api/risk/<int:risk_id>/attitude")
def api_risk_attitude(risk_id):
    return jsonify(get_risk_attitude_summary(risk_id))


@app.route("/api/risk/<int:risk_id>/themes")
def api_risk_themes(risk_id):
    return jsonify(get_risk_theme_summary(risk_id, 10))


@app.route("/api/risk/<int:risk_id>/trend")
def api_risk_trend_detail(risk_id):
    return jsonify(get_risk_trend_detail(risk_id))


@app.route("/api/risk/<int:risk_id>/negative_trend")
def api_risk_negative_trend(risk_id):
    return jsonify(get_risk_negative_trend_detail(risk_id))


@app.route("/api/risk/<int:risk_id>/attitude_trend")
def api_risk_attitude_trend(risk_id):
    return jsonify(get_risk_attitude_trend(risk_id))


@app.route("/api/sentiment_trend")
def api_sentiment_trend():
    return jsonify(get_sentiment_trend())


@app.route("/api/attitude_trend")
def api_attitude_trend():
    return jsonify(get_attitude_trend())


@app.route("/api/risk/<int:risk_id>/theme_attitude_matrix")
def api_risk_theme_attitude_matrix(risk_id):
    print(f"DEBUG: api_risk_theme_attitude_matrix called with risk_id={risk_id}")
    result = get_risk_theme_attitude_matrix(risk_id, 8)
    print(f"DEBUG: result: {result}")
    return jsonify(result)


@app.route("/api/risk/<int:risk_id>/theme_sentiment_distribution")
def api_risk_theme_sentiment_distribution(risk_id):
    print(f"DEBUG: api_risk_theme_sentiment_distribution called with risk_id={risk_id}")
    result = get_risk_theme_sentiment_distribution(risk_id, 8)
    print(f"DEBUG: result: {result}")
    return jsonify(result)


@app.route("/api/post/<int:post_id>/sentiment")
def api_post_sentiment(post_id):
    return jsonify(get_post_sentiment_summary(post_id))


@app.route("/api/post/<int:post_id>/attitude")
def api_post_attitude(post_id):
    return jsonify(get_post_attitude_summary(post_id))


@app.route("/api/post/<int:post_id>/themes")
def api_post_themes(post_id):
    return jsonify(get_post_theme_summary(post_id, 10))


@app.route("/api/theme_distribution")
def api_theme_distribution():
    return jsonify(get_theme_distribution())


@app.route("/api/post/<int:post_id>/theme_sentiment_distribution")
def api_post_theme_sentiment(post_id):
    return jsonify(get_post_theme_sentiment_distribution(post_id, 8))


@app.route("/api/post/<int:post_id>/theme_attitude_matrix")
def api_post_theme_attitude(post_id):
    return jsonify(get_post_theme_attitude_matrix(post_id, 8))


@app.route("/api/post/<int:post_id>/wordcloud")
def api_post_wordcloud(post_id):
    return jsonify(get_post_wordcloud_data(post_id, 50))


@app.route("/api/theme/<theme>/wordcloud")
def api_theme_wordcloud(theme):
    return jsonify(get_theme_wordcloud_data(theme, 50))


@app.route("/api/themes")
def api_themes():
    return jsonify(get_all_themes())


@app.route("/api/risk/<int:risk_id>/themes_list")
def api_risk_themes_list(risk_id):
    return jsonify(get_risk_themes(risk_id))


@app.route("/api/theme/<theme>/posts")
def api_theme_posts(theme):
    return jsonify(get_theme_posts(theme))


@app.route("/api/theme/<theme>/detail")
def api_theme_detail(theme):
    return jsonify(get_theme_detail(theme))


@app.route("/api/theme/<theme>/trend")
def api_theme_trend(theme):
    return jsonify(get_theme_trend(theme))


@app.route("/api/theme/<theme>/attitude")
def api_theme_attitude(theme):
    return jsonify(get_theme_attitude(theme))


@app.route("/api/theme/<theme>/negative-trend")
def api_theme_negative_trend(theme):
    return jsonify(get_theme_negative_trend(theme))


@app.route("/api/theme/<theme>/attitude-trend")
def api_theme_attitude_trend(theme):
    return jsonify(get_theme_attitude_trend(theme))


if __name__ == "__main__":
    app.run(debug=False)