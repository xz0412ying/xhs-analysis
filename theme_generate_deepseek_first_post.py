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


# DeepSeek API 配置
MODEL_NAME = os.getenv("LLM_MODEL", "deepseek-chat")  # DeepSeek 模型名称
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()  # DeepSeek API Key
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip()  # DeepSeek API 地址


# ---------------------------------------------------------------------------
# 可配置：要分析 posts 表里按 post_id 排序后的「第几条」帖子
# 1 = 第一个帖子，2 = 第二个帖子，以此类推
# ---------------------------------------------------------------------------
POST_RANK = 1


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def get_post_by_rank(conn, rank):
    """
    按 post_id 升序取「第 rank 条」帖子（rank 从 1 开始）。

    例如 rank=1 为第一个帖子，rank=2 为第二个帖子。
    SQL 使用 LIMIT 1 OFFSET (rank-1) 实现跳过前面的行。

    修改主题分析对象：只需改文件顶部的 POST_RANK，不要改本函数内部。
    """
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
        raise RuntimeError("缺少 DEEPSEEK_API_KEY 环境变量。")

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

def update_comment_assigned_theme(conn, post_id, comments, theme1, theme2, theme3):
    """
    为每条评论分配主题，写入 comments.assigned_theme。
    逻辑：
    1. 纯表态评论直接归为 theme1
    2. 其他评论使用语义相似度计算，归到最相似的主题
    """
    # 纯表态评论的关键词列表
    EXPRESSIVE_COMMENTS_KEYWORDS = {
        # 赞同/附和
        "支持", "赞同", "同意", "确实", "是的", "对的", "没错", "正确", "赞成", "认同",
        "是的", "对", "没错", "确实如此", "完全同意", "非常赞同", "我也是", "我也觉得", "我也这么认为",
        # 情绪表达
        "哈哈哈", "呵呵", "嘻嘻", "呵呵呵", "哈哈", "笑", "笑死", "好玩", "有趣", "不错",
        "厉害", "棒", "赞", "牛", "牛掰", "厉害", "优秀", "完美", "好", "太好了",
        # 简单回应
        "嗯", "哦", "啊", "呀", "哟", "哦", "嗯", "好的", "知道了", "了解",
        # 疑问/感叹
        "真的吗", "真的", "假的", "哇", "哇塞", "天啊", "天哪", "哦天", "我的天", "天哪",
    }
    
    # 纯表态评论的模式
    EXPRESSIVE_PATTERNS = [
        r"^\s*[支持赞同同意确实是的对的没错正确赞成认同]+\s*$",  # 纯赞同
        r"^\s*[哈哈呵呵嘻嘻]+\s*$",  # 纯笑声
        r"^\s*[嗯哦啊呀哟]+\s*$",  # 纯语气词
        r"^\s*[厉害棒赞牛优秀]+\s*$",  # 纯赞美
        r"^\s*[好不错]+\s*$",  # 纯评价
    ]
    
    def is_expressive_comment(text):
        """判断是否为纯表态评论。"""
        text = text.strip()
        if not text:
            return True
        
        # 检查是否匹配纯表态模式
        import re
        for pattern in EXPRESSIVE_PATTERNS:
            if re.match(pattern, text):
                return True
        
        # 检查是否只包含纯表态关键词
        words = text.split()
        if not words:
            return True
        
        # 检查是否所有词都是纯表态关键词
        for word in words:
            if word not in EXPRESSIVE_COMMENTS_KEYWORDS:
                return False
        
        return True
    
    def calculate_semantic_similarity(text1, text2):
        """计算两个文本的语义相似度（使用词频向量余弦相似度）。"""
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        
        # 创建TF-IDF向量化器
        vectorizer = TfidfVectorizer()
        
        # 将两个文本转换为向量
        try:
            vectors = vectorizer.fit_transform([text1, text2])
            similarity = cosine_similarity(vectors[0:1], vectors[1:2])[0][0]
            return similarity
        except:
            # 如果向量化失败（如文本太短），返回0
            return 0.0
    
    def assign_theme_by_semantic_similarity(comment_text, theme1, theme2, theme3):
        """使用语义相似度为评论分配主题。"""
        # 计算评论与每个主题的语义相似度
        similarity1 = calculate_semantic_similarity(comment_text, theme1)
        similarity2 = calculate_semantic_similarity(comment_text, theme2)
        similarity3 = calculate_semantic_similarity(comment_text, theme3)
        
        # 选择相似度最高的主题
        similarities = [
            (similarity1, theme1),
            (similarity2, theme2), 
            (similarity3, theme3)
        ]
        similarities.sort(reverse=True)
        
        # 如果最高相似度低于阈值，归为 theme1
        if similarities[0][0] < 0.1:
            return theme1
        
        return similarities[0][1]
    
    # 为每条评论分配主题
    updates = []
    for comment in comments:
        comment_text = comment["comment_content"]
        
        # 纯表态评论直接归为 theme1
        if is_expressive_comment(comment_text):
            assigned_theme = theme1
        else:
            # 其他评论使用语义相似度分配主题
            assigned_theme = assign_theme_by_semantic_similarity(comment_text, theme1, theme2, theme3)
        
        updates.append((assigned_theme, comment["comment_id"], post_id))
    
    # 更新评论主题
    if updates:
        sql = """
            UPDATE comments
            SET assigned_theme = %s
            WHERE comment_id = %s
              AND post_id = %s
        """
        with conn.cursor() as cursor:
            cursor.executemany(sql, updates)
        conn.commit()
    
    # 统计各主题的评论数量
    from collections import Counter
    theme_count = Counter()
    for update in updates:
        theme_count[update[0]] += 1
    
    return theme_count


def main():
    conn = None
    try:
        conn = get_connection()
        # 这里使用 POST_RANK：要改成分析「第一个帖子」把文件顶部 POST_RANK 改为 1
        post = get_post_by_rank(conn, POST_RANK)
        if not post:
            print(f"posts 表中没有第 {POST_RANK} 条帖子（数据不足或 OFFSET 越界）。")
            return

        comments = get_post_comments(conn, post["post_id"], limit=800)
        comments_for_llm = select_representative_comments(comments, keep_count=50)

        print(
            f"准备分析 post_id={post['post_id']}，"
            f"原始评论 {len(comments)} 条，送入模型 {len(comments_for_llm)} 条..."
        )

        theme1, theme2, theme3 = call_llm_generate_themes(post, comments_for_llm)
        update_post_themes(conn, post["post_id"], theme1, theme2, theme3)
        
        # 为评论分配主题
        theme_count = update_comment_assigned_theme(conn, post["post_id"], comments, theme1, theme2, theme3)

        print("主题写回成功：")
        print("theme1:", theme1)
        print("theme2:", theme2)
        print("theme3:", theme3)
        print("各主题评论量：", dict(theme_count))

    except Exception as e:
        print("执行失败：", str(e))
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
