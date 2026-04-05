import json
import os
import re
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

# DeepSeek 配置
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()

# 主题生成时抽样评论数
THEME_COMMENT_SAMPLE_SIZE = 60

# 评论分类时每批发送条数
CLASSIFY_BATCH_SIZE = 20

# 纯表态评论词表
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

START_POST_RANK = 3
END_POST_RANK = None   # None 表示一直跑到最后一条


def get_post_count(conn):
    sql = "SELECT COUNT(*) FROM posts"
    with conn.cursor() as cursor:
        cursor.execute(sql)
        row = cursor.fetchone()
    return int(row[0] or 0)

def get_post_by_rank(conn, rank):
    if rank < 1:
        raise ValueError("rank 必须 >= 1")

    offset = rank - 1
    sql = """
        SELECT post_id, title, content
        FROM posts
        ORDER BY post_id ASC
        LIMIT 1 OFFSET %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (offset,))
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "post_id": row[0],
        "title": row[1] or "",
        "content": row[2] or "",
    }


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


def clean_text(text: str) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def is_expressive_comment(text: str) -> bool:
    text = clean_text(text)
    if not text:
        return True

    for pattern in EXPRESSIVE_PATTERNS:
        if re.match(pattern, text):
            return True

    # 简单分句切词，适配中文短评论
    pieces = re.split(r"[，。！？、；\s]+", text)
    pieces = [p for p in pieces if p]

    if not pieces:
        return True

    if len(pieces) <= 3 and all(p in EXPRESSIVE_WORDS for p in pieces):
        return True

    return False


def select_representative_comments(comments, keep_count=60):
    if len(comments) <= keep_count:
        return comments

    # 高赞 + 中部 + 尾部均匀抽样
    top_count = keep_count // 3
    middle_count = keep_count // 3
    tail_count = keep_count - top_count - middle_count

    top_part = comments[:top_count]

    middle_start = len(comments) // 3
    middle_end = middle_start + middle_count * 2
    middle_pool = comments[middle_start:middle_end]
    middle_part = middle_pool[:middle_count]

    tail_pool = comments[middle_end:]
    step = max(1, len(tail_pool) // max(tail_count, 1))
    tail_part = tail_pool[::step][:tail_count]

    merged = top_part + middle_part + tail_part

    # 按 comment_id 去重
    seen = set()
    result = []
    for c in merged:
        cid = c["comment_id"]
        if cid in seen:
            continue
        seen.add(cid)
        result.append(c)

    return result[:keep_count]


def get_client():
    if not API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量。")

    client_kwargs = {"api_key": API_KEY}
    if BASE_URL:
        client_kwargs["base_url"] = BASE_URL

    return OpenAI(timeout=120, **client_kwargs)


def build_theme_prompt(post, comments):
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
theme1：主帖核心议题
- 必须由标题+正文直接概括
- 不要主要依赖评论

theme2：评论区最主要的延伸争议点
- 必须从评论中高频/高赞观点总结
- 可以与 theme1 接近，但必须体现“评论区主要回应方向”

theme3：评论区第二主要延伸争议点
- 也必须从评论中总结
- 如果评论区没有明显第二延伸方向，可写“评论区无其他延伸主题”

约束：
1. 主题名简洁明确，建议6-18字；
2. 只输出合法 JSON；
3. 不要输出解释说明。

输出格式：
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

    user_prompt = "请基于以下数据生成3个主题：\n" + json.dumps(payload, ensure_ascii=False)
    return system_prompt, user_prompt


def call_llm_generate_themes(post, comments):
    client = get_client()
    system_prompt, user_prompt = build_theme_prompt(post, comments)

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


def build_classify_prompt(post, themes, comments_batch):
    theme1, theme2, theme3 = themes

    system_prompt = """
你是小红书评论主题分类助手。你的任务是把每条评论分配到给定的三个主题之一。

分类规则：
1. theme1 = 主帖核心议题
2. theme2 = 评论区最主要延伸争议点
3. theme3 = 评论区第二主要延伸争议点
4. 如果评论只是表态、附和、感叹，但没有独立展开，也归到 theme1
5. 必须三选一，不能输出其他标签
6. 只输出合法 JSON，不要输出任何解释

