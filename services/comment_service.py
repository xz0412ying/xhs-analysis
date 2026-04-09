"""
comments 表操作服务
"""
import pymysql
from config import DB_CONFIG


def get_connection():
    """创建数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def create_comment(post_id, comment_content, like_count):
    """
    创建新评论
    
    Args:
        post_id: 帖子ID
        comment_content: 评论内容
        like_count: 点赞数
        
    Returns:
        int: 新创建的评论ID
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO comments (post_id, comment_content, like_count)
                VALUES (%s, %s, %s)
            """, (post_id, comment_content, like_count))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def get_comments_by_post_id(post_id):
    """
    根据帖子ID获取评论
    
    Args:
        post_id: 帖子ID
        
    Returns:
        list: 评论列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT comment_id, post_id, comment_content, like_count,
                       assigned_theme, sentiment_label, sentiment_score, attitude_type
                FROM comments
                WHERE post_id = %s
                ORDER BY like_count DESC, comment_id ASC
            """, (post_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def update_comment_sentiment(comment_id, sentiment_label, sentiment_score, attitude_type):
    """
    更新评论的情感分析结果
    
    Args:
        comment_id: 评论ID
        sentiment_label: 情感标签
        sentiment_score: 情感分数
        attitude_type: 态度类型
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE comments
                SET sentiment_label = %s,
                    sentiment_score = %s,
                    attitude_type = %s
                WHERE comment_id = %s
            """, (sentiment_label, sentiment_score, attitude_type, comment_id))
            conn.commit()
    finally:
        conn.close()


def update_comment_theme(comment_id, assigned_theme):
    """
    更新评论的主题
    
    Args:
        comment_id: 评论ID
        assigned_theme: 分配的主题
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE comments
                SET assigned_theme = %s
                WHERE comment_id = %s
            """, (assigned_theme, comment_id))
            conn.commit()
    finally:
        conn.close()


def get_comment_by_id(comment_id):
    """
    根据ID获取评论
    
    Args:
        comment_id: 评论ID
        
    Returns:
        dict: 评论信息
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT comment_id, post_id, comment_content, like_count,
                       assigned_theme, sentiment_label, sentiment_score, attitude_type
                FROM comments
                WHERE comment_id = %s
            """, (comment_id,))
            return cursor.fetchone()
    finally:
        conn.close()
