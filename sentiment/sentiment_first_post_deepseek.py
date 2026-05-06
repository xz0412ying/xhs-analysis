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

DEEPSEEK_API_KEY = "sk-03214af033c741ad8dbc45e59976a27e"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
MODEL_NAME = "deepseek-chat"

BATCH_SIZE = 10
ONLY_NULL = True


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


# =========================
# prompt（低token版）
# =========================
def build_prompt(batch):
    text = "\n".join([
        f'{i+1}. 主题={x["bertopic_theme"][:30]} 评论={x["comment_content"][:150]}'
        for i, x in enumerate(batch)
    ])

    return f"""
判断每条评论情感，输出JSON数组：

sentiment_label=[积极,中性,消极]
sentiment_score=0-10整数
attitude_type=[支持,认可,担忧,警惕,质疑,反对,愤怒,疑惑,调侃,无明显态度]

只输出JSON数组，顺序必须一致。

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


# =========================
# JSON解析（增强版）
# =========================
def parse_json(text):
    text = re.sub(r"```json|```", "", text).strip()

    try:
        return json.loads(text)
    except:
        pass

    match = re.search(r"\[.*\]", text, re.S)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass

    return None


# =========================
# 写入数据库（用顺序匹配）
# =========================
def update_result(conn, batch, results):
    with conn.cursor() as c:
        for i, r in enumerate(results):
            try:
                comment_id = batch[i]["comment_id"]

                sentiment_label = r.get("sentiment_label", "中性")
                sentiment_score = int(r.get("sentiment_score", 5))
                attitude_type = r.get("attitude_type", "无明显态度")

                c.execute("""
                UPDATE comments
                SET sentiment_label=%s,
                    sentiment_score=%s,
                    attitude_type=%s
                WHERE comment_id=%s
                """, (
                    sentiment_label,
                    sentiment_score,
                    attitude_type,
                    comment_id
                ))

            except Exception as e:
                print("单条失败:", e, r)


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

            # ⚠️ 数量校验（非常重要）
            if len(result) != len(batch):
                print("数量不一致，跳过:", len(result), len(batch))
                continue

            update_result(conn, batch, result)
            conn.commit()

            print(f"[批次 {i//BATCH_SIZE+1}] 成功 {len(batch)} 条")

        except Exception as e:
            conn.rollback()
            print("批次失败:", e)

    conn.close()


if __name__ == "__main__":
    run()