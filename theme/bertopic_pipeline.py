# -*- coding: utf-8 -*-
import time
import json
import pymysql
import pandas as pd
from openai import OpenAI

# =========================
# 1. 配置区
# =========================
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4"
}

API_KEY = "sk-03214af033c741ad8dbc45e59976a27e"
BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

BERTOPIC_FILE = "bertopic_topics.xlsx"
TOPIC_COL = "Topic"
KEYWORDS_COL = "Keywords"
DESC_COL = "Semantic_Description"

# 是否从头重跑
RESET_THEME_TABLE = True
RESET_POST_THEME = True

# 只处理 risk_id 为空的主题
ONLY_CLASSIFY_NULL_RISK = False

TOP_N = 30
MID_N = 30

MAX_TITLE_LEN = 300
MAX_CONTENT_LEN = 1500
MAX_COMMENT_LEN = 200

SLEEP_SECONDS = 1


# =========================
# 2. 初始化客户端
# =========================
client = OpenAI(
    api_key=API_KEY,
    base_url=BASE_URL
)


# =========================
# 3. 数据库连接
# =========================
def get_connection():
    return pymysql.connect(**DB_CONFIG)


# =========================
# 4. 工具函数
# =========================
def safe_text(text, max_len=None):
    if text is None:
        return ""
    text = str(text).strip()
    if max_len and len(text) > max_len:
        return text[:max_len]
    return text


def normalize_text(text):
    if text is None:
        return ""
    text = str(text).strip()
    text = text.replace("主题：", "").replace("主题:", "").strip()
    text = text.strip("“”\"' ")
    return text


# =========================
# 5. 建表 / 清表 / 清空 posts 主题
# =========================
def ensure_theme_table():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
            CREATE TABLE IF NOT EXISTS theme_bertopic (
                id INT AUTO_INCREMENT PRIMARY KEY,
                theme VARCHAR(255) NOT NULL,
                theme_source ENUM('existing', 'generated') NOT NULL,
                risk_id INT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE KEY uniq_theme (theme)
            )
            """
            cursor.execute(sql)
        conn.commit()
    finally:
        conn.close()


def reset_theme_table():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE theme_bertopic")
        conn.commit()
    finally:
        conn.close()


def reset_posts_bertopic_theme():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE posts SET bertopic_theme = NULL")
        conn.commit()
    finally:
        conn.close()


# =========================
# 6. BERTopic 主题解释（写回 Excel）
# =========================
def interpret_bertopic_topic(topic_id, keywords):
    prompt = f"""
你是一个擅长主题分析的专家。

下面是一组由BERTopic主题模型输出的主题关键词：

主题编号：{topic_id}
主题关键词：{keywords}

请根据这些关键词，生成一个语义清晰、可读性强、适合论文展示的中文主题短句。

要求：
1. 根据关键词整体语义概括主题
2. 输出一句中文短句即可
3. 长度控制在10~20字左右
4. 表达自然、准确、概括性强
5. 不要直接重复粘贴关键词
6. 不要输出“主题：”
7. 不要解释，不要分点，不要多句话

请直接输出主题短句：
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是一个擅长从BERTopic关键词中提炼语义主题的专家。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    return normalize_text(response.choices[0].message.content)


def ensure_bertopic_excel_has_desc():
    print(f"检查 {BERTOPIC_FILE} 是否已有 {DESC_COL} ...")
    df = pd.read_excel(BERTOPIC_FILE)

    if TOPIC_COL not in df.columns or KEYWORDS_COL not in df.columns:
        raise ValueError(
            f"{BERTOPIC_FILE} 中缺少列 {TOPIC_COL} 或 {KEYWORDS_COL}，当前列：{list(df.columns)}"
        )

    if DESC_COL not in df.columns:
        df[DESC_COL] = ""

    changed = False

    for idx, row in df.iterrows():
        current_desc = normalize_text(row[DESC_COL]) if pd.notna(row[DESC_COL]) else ""
        if current_desc:
            continue

        topic_id = row[TOPIC_COL]
        keywords = str(row[KEYWORDS_COL])

        print(f"[BERTopic解释] 正在处理第 {idx + 1}/{len(df)} 个主题...")
        print(f"Topic: {topic_id}")
        print(f"Keywords: {keywords}")

        try:
            desc = interpret_bertopic_topic(topic_id, keywords)
            print(f"生成结果：{desc}")
            df.at[idx, DESC_COL] = desc
            changed = True
        except Exception as e:
            print(f"解释失败：{e}")
            df.at[idx, DESC_COL] = f"生成失败：{e}"
            changed = True

        df.to_excel(BERTOPIC_FILE, index=False)
        time.sleep(SLEEP_SECONDS)

    if changed:
        print(f"{BERTOPIC_FILE} 已补充/更新 {DESC_COL}")
    else:
        print(f"{BERTOPIC_FILE} 已有完整 {DESC_COL}，跳过解释。")


