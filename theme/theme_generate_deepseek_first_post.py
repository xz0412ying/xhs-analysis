import json
import os
import re
from collections import Counter

import jieba
import pymysql
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# DeepSeek API 配置
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()

# 只分析 posts 表里按 post_id 排序后的第几条帖子
POST_RANK = 3

# 送入大模型生成主题时，最多采样多少条评论
COMMENT_SAMPLE_SIZE = 90

# 评论主题分配时使用的句向量模型
EMBEDDING_MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

STOP_WORDS = {
    "的", "了", "是", "我", "你", "他", "她", "它", "这", "那", "也", "都", "就", "很",
    "吗", "啊", "吧", "呢", "呀", "哦", "有", "在", "和", "与", "及", "被", "还",
    "一个", "这个", "那个", "不是", "就是", "然后", "因为", "所以", "如果", "但是",
    "而且", "还是", "已经", "没有", "可以", "觉得", "感觉"
}

EXPRESSIVE_WORDS = {
    "支持", "赞同", "同意", "确实", "是的", "对的", "没错", "正确", "赞成", "认同",
    "对", "完全同意", "非常赞同", "我也是", "我也觉得", "我也这么认为",
    "哈哈", "哈哈哈", "呵呵", "嘻嘻", "笑死", "有趣", "不错",
    "厉害", "棒", "赞", "牛", "优秀", "完美", "太好了", "好",
    "嗯", "哦", "啊", "呀", "哟", "好的", "知道了", "了解",
    "真的", "真的吗", "假的", "哇", "哇塞", "天啊", "天哪", "我的天"
}

EXPRESSIVE_PATTERNS = [
    r"^\s*(支持|赞同|同意|确实|是的|对的|没错|正确|赞成|认同|对)+\s*$",
    r"^\s*(哈哈|哈哈哈|呵呵|嘻嘻|笑死)+\s*$",
    r"^\s*(嗯|哦|啊|呀|哟)+\s*$",
    r"^\s*(厉害|棒|赞|牛|优秀|完美)+\s*$",
    r"^\s*(好|不错|太好了)+\s*$",
]


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def clean_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def get_post_by_rank(conn, rank: int):
    if rank < 1:
        raise ValueError("POST_RANK 必须 >= 1")

    sql = """
        SELECT post_id, title, content
        FROM posts
        ORDER BY post_id ASC
        LIMIT 1 OFFSET %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (rank - 1,))
        return cursor.fetchone()


def get_post_comments(conn, post_id: int, limit: int = 800):
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


def tokenize_zh(text: str):
    words = jieba.lcut(clean_text(text))
    tokens = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if len(w) <= 1:
            continue
        if w in STOP_WORDS:
            continue
        tokens.append(w)
    return tokens


def is_expressive_comment(text: str) -> bool:
    text = clean_text(text)
    if not text:
        return True

    for pattern in EXPRESSIVE_PATTERNS:
        if re.match(pattern, text):
            return True

    tokens = tokenize_zh(text)
    if not tokens:
        return True

    if len(tokens) <= 3 and all(token in EXPRESSIVE_WORDS for token in tokens):
        return True

    return False


def select_representative_comments(comments, keep_count=60):
    if len(comments) <= keep_count:
        return comments

    high_like_count = keep_count // 3
    middle_count = keep_count // 3
    low_count = keep_count - high_like_count - middle_count

    sorted_comments = comments[:]
    top_part = sorted_comments[:high_like_count]

    remain = sorted_comments[high_like_count:]
    mid_start = len(remain) // 3
    mid_end = mid_start + max(middle_count * 2, 1)
    middle_pool = remain[mid_start:mid_end]
    low_pool = remain[mid_end:]

    middle_part = middle_pool[:middle_count]
    if len(middle_part) < middle_count:
        middle_part += remain[: middle_count - len(middle_part)]

    step = max(1, len(low_pool) // max(low_count, 1))
    low_part = low_pool[::step][:low_count]

    merged = top_part + middle_part + low_part

    seen = set()
    result = []
    for c in merged:
        cid = c["comment_id"]
        if cid in seen:
            continue
        seen.add(cid)
        result.append(c)

    return result[:keep_count]


def build_prompt(post, comments):
    like_values = [c["like_count"] for c in comments]
    like_counter = Counter(like_values)

    quick_stats = {
        "comment_count": len(comments),
        "max_like": max(like_values) if like_values else 0,
        "like_distribution_top": like_counter.most_common(5),
    }

    system_prompt = """
你是小红书帖子主题分析助手。请严格按下列要求生成3个主题，并只输出JSON。

主题生成模板：
主题1：主帖核心议题
- 必须根据帖子标题和正文直接概括
- 不要主要依赖评论

主题2：评论区最主要的延伸争议点
- 必须从评论区高频/高赞观点中总结
- 需要与主题1区分开

主题3：评论区第二主要的延伸争议点
- 也必须从评论区总结
- 不能与主题2重复或同义

约束：
1. 主题名简洁明确，建议6-16字；
2. theme2 和 theme3 必须来自评论，而不是重复主帖；
3. 如果评论区只有一个明显延伸方向，theme3 可以写成“评论区无其他延伸主题”；
4. 只输出合法JSON，不要输出任何额外文字。

