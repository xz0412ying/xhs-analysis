"""
posts 表操作服务
"""
import pymysql
from config import DB_CONFIG


def get_connection():
    """创建数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def create_post(title, publish_time, content):
    """
    创建新帖子
    
    Args:
        title: 帖子标题
        publish_time: 发布时间
        content: 帖子内容
        
    Returns:
        int: 新创建的帖子ID
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO posts (title, publish_time, content)
                VALUES (%s, %s, %s)
            """, (title, publish_time, content))
            conn.commit()
            return cursor.lastrowid
    finally:
        conn.close()


def get_post_by_id(post_id):
    """
    根据ID获取帖子
    
    Args:
        post_id: 帖子ID
        
    Returns:
        dict: 帖子信息
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT post_id, title, publish_time, content, theme1, theme2, theme3
                FROM posts
                WHERE post_id = %s
            """, (post_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def update_post_themes(post_id, theme1, theme2, theme3):
    """
    更新帖子的主题
    
    Args:
        post_id: 帖子ID
        theme1: 主题1
        theme2: 主题2
        theme3: 主题3
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE posts
                SET theme1 = %s, theme2 = %s, theme3 = %s
                WHERE post_id = %s
            """, (theme1, theme2, theme3, post_id))
            conn.commit()
    finally:
        conn.close()


def get_all_posts():
    """
    获取所有帖子
    
    Returns:
        list: 帖子列表
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT post_id, title, publish_time, content, theme1, theme2, theme3
                FROM posts
                ORDER BY post_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_by_rank(rank):
    """
    按顺序获取第N个帖子
    
    Args:
        rank: 排序位置（从1开始）
        
    Returns:
        dict: 帖子信息
    """
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT post_id, title, publish_time, content, theme1, theme2, theme3
                FROM posts
                ORDER BY post_id ASC
                LIMIT 1 OFFSET %s
            """, (rank - 1,))
            return cursor.fetchone()
    finally:
        conn.close()