# =========================
# 7. 主题表写入
# =========================
def insert_theme(theme, theme_source):
    theme = normalize_text(theme)
    if not theme:
        return

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                INSERT IGNORE INTO theme_bertopic (theme, theme_source)
                VALUES (%s, %s)
            """
            cursor.execute(sql, (theme, theme_source))
        conn.commit()
    finally:
        conn.close()


# =========================
# 8. 从 Excel 导入已有主题
# =========================
def load_topics_from_excel():
    df = pd.read_excel(BERTOPIC_FILE)

    if DESC_COL not in df.columns:
        raise ValueError(
            f"{BERTOPIC_FILE} 中没有找到列 {DESC_COL}"
        )

    topics = []
    for _, row in df.iterrows():
        topic = normalize_text(row[DESC_COL])
        if topic and topic.lower() != "nan":
            topics.append(topic)

    deduped = []
    seen = set()
    for t in topics:
        if t not in seen:
            deduped.append(t)
            seen.add(t)

    return deduped


def seed_theme_table():
    print("开始把 Excel 中已有 BERTopic 主题写入 theme_bertopic...")
    topics = load_topics_from_excel()

    for topic in topics:
        insert_theme(topic, "existing")

    print(f"BERTopic 主题导入：{len(topics)} 条")


# =========================
# 9. 从数据库读取候选主题
# =========================
def get_candidate_themes():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT theme
                FROM theme_bertopic
                ORDER BY id ASC
            """
            cursor.execute(sql)
            rows = cursor.fetchall()

        themes = []
        seen = set()
        for row in rows:
            theme = normalize_text(row[0])
            if theme and theme not in seen:
                themes.append(theme)
                seen.add(theme)

        return themes
    finally:
        conn.close()


# =========================
# 10. 读取帖子
# =========================
def get_posts():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT post_id, title, content
                FROM posts
                ORDER BY post_id ASC
            """
            cursor.execute(sql)
            rows = cursor.fetchall()
        return rows
    finally:
        conn.close()


# =========================
# 11. 读取评论
# =========================
def get_comments_by_post_id(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT comment_id, comment_content, like_count
                FROM comments
                WHERE post_id = %s
                  AND comment_content IS NOT NULL
                  AND comment_content <> ''
                ORDER BY like_count DESC, comment_id ASC
            """
            cursor.execute(sql, (post_id,))
            rows = cursor.fetchall()
        return rows
    finally:
        conn.close()


