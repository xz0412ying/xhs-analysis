"""
LDA 主题分析脚本（免费、不调用大模型 API）。

流程概要：
1. 从 posts 表按 post_id 升序取出「第 N 条」帖子（见下方 POST_RANK）。
2. theme1：由该帖 title + content 抽关键词生成（主帖核心议题）。
3. theme2、theme3：对该帖评论跑 LDA，聚类出 2 个延伸主题。
4. 回写 posts.theme1~theme3，并更新 comments.assigned_theme。

修改「分析第几个帖子」：改文件顶部 POST_RANK 即可（1=第一条，2=第二条）。
"""
import re
from collections import Counter

import jieba
import pymysql
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.decomposition import LatentDirichletAllocation

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



# ---------------------------------------------------------------------------
# 可配置：要分析 posts 表里按 post_id 排序后的「第几条」帖子
# 1 = 第一个帖子，2 = 第二个帖子，以此类推
# ---------------------------------------------------------------------------
POST_RANK = 3


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
}


STOP_WORDS = {
    "的",
    "了",
    "是",
    "我",
    "你",
    "他",
    "她",
    "它",
    "这",
    "那",
    "也",
    "都",
    "就",
    "很",
    "吗",
    "啊",
    "吧",
    "呢",
    "呀",
    "哦",
    "有",
    "在",
    "和",
    "与",
    "及",
    "被",
    "还",
    "一个",
    "这个",
    "那个",
    "不是",
    "就是",
    "什么",
    "自己",
    "还是",
    "可以",
    "如果",
    "因为",
    "所以",
}


def get_connection():
    """创建 MySQL 连接，配置与 crawler.py 中 DB_CONFIG 保持一致。"""
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


def get_comments_by_post(conn, post_id):
    """拉取某帖全部非空评论；先按点赞降序，便于高赞观点参与聚类。"""
    sql = """
        SELECT comment_id, comment_content, like_count
        FROM comments
        WHERE post_id = %s
          AND comment_content IS NOT NULL
          AND comment_content <> ''
        ORDER BY like_count DESC, comment_id ASC
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (post_id,))
        rows = cursor.fetchall()

    results = []
    for row in rows:
        results.append(
            {
                "comment_id": int(row[0]),
                "comment_content": (row[1] or "").strip(),
                "like_count": int(row[2] or 0),
            }
        )
    return results


def clean_text(text):
    """去掉首尾空白，合并连续空白，便于分词与向量化。"""
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text

def is_expressive_comment(text):
    """判断是否为纯表态评论。"""
    text = clean_text(text)
    if not text:
        return True
    
    # 检查是否匹配纯表态模式
    for pattern in EXPRESSIVE_PATTERNS:
        if re.match(pattern, text):
            return True
    
    # 检查是否只包含纯表态关键词
    words = jieba_tokenizer(text)
    if not words:
        return True
    
    # 检查是否所有词都是纯表态关键词
    for word in words:
        if word not in EXPRESSIVE_COMMENTS_KEYWORDS:
            return False
    
    return True


def jieba_tokenizer(text):
    """jieba 分词 + 去停用词 + 过滤单字，供 CountVectorizer 使用。"""
    words = jieba.lcut(text)
    tokens = []
    for w in words:
        w = w.strip()
        if len(w) <= 1:
            continue
        if w in STOP_WORDS:
            continue
        tokens.append(w)
    return tokens

def build_post_core_theme(post, max_words=4):
    """
    主题1必须来自主帖标题+正文。
    优先用标题关键词；标题过短时补充正文高频词。
    """
    title = clean_text(post.get("title", ""))
    content = clean_text(post.get("content", ""))
    source_text = f"{title} {content}".strip()

    if not source_text:
        return "主帖核心议题"

    title_tokens = jieba_tokenizer(title)
    content_tokens = jieba_tokenizer(content)

    merged = title_tokens + content_tokens
    if not merged:
        return source_text[:18]

    freq = Counter(merged)
    core_words = [w for w, _ in freq.most_common(max_words)]
    if not core_words:
        return source_text[:18]

    return "、".join(core_words[:max_words])

def fallback_themes_from_post(post):
    """
    当 LDA 聚类凑不齐两个评论延伸主题时，用固定文案占位。
    使用「评论区无其他延伸主题」表示：未再分出可与主帖并列的第二条/第三条延伸议题。
    """
    title = clean_text(post.get("title", ""))
    content = clean_text(post.get("content", ""))
    base = (title + " " + content).strip()
    base = base[:18] if base else "主帖核心议题"
    placeholder = "评论区无其他延伸主题"
    return [
        base,
        placeholder,
        placeholder,
    ]

def run_lda(comments):
    """
    对评论文本跑 LDA，固定聚成 2 个主题（对应 theme2、theme3 的来源）。
    返回：每条评论的 topic 编号、选中的两个 topic_id、两个主题名（关键词拼接）。
    """
    docs = [clean_text(x["comment_content"]) for x in comments if clean_text(x["comment_content"])]
    if len(docs) < 10:
        raise RuntimeError("评论数量过少，建议至少 10 条再跑 LDA。")

    # 构建词袋模型
    vectorizer = CountVectorizer(tokenizer=jieba_tokenizer, token_pattern=None, min_df=2)
    X = vectorizer.fit_transform(docs)
    feature_names = vectorizer.get_feature_names_out()

    # 训练 LDA 模型
    n_topics = 2
    lda_model = LatentDirichletAllocation(n_components=n_topics, random_state=42)
    lda_model.fit(X)

    # 获取主题分布
    topic_distributions = lda_model.transform(X)
    topics = topic_distributions.argmax(axis=1)

    # 提取每个主题的关键词
    topic_names = []
    n_top_words = 4
    for topic_idx, topic in enumerate(lda_model.components_):
        top_words = [feature_names[i] for i in topic.argsort()[:-n_top_words-1:-1]]
        topic_name = "、".join(top_words)
        topic_names.append(topic_name)

    return topics, list(range(n_topics)), topic_names

def update_post_themes(conn, post_id, themes):
    """把 theme1~theme3 写回 posts 表对应行。"""
    sql = """
        UPDATE posts
        SET theme1 = %s,
            theme2 = %s,
            theme3 = %s
        WHERE post_id = %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (themes[0], themes[1], themes[2], post_id))
    conn.commit()