输出格式：
{
  "results": [
    {"comment_id": 1, "assigned_theme": "theme1"},
    {"comment_id": 2, "assigned_theme": "theme2"}
  ]
}
""".strip()

    payload = {
        "post": {
            "title": post["title"],
            "content": post["content"]
        },
        "themes": {
            "theme1": theme1,
            "theme2": theme2,
            "theme3": theme3,
        },
        "comments": [
            {
                "comment_id": c["comment_id"],
                "comment_content": c["comment_content"],
                "like_count": c["like_count"],
            }
            for c in comments_batch
        ],
    }

    user_prompt = "请对以下评论进行主题分类：\n" + json.dumps(payload, ensure_ascii=False)
    return system_prompt, user_prompt


def call_llm_classify_comments(post, themes, comments_batch):
    client = get_client()
    system_prompt, user_prompt = build_classify_prompt(post, themes, comments_batch)

    try:
        resp = client.chat.completions.create(
            model=MODEL_NAME,
            temperature=0,
            max_tokens=1200,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as e:
        batch_ids = [c["comment_id"] for c in comments_batch]
        raise RuntimeError(f"评论分类接口调用失败，comment_ids={batch_ids}，错误={str(e)}")

    content = resp.choices[0].message.content

    try:
        data = json.loads(content)
    except Exception:
        batch_ids = [c["comment_id"] for c in comments_batch]
        raise RuntimeError(f"评论分类返回不是合法JSON，comment_ids={batch_ids}，原始返回={content}")

    results = data.get("results", [])
    if not isinstance(results, list):
        raise RuntimeError(f"评论分类返回格式异常: {data}")

    mapping = {}
    valid_labels = {"theme1", "theme2", "theme3"}

    for item in results:
        comment_id = item.get("comment_id")
        assigned_theme = item.get("assigned_theme")

        if comment_id is None or assigned_theme not in valid_labels:
            continue

        mapping[int(comment_id)] = assigned_theme

    return mapping


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


def chunk_list(items, batch_size):
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def assign_comment_themes_with_llm(post, comments, theme1, theme2, theme3):
    """
    逻辑：
    1. 纯表态评论直接归 theme1
    2. 非纯表态评论分批交给 DeepSeek 分类
    """
    theme_count = Counter()
    updates = []

    expressive_comments = []
    normal_comments = []

    for c in comments:
        if is_expressive_comment(c["comment_content"]):
            expressive_comments.append(c)
        else:
            normal_comments.append(c)

    # 纯表态评论直接归 theme1
    for c in expressive_comments:
        updates.append((theme1, c["comment_id"], post["post_id"]))
        theme_count[theme1] += 1

    themes = (theme1, theme2, theme3)

    total_batches = (len(normal_comments) + CLASSIFY_BATCH_SIZE - 1) // CLASSIFY_BATCH_SIZE
    print(f"纯表态评论 {len(expressive_comments)} 条，需模型分类 {len(normal_comments)} 条，共 {total_batches} 批。")

    # 其余评论交给 LLM 批量分类
    for batch_idx, batch in enumerate(chunk_list(normal_comments, CLASSIFY_BATCH_SIZE), start=1):
        print(f"正在处理第 {batch_idx}/{total_batches} 批，本批 {len(batch)} 条评论...")

        label_mapping = call_llm_classify_comments(post, themes, batch)

        for c in batch:
            label = label_mapping.get(c["comment_id"], "theme1")

            if label == "theme1":
                assigned_theme = theme1
            elif label == "theme2":
                assigned_theme = theme2
            elif label == "theme3":
                assigned_theme = theme3
            else:
                assigned_theme = theme1

            updates.append((assigned_theme, c["comment_id"], post["post_id"]))
            theme_count[assigned_theme] += 1

        print(f"第 {batch_idx}/{total_batches} 批完成。")

    return updates, theme_count, len(expressive_comments), len(normal_comments)


def main():
    conn = None
    try:
        conn = get_connection()
        post = get_post_by_rank(conn, POST_RANK)
        if not post:
            print("posts 表没有数据，无法生成主题。")
            return

        comments = get_post_comments(conn, post["post_id"], limit=800)
        if not comments:
            print(f"post_id={post['post_id']} 没有评论，无法分析。")
            return

        comments_for_llm = select_representative_comments(
            comments,
            keep_count=THEME_COMMENT_SAMPLE_SIZE
        )

        print(
            f"准备分析 post_id={post['post_id']}，"
            f"原始评论 {len(comments)} 条，送入主题生成模型 {len(comments_for_llm)} 条..."
        )

        theme1, theme2, theme3 = call_llm_generate_themes(post, comments_for_llm)
        update_post_themes(conn, post["post_id"], theme1, theme2, theme3)

        print("主题写回成功：")
        print("theme1:", theme1)
        print("theme2:", theme2)
        print("theme3:", theme3)

        print("开始为评论分配主题...")
        updates, theme_count, expressive_count, normal_count = assign_comment_themes_with_llm(
            post, comments, theme1, theme2, theme3
        )
        update_comment_assigned_theme(conn, updates)

        print("评论主题写回成功：")
        print("纯表态评论数：", expressive_count)
        print("需模型分类评论数：", normal_count)
        print("各主题评论量：", dict(theme_count))

    except Exception as e:
        print("执行失败：", str(e))
        print("如缺少依赖，请安装：")
        print("python -m pip install openai pymysql jieba")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()