def select_comments(all_comments, top_n=30, mid_n=30):
    if not all_comments:
        return [], []

    total = len(all_comments)
    top_comments = all_comments[:top_n]

    if total <= top_n:
        mid_comments = []
    else:
        mid_start = max(0, total // 2 - mid_n // 2)
        mid_end = min(total, mid_start + mid_n)
        mid_comments = all_comments[mid_start:mid_end]

        top_ids = set(x[0] for x in top_comments)
        mid_comments = [x for x in mid_comments if x[0] not in top_ids]

        if len(mid_comments) < mid_n:
            exist_ids = top_ids | set(x[0] for x in mid_comments)
            remain = [x for x in all_comments if x[0] not in exist_ids]
            need = mid_n - len(mid_comments)
            mid_comments.extend(remain[:need])

    return top_comments, mid_comments


def build_comment_text(comment_rows, tag):
    if not comment_rows:
        return "无"

    lines = []
    for idx, (_, comment_content, like_count) in enumerate(comment_rows, start=1):
        content = safe_text(comment_content, MAX_COMMENT_LEN)
        like_count = 0 if like_count is None else like_count
        lines.append(f"{tag}{idx}（点赞{like_count}）: {content}")
    return "\n".join(lines)


# =========================
# 12. 匹配已有主题（只看标题+正文）
# =========================
def match_existing_theme(title, content, candidate_topics):
    if not candidate_topics:
        return None

    topic_block = "\n".join([f"{i+1}. {topic}" for i, topic in enumerate(candidate_topics)])

    prompt = f"""
你是一个中文文本主题匹配专家。

现在有一篇帖子，请你仅根据“帖子标题”和“帖子正文”，
从候选主题库中选择一个最合适的BERTopic主题

【帖子标题】
{title}

【帖子正文】
{content}

【候选主题库】
{topic_block}

判断要求：
1. 只根据标题和正文判断，不参考评论区
2. 如果候选主题中有一个能准确概括帖子核心内容，就直接返回该主题原文
3. 如果都不合适，返回：NONE
4. 不要解释，不要多写任何内容

输出格式：
- 匹配成功：直接输出候选主题原文
- 不匹配：直接输出 NONE
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是一个严谨的主题匹配助手。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    result = normalize_text(response.choices[0].message.content)

    if result.upper() == "NONE":
        return None

    for topic in candidate_topics:
        if result == topic:
            return topic

    result2 = result.strip("“”\"' ").strip()
    for topic in candidate_topics:
        if result2 == topic:
            return topic

    return None


# =========================
# 13. 生成新主题（帖子+评论）
# =========================
def generate_new_theme(title, content, top_comments_text, mid_comments_text):
    prompt = f"""
你是一个中文社交媒体主题归纳专家。

当前帖子无法匹配已有BERTopic主题库，请根据以下信息生成一个新的综合主题短句。

【帖子标题】
{title}

【帖子正文】
{content}

【高赞评论】
{top_comments_text}

【中间点赞评论】
{mid_comments_text}

要求：
1. 主题应优先围绕帖子核心内容
2. 同时参考评论区主要讨论方向
3. 输出一个简洁、准确、适合数据库存储和论文展示的中文主题短句
4. 长度控制在8~20字
5. 不要输出“主题：”
6. 不要解释，不要分点，不要多句话

请直接输出主题短句：
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是一个擅长社交媒体主题提炼的专家。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.3
    )

    return normalize_text(response.choices[0].message.content)


