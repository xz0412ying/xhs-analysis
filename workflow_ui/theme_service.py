import sys
import os
import json
import re
from collections import Counter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pymysql
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from openai import OpenAI

from theme.threetheme.theme_generate_deepseek_first_post import (
    get_connection as get_conn,
    get_post_comments as get_post_cmts,
    select_representative_comments,
    call_llm_generate_themes,
    assign_comment_themes,
    update_post_themes,
    update_comment_assigned_theme,
    is_expressive_comment,
    clean_text
)

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()

EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

def get_connection():
    return pymysql.connect(**DB_CONFIG)

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
    for row in rows:
        comments.append({
            "comment_id": int(row["comment_id"]),
            "comment_content": clean_text(row["comment_content"]),
            "like_count": int(row["like_count"] or 0),
        })
    return comments

def get_all_existing_themes(conn):
    sql = """
        SELECT id, theme, risk_id
        FROM theme_bertopic
        WHERE theme_source = 'existing'
          AND theme IS NOT NULL
          AND theme <> ''
        ORDER BY id ASC
    """
    with conn.cursor() as cursor:
        cursor.execute(sql)
        rows = cursor.fetchall()
    return [{"id": int(row["id"]), "theme": row["theme"], "risk_id": int(row["risk_id"]) if row["risk_id"] else None} for row in rows]

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

def match_existing_theme_for_post_id(post_id):
    """
    使用DeepSeek匹配现有主题的新流程：
    1. 获取帖子和评论
    2. 使用DeepSeek从现有主题列表中选择最匹配的主题
    3. 更新帖子的bertopic_theme字段
    4. 为每条评论分配主题
    """
    conn = get_connection()
    try:
        post = get_post_by_id(conn, post_id)
        if not post:
            raise RuntimeError(f"post_id={post_id} 不存在")

        comments = get_post_comments(conn, post_id, limit=800)
        if not comments:
            raise RuntimeError(f"post_id={post_id} 没有评论")

        existing_themes = get_all_existing_themes(conn)
        if not existing_themes:
            raise RuntimeError("没有可用的现有主题")

        theme_list = [t["theme"] for t in existing_themes]
        comments_for_llm = select_representative_comments(comments, keep_count=60)

        selected_theme = call_llm_match_theme(post, comments_for_llm, theme_list)

        update_post_bertopic_theme(conn, post_id, selected_theme)

        updates, theme_count = assign_comment_theme_single(post, comments, selected_theme)
        update_comment_assigned_theme(conn, updates)

        return {
            "matched_theme": selected_theme,
            "theme_count": dict(theme_count)
        }
    finally:
        conn.close()

def call_llm_match_theme(post, comments, theme_list):
    """
    使用DeepSeek从现有主题列表中选择最匹配的主题
    """
    if not API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量。")

    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL

    client = OpenAI(timeout=120, **client_kwargs)

    system_prompt = f"""你是小红书帖子主题匹配助手。请从以下现有主题列表中选择最匹配的主题，只输出JSON。

可用主题列表：
{chr(10).join([f'{i+1}. {t}' for i, t in enumerate(theme_list)])}

匹配规则：
1. 主题必须与帖子内容和评论主题高度相关
2. 如果没有主题匹配，返回列表中的第一个主题作为默认
3. 只输出合法JSON，不要输出任何额外文字

输出格式：
{{"matched_theme": "xxx"}}
""".strip()

    payload = {
        "post": {
            "title": post["title"],
            "content": post["content"],
        },
        "comments_for_analysis": [
            {
                "comment_id": c["comment_id"],
                "comment_content": c["comment_content"],
                "like_count": c["like_count"],
            }
            for c in comments[:30]
        ],
    }

    user_prompt = "请基于以下数据选择最匹配的主题：\n" + json.dumps(payload, ensure_ascii=False)

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        max_tokens=200,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = resp.choices[0].message.content
    data = json.loads(content)
    matched = clean_text(data.get("matched_theme", ""))

    if not matched or matched not in theme_list:
        matched = theme_list[0]

    return matched

def assign_comment_theme_single(post, comments, matched_theme):
    """
    为评论分配给定的主题（使用embedding相似度）
    """
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    updates = []
    theme_count = Counter()

    expressive_comments = []
    non_expressive_comments = []

    for comment in comments:
        comment_text = comment["comment_content"]
        if is_expressive_comment(comment_text):
            expressive_comments.append(comment)
        else:
            non_expressive_comments.append(comment)

    for comment in expressive_comments:
        assigned_theme = matched_theme
        updates.append((assigned_theme, comment["comment_id"], post["post_id"]))
        theme_count[assigned_theme] += 1

    if not non_expressive_comments:
        return updates, theme_count

    enhanced_comments = [
        build_comment_text_for_embedding(post, c["comment_content"])
        for c in non_expressive_comments
    ]

    comment_embeddings = model.encode(
        enhanced_comments,
        normalize_embeddings=True
    )

    theme_texts = [f"主题：{matched_theme}"]
    theme_embeddings = model.encode(theme_texts, normalize_embeddings=True)

    sims_matrix = cosine_similarity(comment_embeddings, theme_embeddings)

    low_similarity_threshold = 0.25

    for idx, comment in enumerate(non_expressive_comments):
        best_score = float(sims_matrix[idx][0])

        if best_score < low_similarity_threshold:
            assigned_theme = matched_theme
        else:
            assigned_theme = matched_theme

        updates.append((assigned_theme, comment["comment_id"], post["post_id"]))
        theme_count[assigned_theme] += 1

    return updates, theme_count

def build_comment_text_for_embedding(post, comment_text: str) -> str:
    title = clean_text(post.get("title", ""))
    content = clean_text(post.get("content", ""))[:120]
    comment_text = clean_text(comment_text)
    return f"主帖标题：{title}。主帖内容：{content}。评论：{comment_text}"

def update_post_bertopic_theme(conn, post_id, theme):
    sql = """
        UPDATE posts
        SET bertopic_theme = %s
        WHERE post_id = %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (theme, post_id))
    conn.commit()

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