def update_comment_assigned_theme(conn, post_id, comments, topics, selected_topic_ids, themes):
    """
    将 LDA 的 topic 编号映射到 posts 里已写入的 theme 文案，写入 comments.assigned_theme。
    themes[0] = theme1（主帖核心），不参与聚类 id 映射；
    themes[1]、themes[2] 分别对应聚类得到的两个 topic。
    未映射到的 topic：回落到 theme1。
    """
    # LDA 的 topic_id -> 数据库里存的 theme 文本（theme2 / theme3）
    topic_to_theme = {}
    for idx, tid in enumerate(selected_topic_ids):
        # themes[0] 是主帖核心主题，评论聚类主题从 themes[1] 开始映射
        topic_to_theme[tid] = themes[idx + 1]

    # 不在聚类核心主题里的评论，按规则回落到主题1（主帖核心）
    updates = []
    for c, topic_id in zip(comments, topics):
        assigned = topic_to_theme.get(topic_id, themes[0])
        updates.append((assigned, c["comment_id"], post_id))

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
        # 这里使用 POST_RANK：要改成分析「第一个帖子」把文件顶部 POST_RANK 改为 1
        post = get_post_by_rank(conn, POST_RANK)
        if not post:
            print(f"posts 表中没有第 {POST_RANK} 条帖子（数据不足或 OFFSET 越界）。")
            return

        comments = get_comments_by_post(conn, post["post_id"])
        if not comments:
            print(f"post_id={post['post_id']} 没有评论，无法进行评论主题分析。")
            return

        print(f"当前 POST_RANK={POST_RANK}，开始分析 post_id={post['post_id']}，评论数={len(comments)}")

        # 分离纯表态评论和非纯表态评论
        expressive_comments = []
        non_expressive_comments = []
        for comment in comments:
            if is_expressive_comment(comment["comment_content"]):
                expressive_comments.append(comment)
            else:
                non_expressive_comments.append(comment)

        print(f"纯表态评论数：{len(expressive_comments)}")
        print(f"非纯表态评论数：{len(non_expressive_comments)}")

        # 生成主题
        theme1 = build_post_core_theme(post)
        theme2 = "评论区无其他延伸主题"
        theme3 = "评论区无其他延伸主题"
        topics = []
        selected_topic_ids = []

        # 对非纯表态评论运行 LDA
        if len(non_expressive_comments) >= 10:
            topics, selected_topic_ids, topic_names = run_lda(non_expressive_comments)
            # theme2/theme3 优先来自评论聚类；若只分出 0/1 个主题，用「评论区无其他延伸主题」补齐
            comment_fallback = fallback_themes_from_post(post)[1:]
            topic_names = (topic_names + comment_fallback)[:2]
            theme2 = topic_names[0]
            if len(topic_names) > 1:
                theme3 = topic_names[1]
        elif len(non_expressive_comments) > 0:
            print("非纯表态评论数量过少，无法运行 LDA。")
        else:
            print("没有非纯表态评论，无法运行 LDA。")

        themes = [theme1, theme2, theme3]
        update_post_themes(conn, post["post_id"], themes)

        # 为评论分配主题
        updates = []
        # 为非纯表态评论分配 LDA 聚类结果
        for c, topic_id in zip(non_expressive_comments, topics):
            if topic_id in selected_topic_ids:
                idx = selected_topic_ids.index(topic_id)
                if idx == 0:
                    assigned = theme2
                elif idx == 1:
                    assigned = theme3
                else:
                    assigned = theme1
            else:
                assigned = theme1
            updates.append((assigned, c["comment_id"], post["post_id"]))
        # 为纯表态评论直接分配 theme1
        for c in expressive_comments:
            updates.append((theme1, c["comment_id"], post["post_id"]))

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
        theme_count = Counter()
        for update in updates:
            theme_count[update[0]] += 1

        print("主题生成并写回成功：")
        print("theme1:", themes[0])
        print("theme2:", themes[1])
        print("theme3:", themes[2])
        print("各主题评论量：", dict(theme_count))

    except Exception as e:
        print("执行失败：", str(e))
        print("如果是依赖缺失，请安装：")
        print("pip install jieba scikit-learn")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()