# =========================
# 14. 回写 posts
# =========================
def update_post_theme(post_id, bertopic_theme=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                UPDATE posts
                SET bertopic_theme = %s
                WHERE post_id = %s
            """
            cursor.execute(sql, (bertopic_theme, post_id))
        conn.commit()
    finally:
        conn.close()


# =========================
# 15. 风险分类
# =========================
def get_risk_types():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT risk_id, risk_name, risk_desc
                FROM risk_type
                ORDER BY risk_id ASC
            """
            cursor.execute(sql)
            rows = cursor.fetchall()
        return rows
    finally:
        conn.close()


def get_themes_to_classify():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if ONLY_CLASSIFY_NULL_RISK:
                sql = """
                    SELECT id, theme, theme_source
                    FROM theme_bertopic
                    WHERE risk_id IS NULL
                    ORDER BY id ASC
                """
            else:
                sql = """
                    SELECT id, theme, theme_source
                    FROM theme_bertopic
                    ORDER BY id ASC
                """
            cursor.execute(sql)
            rows = cursor.fetchall()
        return rows
    finally:
        conn.close()


def classify_theme_to_risk_id(theme, risk_types):
    risk_text = "\n".join([
        f"{risk_id}. {risk_name}：{risk_desc}"
        for risk_id, risk_name, risk_desc in risk_types
    ])

    prompt = f"""
你是一个生成式AI伦理风险分类专家。

请根据下面的“主题”，判断它最适合归入哪一个风险类别，并返回对应的 risk_id。

【主题】
{theme}

【风险类别列表】
{risk_text}

判断要求：
1. 只从上面的风险类别中选择一个最合适的 risk_id
2. 如果该主题不属于任何 AI伦理风险范畴，返回 0
3. 只输出一行 JSON，不要解释，不要多余文字

输出格式：
{{"risk_id": 3}}
或
{{"risk_id": 0}}
"""

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "你是一个严谨的AI伦理风险编号分类助手。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    return response.choices[0].message.content.strip()


def parse_result(text, valid_risk_ids):
    text = text.strip()
    text = text.replace("```json", "").replace("```", "").strip()

    data = json.loads(text)
    risk_id = int(data["risk_id"])

    if risk_id != 0 and risk_id not in valid_risk_ids:
        raise ValueError(f"模型返回了不存在的 risk_id: {risk_id}")

    return risk_id


def update_theme_risk_id(theme_table_id, risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
                UPDATE theme_bertopic
                SET risk_id = %s
                WHERE id = %s
            """
            cursor.execute(sql, (risk_id, theme_table_id))
        conn.commit()
    finally:
        conn.close()


# =========================
# 16. 主流程
# =========================
def main():
    print("===== BERTopic 全流程开始 =====")

    # Step 1: 确保 Excel 有 Semantic_Description
    ensure_bertopic_excel_has_desc()

    # Step 2: 建表 / 清表 / 清空 posts 主题
    ensure_theme_table()

    if RESET_THEME_TABLE:
        print("清空 theme_bertopic ...")
        reset_theme_table()

    if RESET_POST_THEME:
        print("清空 posts.bertopic_theme ...")
        reset_posts_bertopic_theme()

    # Step 3: 导入已有主题
    seed_theme_table()

    # Step 4: 读取候选主题
    candidate_topics = get_candidate_themes()
    print(f"\n当前数据库中的 BERTopic 候选主题数：{len(candidate_topics)}")

    # Step 5: 帖子匹配 / 生成 / 回写
    posts = get_posts()
    print(f"待处理帖子数量：{len(posts)}")

    matched_count = 0
    generated_count = 0
    success_count = 0
    failed_count = 0

    for idx, (post_id, title, content) in enumerate(posts, start=1):
        print("\n" + "=" * 80)
        print(f"正在处理第 {idx}/{len(posts)} 条帖子，post_id={post_id}")

        title = safe_text(title, MAX_TITLE_LEN)
        content = safe_text(content, MAX_CONTENT_LEN)

        print(f"标题：{title}")

        try:
            comments_loaded = False
            top_comments_text = ""
            mid_comments_text = ""

            bertopic_theme = match_existing_theme(
                title=title,
                content=content,
                candidate_topics=candidate_topics
            )

            if bertopic_theme:
                matched_count += 1
                print(f"匹配到 BERTopic 主题：{bertopic_theme}")
                insert_theme(bertopic_theme, "existing")
            else:
                if not comments_loaded:
                    all_comments = get_comments_by_post_id(post_id)
                    top_comments, mid_comments = select_comments(all_comments, TOP_N, MID_N)
                    top_comments_text = build_comment_text(top_comments, "高赞评论")
                    mid_comments_text = build_comment_text(mid_comments, "中间评论")
                    comments_loaded = True

                bertopic_theme = generate_new_theme(
                    title=title,
                    content=content,
                    top_comments_text=top_comments_text,
                    mid_comments_text=mid_comments_text
                )
                generated_count += 1
                print(f"新生成 BERTopic 主题：{bertopic_theme}")
                insert_theme(bertopic_theme, "generated")
                if bertopic_theme not in candidate_topics:
                    candidate_topics.append(bertopic_theme)

            update_post_theme(post_id, bertopic_theme)
            print("已回写到 posts.bertopic_theme")
            success_count += 1

        except Exception as e:
            failed_count += 1
            print(f"处理失败，post_id={post_id}，错误：{e}")

        time.sleep(SLEEP_SECONDS)

    print("\n" + "=" * 80)
    print("帖子主题处理完成")
    print(f"成功：{success_count}")
    print(f"匹配成功：{matched_count}")
    print(f"新生成：{generated_count}")
    print(f"失败：{failed_count}")

    # Step 6: 风险分类
    risk_types = get_risk_types()
    valid_risk_ids = set(r[0] for r in risk_types)
    themes = get_themes_to_classify()

    print(f"\n待分类主题数量：{len(themes)}")

    cls_success = 0
    cls_failed = 0

    for idx, (theme_table_id, theme, theme_source) in enumerate(themes, start=1):
        print("\n" + "-" * 70)
        print(f"正在分类第 {idx}/{len(themes)} 条主题，id={theme_table_id}")
        print(f"theme_source={theme_source}")
        print(f"theme={theme}")

        try:
            result_text = classify_theme_to_risk_id(theme, risk_types)
            print(f"模型输出：{result_text}")

            risk_id = parse_result(result_text, valid_risk_ids)
            update_theme_risk_id(theme_table_id, risk_id)

            print(f"已回写 risk_id={risk_id}")
            cls_success += 1

        except Exception as e:
            cls_failed += 1
            print(f"分类失败，id={theme_table_id}，错误：{e}")

        time.sleep(SLEEP_SECONDS)

    print("\n" + "=" * 80)
    print("风险分类完成")
    print(f"成功：{cls_success}")
    print(f"失败：{cls_failed}")
    print("===== BERTopic 全流程结束 =====")


if __name__ == "__main__":
    main()