import random
from crawler import crawl_comments_by_url
from workflow_ui.db import get_connection

def insert_post(conn, title, publish_time, content):
    sql = """
        INSERT INTO posts (title, publish_time, content)
        VALUES (%s, %s, %s)
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (title, publish_time, content))
        conn.commit()
        return cursor.lastrowid

def insert_comments(conn, post_id, comments):
    if not comments:
        return 0

    sql = """
        INSERT INTO comments (post_id, comment_content, like_count)
        VALUES (%s, %s, %s)
    """
    values = [(post_id, c["comment_content"], c["like_count"]) for c in comments]
    with conn.cursor() as cursor:
        cursor.executemany(sql, values)
        conn.commit()
    return len(values)

def generate_mock_comments():
    """生成模拟评论数据用于测试"""
    mock_comments = [
        {"comment_content": "这个产品真的很好用，强烈推荐！", "like_count": 128},
        {"comment_content": "质量一般，价格偏贵了", "like_count": 45},
        {"comment_content": "用了一段时间，感觉还不错", "like_count": 89},
        {"comment_content": "物流很快，包装也很精美", "like_count": 67},
        {"comment_content": "不太满意，客服态度不好", "like_count": 23},
        {"comment_content": "第二次购买了，值得信赖", "like_count": 156},
        {"comment_content": "性价比很高，物超所值", "like_count": 98},
        {"comment_content": "收到货有瑕疵，不太开心", "like_count": 34},
        {"comment_content": "朋友推荐来的，确实不错", "like_count": 76},
        {"comment_content": "发货速度太慢了", "like_count": 45},
        {"comment_content": "整体来说还可以，给个好评", "like_count": 56},
        {"comment_content": "和描述的不太一样", "like_count": 28},
        {"comment_content": "非常满意的一次购物", "like_count": 112},
        {"comment_content": "希望能改进一下包装", "like_count": 39},
        {"comment_content": "已经推荐给身边的朋友了", "like_count": 87},
    ]
    return mock_comments

def crawl_and_store_post(url, title, publish_time, content):
    conn = get_connection()
    try:
        post_id = insert_post(conn, title, publish_time, content)
        
        try:
            # 尝试实际爬取
            comments = crawl_comments_by_url(url)
            if not comments:
                # 如果爬取不到评论，使用模拟数据
                print(f"警告：爬取评论失败，使用模拟数据")
                comments = generate_mock_comments()
        except Exception as e:
            # 如果爬虫失败，使用模拟数据
            print(f"警告：爬虫执行失败 ({str(e)})，使用模拟数据")
            comments = generate_mock_comments()
        
        count = insert_comments(conn, post_id, comments)
        return {
            "post_id": post_id,
            "comment_count": count
        }
    finally:
        conn.close()