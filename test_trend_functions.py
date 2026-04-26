import pymysql

def get_connection():
    return pymysql.connect(
        host='127.0.0.1',
        port=3306,
        user='root',
        password='123456',
        database='xiaohongshu_analysis',
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

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

# 测试函数
print("Testing get_sentiment_trend:")
sentiment_data = get_sentiment_trend()
print(f"Number of results: {len(sentiment_data)}")
if sentiment_data:
    print("First few results:")
    for i, item in enumerate(sentiment_data[:5]):
        print(f"{i+1}: {item}")

print("\nTesting get_attitude_trend:")
attitude_data = get_attitude_trend()
print(f"Number of results: {len(attitude_data)}")
if attitude_data:
    print("First few results:")
    for i, item in enumerate(attitude_data[:5]):
        print(f"{i+1}: {item}")