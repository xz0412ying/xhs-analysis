import json
import re
import pymysql
from openai import OpenAI

# =========================
# 配置
# =========================
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4"
}

DEEPSEEK_API_KEY = "你的新API_KEY"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

BATCH_SIZE = 10   # 每批处理数量
ONLY_NULL = True  # 只处理未分析的


# =========================
# 数据库
# =========================
def get_conn():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def fetch_comments(conn):
    with conn.cursor() as c:
        sql = """
        SELECT c.comment_id, c.comment_content, p.bertopic_theme
        FROM comments c
        JOIN posts p ON c.post_id = p.post_id
        WHERE 1=1
        """
        if ONLY_NULL:
            sql += " AND c.attitude_type IS NULL"

        sql += " ORDER BY c.comment_id ASC"
        c.execute(sql)
        return c.fetchall()


def update_result(conn, results):
    with conn.cursor() as c:
        for r in results:
            c.execute("""
            UPDATE comments
            SET sentiment_label=%s,
                sentiment_score=%s,
                attitude_type=%s
            WHERE comment_id=%s
            """, (
                r["sentiment_label"],
                r["sentiment_score"],
                r["attitude_type"],
                r["comment_id"]
            ))


# =========================
# prompt（极简版）
# =========================
def build_prompt(batch):
    text = "\n".join([
        f'{i+1}. id={x["comment_id"]} 主题={x["bertopic_theme"][:30]} 评论={x["comment_content"][:150]}'
        for i, x in enumerate(batch)
    ])

    return f"""
按主题和评论判断情感，输出JSON数组：

sentiment_label=[积极,中性,消极]
sentiment_score=0-10整数
attitude_type=[支持,认可,担忧,警惕,质疑,反对,愤怒,疑惑,调侃,无明显态度]

只输出JSON数组。

{text}
""".strip()


# =========================
# 调用模型
# =========================
def call_llm(client, prompt):
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": "只输出JSON"},
            {"role": "user", "content": prompt}
        ],
        temperature=0
    )
    return resp.choices[0].message.content.strip()


def parse_json(text):
    text = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(text)
    except:
        m = re.search(r"\[.*\]", text, re.S)
        if m:
            return json.loads(m.group())
    return None


# =========================
# 主流程
# =========================
def run():
    conn = get_conn()
    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

    data = fetch_comments(conn)
    print(f"共 {len(data)} 条评论")

    for i in range(0, len(data), BATCH_SIZE):
        batch = data[i:i+BATCH_SIZE]

        try:
            prompt = build_prompt(batch)
            raw = call_llm(client, prompt)
            result = parse_json(raw)

            if not result:
                print("解析失败:", raw)
                continue

            update_result(conn, result)
            conn.commit()

            print(f"[{i//BATCH_SIZE+1}] 成功处理 {len(batch)} 条")

        except Exception as e:
            conn.rollback()
            print("错误:", e)

    conn.close()


if __name__ == "__main__":
    run()