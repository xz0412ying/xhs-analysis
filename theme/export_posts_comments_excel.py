"""
将指定 post_id 的帖子行 + 对应评论行导出到单个 Excel 文件（两个 sheet）。
默认导出 post_id 为 1、2、3 的数据。
"""
import os
from datetime import datetime

import pymysql

try:
    import pandas as pd
except ImportError as e:
    raise SystemExit(
        "请先安装: pip install pandas openpyxl\n"
        f"原始错误: {e}"
    ) from e


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
}

# 要导出的帖子 id（可按需修改）
POST_IDS = [1, 2, 3]


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def query_dataframe(conn, sql, params):
    """用 cursor 查询，避免 pandas + pymysql 的 UserWarning。"""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
    return pd.DataFrame(rows, columns=cols)


def main():
    conn = get_connection()
    try:
        placeholders = ",".join(["%s"] * len(POST_IDS))

        sql_posts = f"""
            SELECT *
            FROM posts
            WHERE post_id IN ({placeholders})
            ORDER BY post_id ASC
        """
        sql_comments = f"""
            SELECT *
            FROM comments
            WHERE post_id IN ({placeholders})
            ORDER BY post_id ASC, comment_id ASC
        """

        df_posts = query_dataframe(conn, sql_posts, tuple(POST_IDS))
        df_comments = query_dataframe(conn, sql_comments, tuple(POST_IDS))

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_name = f"xhs_posts_{'_'.join(map(str, POST_IDS))}_{stamp}.xlsx"
        out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), out_name)

        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            df_posts.to_excel(writer, sheet_name="posts", index=False)
            df_comments.to_excel(writer, sheet_name="comments", index=False)

        print(f"导出成功: {out_path}")
        print(f"posts 行数: {len(df_posts)}, comments 行数: {len(df_comments)}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
