import json
import re
import pymysql
from openai import OpenAI

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
# DeepSeek 配置
# =========================
DEEPSEEK_API_KEY = "sk-03214af033c741ad8dbc45e59976a27e"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL_NAME = "deepseek-chat"

# =========================
# 任务配置
# =========================
ONLY_ANALYZE_NULL_ATTITUDE = True   # True=只分析 attitude_type 为空的评论
LIMIT_COMMENTS = None               # 例如 100；不限制就填 None


def create_db_connection():
    return pymysql.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
        database=DB_CONFIG["database"],
        charset=DB_CONFIG["charset"],
        cursorclass=pymysql.cursors.DictCursor
    )


def create_deepseek_client():
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )


def clean_text(text: str) -> str:
    if not text:
        return ""
    return str(text).strip().replace("\n", " ").replace("\r", " ")


def fetch_comments_with_post_theme(conn, only_null_attitude=True, limit_comments=None):
    with conn.cursor() as cursor:
        sql = """
            SELECT
                c.comment_id,
                c.post_id,
                c.comment_content,
                c.sentiment_label,
                c.sentiment_score,
                c.attitude_type,
                p.title,
                p.bertopic_theme
            FROM comments c
            JOIN posts p ON c.post_id = p.post_id
            WHERE 1=1
        """
        params = []

        if only_null_attitude:
            sql += " AND c.attitude_type IS NULL "

        sql += " ORDER BY c.comment_id ASC "

        if limit_comments is not None:
            sql += " LIMIT %s "
            params.append(limit_comments)

        cursor.execute(sql, params)
        return cursor.fetchall()


def fetch_comments_for_post(conn, post_id):
    with conn.cursor() as cursor:
        sql = """
            SELECT
                c.comment_id,
                c.post_id,
                c.comment_content,
                c.sentiment_label,
                c.sentiment_score,
                c.attitude_type,
                p.title,
                p.bertopic_theme
            FROM comments c
            JOIN posts p ON c.post_id = p.post_id
            WHERE c.post_id = %s
            ORDER BY c.comment_id ASC
        """
        cursor.execute(sql, (post_id,))
        return cursor.fetchall()


def build_deepseek_sentiment_prompt(post_theme: str, comment_text: str) -> str:
    return f"""
你是一名中文社交媒体评论分析助手。请结合“评论所属帖子的BERTopic主题”和“评论内容”进行分析。

【帖子主题（BERTopic）】
{post_theme}

【评论内容】
{comment_text}

请严格遵循以下规则：

1. 你需要输出三个字段：
- sentiment_label：评论整体情感极性
- sentiment_score：评论整体情感强度分数
- attitude_type：评论针对该帖子主题所呈现的主要态度类型

2. sentiment_label 只能从以下三个标签中选一个：
- 积极
- 中性
- 消极

3. sentiment_score 必须是 0~10 的整数：
- 0~3：明显消极
- 4~6：中性、复杂、轻微倾向或态度不明显
- 7~10：明显积极

4. attitude_type 只能从以下标签中选一个：
- 支持
- 认可
- 担忧
- 警惕
- 质疑
- 反对
- 愤怒
- 疑惑
- 调侃
- 无明显态度

5. 判断要求：
- attitude_type 必须围绕“该评论对帖子主题的态度”来判断
- 不要脱离帖子主题单独判断
- sentiment_label 判断评论整体情绪倾向
- sentiment_score 判断评论整体情绪强弱
- 如果评论是在认同帖子主题下的观点、事实或批评，优先标为“支持”或“认可”
- 如果评论是在否定帖子主题下的观点，标为“反对”或“质疑”
- 如果评论主要表达风险顾虑，标为“担忧”或“警惕”
- 如果评论主要表示不确定、提问、没看懂，标为“疑惑”
- 如果评论主要是讽刺、玩梗、阴阳怪气，标为“调侃”
- 如果评论没有明确态度，标为“无明显态度”

6. 若帖子主题信息较抽象，也需要结合评论内容判断该评论对这一主题的基本态度。

7. 只输出 JSON，不要输出解释、前后缀、代码块。

输出格式如下：
{{
  "sentiment_label": "积极/中性/消极",
  "sentiment_score": 0,
  "attitude_type": "支持/认可/担忧/警惕/质疑/反对/愤怒/疑惑/调侃/无明显态度"
}}
""".strip()


def parse_json_from_llm_output(text: str):
    if not text:
        return None

    text = text.strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        pass

    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group())
        except Exception:
            pass

    return None