输出格式：
{
  "theme1": "xxx",
  "theme2": "xxx",
  "theme3": "xxx"
}
""".strip()

    payload = {
        "post": {
            "title": post["title"],
            "content": post["content"],
        },
        "comment_stats": quick_stats,
        "comments_for_analysis": [
            {
                "comment_id": c["comment_id"],
                "comment_content": c["comment_content"],
                "like_count": c["like_count"],
            }
            for c in comments
        ],
    }

    user_prompt = "请基于以下数据生成主题：\n" + json.dumps(payload, ensure_ascii=False)
    return system_prompt, user_prompt


def call_llm_generate_themes(post, comments):
    if not API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量。")

    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL

    client = OpenAI(timeout=120, **client_kwargs)
    system_prompt, user_prompt = build_prompt(post, comments)

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        max_tokens=300,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    content = resp.choices[0].message.content
    data = json.loads(content)

    theme1 = clean_text(data.get("theme1", ""))
    theme2 = clean_text(data.get("theme2", ""))
    theme3 = clean_text(data.get("theme3", ""))

    if not (theme1 and theme2 and theme3):
        raise RuntimeError(f"模型返回缺失字段: {data}")

    if theme2 == theme3:
        theme3 = "评论区无其他延伸主题"

    return theme1, theme2, theme3


def build_comment_text_for_embedding(post, comment_text: str) -> str:
    title = clean_text(post.get("title", ""))
    content = clean_text(post.get("content", ""))[:120]
    comment_text = clean_text(comment_text)
    return f"主帖标题：{title}。主帖内容：{content}。评论：{comment_text}"


def assign_comment_themes(post, comments, theme1, theme2, theme3, debug=False):
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    extension_theme_texts = [
        f"评论区主要延伸争议点：{theme2}",
        f"评论区第二延伸争议点：{theme3}",
    ]
    extension_theme_embeddings = model.encode(
        extension_theme_texts,
        normalize_embeddings=True
    )

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
        assigned_theme = theme1
        updates.append((assigned_theme, comment["comment_id"], post["post_id"]))
        theme_count[assigned_theme] += 1

    if non_expressive_comments:
        enhanced_comments = [
            build_comment_text_for_embedding(post, c["comment_content"])
            for c in non_expressive_comments
        ]

        comment_embeddings = model.encode(
            enhanced_comments,
            normalize_embeddings=True
        )

        sims_matrix = cosine_similarity(comment_embeddings, extension_theme_embeddings)

        low_similarity_threshold = 0.20
        margin_threshold = 0.01
        extension_themes = [theme2, theme3]

        for idx, comment in enumerate(non_expressive_comments):
            sims = sims_matrix[idx]
            best_idx = int(sims.argmax())
            best_score = float(sims[best_idx])
            second_score = float(sims[1 - best_idx])
            score_gap = best_score - second_score

            if best_score < low_similarity_threshold or score_gap < margin_threshold:
                assigned_theme = theme1
            else:
                assigned_theme = extension_themes[best_idx]

            updates.append((assigned_theme, comment["comment_id"], post["post_id"]))
            theme_count[assigned_theme] += 1

            if debug and idx < 20:
                print("评论：", comment["comment_content"])
                print("theme2_score:", round(float(sims[0]), 4), "->", theme2)
                print("theme3_score:", round(float(sims[1]), 4), "->", theme3)
                print("best_score:", round(best_score, 4), "gap:", round(score_gap, 4))
                print("assigned:", assigned_theme)
                print("-" * 60)

    return updates, theme_count


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


def update_comment_assigned_theme(conn, updates):
    if not updates:
        return

    sql = """
        UPDATE comments
        SET assigned_theme = %s
        WHERE comment_id = %s
          AND post_id = %s
    """
    with conn.cursor() as cursor:
        cursor.executemany(sql, updates)
    conn.commit()


def main():
    conn = None
    try:
        conn = get_connection()

        print(f"{'=' * 60}")
        print(f"开始处理第 {POST_RANK} 条帖子")
        print(f"{'=' * 60}")

        post = get_post_by_rank(conn, POST_RANK)
        if not post:
            print(f"posts 表中没有第 {POST_RANK} 条帖子。")
            return

        print(f"post_id: {post['post_id']}")
        print(f"title: {post['title']}")

        comments = get_post_comments(conn, post["post_id"], limit=800)
        if not comments:
            print(f"post_id={post['post_id']} 没有评论，无法分析。")
            return

        comments_for_llm = select_representative_comments(
            comments,
            keep_count=COMMENT_SAMPLE_SIZE
        )

        print(
            f"准备分析 post_id={post['post_id']}，"
            f"原始评论 {len(comments)} 条，送入大模型 {len(comments_for_llm)} 条..."
        )

        theme1, theme2, theme3 = call_llm_generate_themes(post, comments_for_llm)
        update_post_themes(conn, post["post_id"], theme1, theme2, theme3)

        print("已生成主题：")
        print("theme1:", theme1)
        print("theme2:", theme2)
        print("theme3:", theme3)

        print("开始为评论分配主题...")
        updates, theme_count = assign_comment_themes(
            post, comments, theme1, theme2, theme3, debug=False
        )
        update_comment_assigned_theme(conn, updates)

        print("评论主题写回成功：")
        print("各主题评论量：", dict(theme_count))

    except Exception as e:
        print("执行失败：", str(e))
        print("如缺少依赖，请安装：")
        print("python -m pip install openai pymysql sentence-transformers scikit-learn jieba")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()