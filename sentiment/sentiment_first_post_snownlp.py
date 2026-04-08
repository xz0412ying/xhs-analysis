import pymysql
from snownlp import SnowNLP

# =========================
# 数据库配置
# =========================
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",   # 改成你的 MySQL 密码
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4"
}

# =========================
# 要分析第几个帖子
# posts 表按 post_id 升序后的第几条
# =========================
POST_RANK = 3

# =========================
# SnowNLP 情感阈值
# 可后续根据实际效果调整
# =========================
POSITIVE_THRESHOLD = 0.6
NEGATIVE_THRESHOLD = 0.4


def get_connection():
    return pymysql.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        charset=DB_CONFIG["charset"],
        cursorclass=pymysql.cursors.DictCursor
    )


def normalize_text(text: str) -> str:
    """简单清洗文本"""
    if not text:
        return ""
    return text.strip().replace("\n", " ").replace("\r", " ")


def classify_sentiment(text: str):
    """
    使用 SnowNLP 进行情感分析
    返回:
        score: 0~1
        label: 正面 / 中性 / 负面
    """
    clean_text = normalize_text(text)

    if not clean_text:
        return 0.5, "中性"

    try:
        s = SnowNLP(clean_text)
        score = float(s.sentiments)

        if score >= POSITIVE_THRESHOLD:
            label = "正面"
        elif score <= NEGATIVE_THRESHOLD:
            label = "负面"
        else:
            label = "中性"

        return round(score, 4), label

    except Exception as e:
        print(f"[分析失败] 文本: {clean_text[:30]}... | 错误: {e}")
        return 0.5, "中性"


def get_post_by_rank(conn, post_rank: int):
    """
    获取 posts 表中第 post_rank 条帖子
    按 post_id 升序取
    """
    with conn.cursor() as cursor:
        sql = """
            SELECT post_id, title, content, publish_time
            FROM posts
            ORDER BY post_id ASC
            LIMIT 1 OFFSET %s
        """
        cursor.execute(sql, (post_rank - 1,))
        return cursor.fetchone()


def get_comments_by_post_id(conn, post_id):
    """
    获取指定帖子下的全部评论
    """
    with conn.cursor() as cursor:
        sql = """
            SELECT comment_id, post_id, comment_content
            FROM comments
            WHERE post_id = %s
            ORDER BY comment_id ASC
        """
        cursor.execute(sql, (post_id,))
        return cursor.fetchall()


def update_comment_sentiment(conn, comment_id, score, label):
    """
    更新评论情感结果
    """
    with conn.cursor() as cursor:
        sql = """
            UPDATE comments
            SET sentiment_score = %s,
                sentiment_label = %s
            WHERE comment_id = %s
        """
        cursor.execute(sql, (score, label, comment_id))


def analyze_first_post_comments():
    conn = None
    try:
        conn = get_connection()

        post = get_post_by_rank(conn, POST_RANK)
        if not post:
            print(f"posts 表中没有第 {POST_RANK} 条帖子。")
            return

        post_id = post["post_id"]
        title = post.get("title", "")
        publish_time = post.get("publish_time", "")

        print(f"开始分析第 {POST_RANK} 条帖子")
        print(f"post_id: {post_id}")
        print(f"title: {title}")
        print(f"publish_time: {publish_time}")

        comments = get_comments_by_post_id(conn, post_id)
        if not comments:
            print("这个帖子没有评论。")
            return

        print(f"\n共找到 {len(comments)} 条评论，开始进行 SnowNLP 情感分析...\n")

        positive_count = 0
        neutral_count = 0
        negative_count = 0

        for i, row in enumerate(comments, start=1):
            comment_id = row["comment_id"]
            content = row.get("comment_content", "")

            score, label = classify_sentiment(content)
            update_comment_sentiment(conn, comment_id, score, label)

            if label == "正面":
                positive_count += 1
            elif label == "负面":
                negative_count += 1
            else:
                neutral_count += 1

            print(
                f"[{i}/{len(comments)}] "
                f"comment_id={comment_id} | score={score} | label={label} | "
                f"content={content[:40]}"
            )

        conn.commit()

        print("\n=== 分析完成 ===")
        print(f"帖子标题: {title}")
        print(f"帖子 post_id: {post_id}")
        print(f"评论总数: {len(comments)}")
        print(f"正面: {positive_count}")
        print(f"中性: {neutral_count}")
        print(f"负面: {negative_count}")

    except Exception as e:
        print(f"程序运行出错: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    analyze_first_post_comments()