def normalize_llm_result(result: dict):
    valid_sentiment_labels = {"积极", "中性", "消极"}
    valid_attitude_types = {
        "支持", "认可", "担忧", "警惕", "质疑",
        "反对", "愤怒", "疑惑", "调侃", "无明显态度"
    }

    sentiment_label = str(result.get("sentiment_label", "")).strip()
    attitude_type = str(result.get("attitude_type", "")).strip()

    try:
        sentiment_score = int(result.get("sentiment_score", 5))
    except Exception:
        sentiment_score = 5

    if sentiment_label not in valid_sentiment_labels:
        sentiment_label = "中性"

    if attitude_type not in valid_attitude_types:
        attitude_type = "无明显态度"

    if sentiment_score < 0:
        sentiment_score = 0
    if sentiment_score > 10:
        sentiment_score = 10

    return sentiment_label, sentiment_score, attitude_type


def analyze_comment_with_deepseek(client, post_theme: str, comment_text: str):
    cleaned_theme = clean_text(post_theme)
    cleaned_comment = clean_text(comment_text)

    if not cleaned_comment:
        return "中性", 5, "无明显态度"

    if not cleaned_theme:
        cleaned_theme = "未提供帖子主题，请结合评论内容概括其针对的主题后再判断情感和态度。"

    prompt = build_deepseek_sentiment_prompt(cleaned_theme, cleaned_comment)

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL_NAME,
        messages=[
            {
                "role": "system",
                "content": "你是一个严格输出 JSON 的中文评论情感分析助手。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        temperature=0
    )

    raw_output = response.choices[0].message.content.strip()
    parsed = parse_json_from_llm_output(raw_output)

    if parsed is None:
        print(f"[JSON解析失败] 模型原始输出：{raw_output}")
        return "中性", 5, "无明显态度"

    return normalize_llm_result(parsed)


def save_comment_sentiment_result(conn, comment_id: int, sentiment_label: str, sentiment_score: int, attitude_type: str):
    with conn.cursor() as cursor:
        sql = """
            UPDATE comments
            SET sentiment_label = %s,
                sentiment_score = %s,
                attitude_type = %s
            WHERE comment_id = %s
        """
        cursor.execute(sql, (sentiment_label, sentiment_score, attitude_type, comment_id))


def run_deepseek_sentiment_analysis():
    conn = None
    try:
        conn = create_db_connection()
        client = create_deepseek_client()

        comments = fetch_comments_with_post_theme(
            conn=conn,
            only_null_attitude=ONLY_ANALYZE_NULL_ATTITUDE,
            limit_comments=LIMIT_COMMENTS
        )

        if not comments:
            print("没有找到待分析评论，程序结束。")
            return

        print(f"\n共找到 {len(comments)} 条待分析评论，开始逐条分析...\n")

        positive_count = 0
        neutral_count = 0
        negative_count = 0

        for index, row in enumerate(comments, start=1):
            comment_id = row["comment_id"]
            post_id = row["post_id"]
            title = clean_text(row.get("title", ""))
            post_theme = row.get("bertopic_theme", "")
            comment_content = row.get("comment_content", "")

            try:
                sentiment_label, sentiment_score, attitude_type = analyze_comment_with_deepseek(
                    client=client,
                    post_theme=post_theme,
                    comment_text=comment_content
                )

                save_comment_sentiment_result(
                    conn=conn,
                    comment_id=comment_id,
                    sentiment_label=sentiment_label,
                    sentiment_score=sentiment_score,
                    attitude_type=attitude_type
                )
                conn.commit()

                if sentiment_label == "积极":
                    positive_count += 1
                elif sentiment_label == "消极":
                    negative_count += 1
                else:
                    neutral_count += 1

                print(
                    f"[{index}/{len(comments)}] "
                    f"comment_id={comment_id} | post_id={post_id} | "
                    f"title={title[:20]} | "
                    f"theme={clean_text(post_theme)[:30]} | "
                    f"label={sentiment_label} | score={sentiment_score} | attitude={attitude_type} | "
                    f"content={clean_text(comment_content)[:40]}"
                )

            except Exception as e:
                conn.rollback()
                print(f"[评论分析失败] comment_id={comment_id} | post_id={post_id} | error={e}")

        print("\n全部评论分析完成")
        print(f"积极: {positive_count} | 中性: {neutral_count} | 消极: {negative_count}")

    except Exception as e:
        print(f"程序运行出错: {e}")
    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    run_deepseek_sentiment_analysis()