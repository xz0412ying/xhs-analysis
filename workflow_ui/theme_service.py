import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from theme.threetheme.theme_generate_deepseek_first_post import (
    get_connection,
    get_post_comments,
    select_representative_comments,
    call_llm_generate_themes,
    assign_comment_themes,
    update_post_themes,
    update_comment_assigned_theme
)

def get_post_by_id(conn, post_id):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT post_id, title, content
            FROM posts
            WHERE post_id = %s
        """, (post_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return {
            "post_id": row["post_id"] if isinstance(row, dict) else row[0],
            "title": row["title"] if isinstance(row, dict) else row[1],
            "content": row["content"] if isinstance(row, dict) else row[2],
        }

def run_theme_analysis_for_post_id(post_id):
    conn = get_connection()
    try:
        post = get_post_by_id(conn, post_id)
        if not post:
            raise RuntimeError(f"post_id={post_id} 不存在")

        comments = get_post_comments(conn, post_id, limit=800)
        if not comments:
            raise RuntimeError(f"post_id={post_id} 没有评论")

        comments_for_llm = select_representative_comments(comments, keep_count=90)
        theme1, theme2, theme3 = call_llm_generate_themes(post, comments_for_llm)

        update_post_themes(conn, post_id, theme1, theme2, theme3)
        updates, theme_count = assign_comment_themes(post, comments, theme1, theme2, theme3, debug=False)
        update_comment_assigned_theme(conn, updates)

        return {
            "theme1": theme1,
            "theme2": theme2,
            "theme3": theme3,
            "theme_count": dict(theme_count)
        }
    finally:
        conn.close()