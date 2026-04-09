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

def crawl_and_store_post(url, title, publish_time, content):
    conn = get_connection()
    try:
        post_id = insert_post(conn, title, publish_time, content)
        comments = crawl_comments_by_url(url)
        count = insert_comments(conn, post_id, comments)
        return {
            "post_id": post_id,
            "comment_count": count
        }
    finally:
        conn.close()