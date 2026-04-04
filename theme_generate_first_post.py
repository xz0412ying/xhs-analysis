import json
import os
from collections import Counter

import pymysql
from openai import OpenAI


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
}


MODEL_NAME = os.getenv("LLM_MODEL", "gpt-4o-mini")
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def get_first_post(conn):
    sql = """
        SELECT post_id, title, content
        FROM posts
        ORDER BY post_id ASC
        LIMIT 1
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    if not row:
        return None
    return {"post_id": row[0], "title": row[1] or "", "content": row[2] or ""}


def get_post_comments(conn, post_id, limit=800):
    sql = """
        SELECT comment_id, comment_content, like_count
        FROM comments
        WHERE post_id = %s
          AND comment_content IS NOT NULL
          AND comment_content <> ''
        ORDER BY like_count DESC, comment_id ASC
        LIMIT %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (post_id, limit))
        rows = cursor.fetchall()

    comments = []
    for comment_id, text, like_count in rows:
        text = (text or "").strip()
        if not text:
            continue
        comments.append(
            {
                "comment_id": int(comment_id),
                "comment_content": text,
                "like_count": int(like_count or 0),
            }
        )
    return comments


def select_representative_comments(comments, keep_count=250):
    if len(comments) <= keep_count:
        return comments

    # 先取高赞评论，再补充非高赞样本，避免主题只由高赞观点决定
    high_like_part = comments[: keep_count // 2]
    tail = comments[keep_count // 2 :]
    step = max(1, len(tail) // (keep_count - len(high_like_part)))
    sampled_tail = tail[::step][: keep_count - len(high_like_part)]
    return high_like_part + sampled_tail


def build_prompt(post, comments):
    like_values = [c["like_count"] for c in comments]
    like_counter = Counter(like_values)
    quick_stats = {
        "comment_count": len(comments),
        "max_like": max(like_values) if like_values else 0,
        "like_distribution_top": like_counter.most_common(5),
    }

    system_prompt = """
你是小红书帖子主题分析助手。请严格按下列模板生成3个主题，并只输出JSON。

主题生成模板：
主题1：主帖核心议题
- 由标题+正文直接概括，不要主要依赖评论

主题2：评论区最主要的延伸争议点
- 从评论中高频/高赞观点总结

主题3：评论区第二主要延伸争议点
- 也是从评论中总结，且与主题2不同

约束：
1) 主题名简洁明确，建议6-16字；
2) 主题2和主题3必须能在评论中找到依据，不能重复同义；
3) 输出只允许是合法JSON，不要输出任何额外说明。

输出JSON格式：
{
  "theme1": "xxx",
  "theme2": "xxx",
  "theme3": "xxx"
}
""".strip()

    payload = {
        "post": post,
        "comment_stats": quick_stats,
        "comments_for_analysis": comments,
    }

    user_prompt = "请基于以下数据生成主题：\n" + json.dumps(payload, ensure_ascii=False)
    return system_prompt, user_prompt


def call_llm_generate_themes(post, comments):
    if not API_KEY:
        raise RuntimeError("缺少 OPENAI_API_KEY 环境变量。")

    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL
    client = OpenAI(timeout=120, **client_kwargs)

    system_prompt, user_prompt = build_prompt(post, comments)

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = resp.choices[0].message.content
    data = json.loads(content)

    theme1 = (data.get("theme1") or "").strip()
    theme2 = (data.get("theme2") or "").strip()
    theme3 = (data.get("theme3") or "").strip()

    if not (theme1 and theme2 and theme3):
        raise RuntimeError(f"模型返回缺失字段: {data}")

    return theme1, theme2, theme3


def update_post_themes(conn, post_id, theme1, theme2, theme3):
    sql = """
        UPDATE posts
        SET theme1 = %s,
            theme2 = %s,
            theme3 = %s
        WHERE post_id = %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (theme1, theme2, theme3, post_id))
    conn.commit()


def main():
    conn = None
    try:
        conn = get_connection()
        post = get_first_post(conn)
        if not post:
            print("posts 表没有数据，无法生成主题。")
            return

        comments = get_post_comments(conn, post["post_id"], limit=800)
        comments_for_llm = select_representative_comments(comments, keep_count=50)

        print(
            f"准备分析 post_id={post['post_id']}，"
            f"原始评论 {len(comments)} 条，送入模型 {len(comments_for_llm)} 条..."
        )

        theme1, theme2, theme3 = call_llm_generate_themes(post, comments_for_llm)
        update_post_themes(conn, post["post_id"], theme1, theme2, theme3)

        print("主题写回成功：")
        print("theme1:", theme1)
        print("theme2:", theme2)
        print("theme3:", theme3)

    except Exception as e:
        print("执行失败：", str(e))
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()

