import json
import re
import time
from typing import List, Dict, Any
import argparse
import os
import pymysql
from openai import OpenAI


# =========================
# 配置区
# =========================

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

DEEPSEEK_API_KEY = os.getenv("sk-03214af033c741ad8dbc45e59976a27e", "").strip()
DEEPSEEK_BASE_URL = "https://api.deepseek.com"   # 如果你当前项目不是这个地址，就改成你自己的
DEEPSEEK_MODEL = "deepseek-chat"

# 是否每次重跑时清空旧映射
CLEAR_OLD_POST_RISK_MAP = True

# 是否每次重跑时清空 risk_issues 表
CLEAR_OLD_RISK_ISSUES = True

# 风险数量范围
MIN_RISK_COUNT = 5
MAX_RISK_COUNT = 8

# 单个帖子内容截断，避免 prompt 太长
MAX_CONTENT_LEN = 800


# =========================
# 基础工具
# =========================

def has_risks(conn):
    with conn.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) AS cnt FROM risk_issues")
        row = cursor.fetchone()
        return (row["cnt"] or 0) > 0


def get_post_by_id(conn, post_id: int):
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT post_id, title, publish_time, content, theme1, theme2, theme3
            FROM posts
            WHERE post_id = %s
        """, (post_id,))
        return cursor.fetchone()


def delete_post_risk_map(conn, post_id: int):
    with conn.cursor() as cursor:
        cursor.execute("DELETE FROM post_risk_map WHERE post_id = %s", (post_id,))
    conn.commit()

def get_connection():
    return pymysql.connect(**DB_CONFIG)


def get_client():
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )


def safe_str(value):
    if value is None:
        return ""
    return str(value).strip()


def truncate_text(text: str, max_len: int = MAX_CONTENT_LEN) -> str:
    text = safe_str(text)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def extract_json_text(text: str) -> str:
    """
    尝试从模型返回中提取 JSON
    支持：
    - ```json ... ```
    - 普通 JSON 数组/对象
    """
    if not text:
        raise ValueError("模型返回为空")

    text = text.strip()

    # 先匹配 ```json ... ```
    fence_match = re.search(r"```json\s*(.*?)\s*```", text, re.S | re.I)
    if fence_match:
        return fence_match.group(1).strip()

    fence_match2 = re.search(r"```\s*(.*?)\s*```", text, re.S)
    if fence_match2:
        return fence_match2.group(1).strip()

    # 再尝试直接截取第一个 JSON 数组
    array_match = re.search(r"(\[.*\])", text, re.S)
    if array_match:
        return array_match.group(1).strip()

    # 再尝试直接截取第一个 JSON 对象
    obj_match = re.search(r"(\{.*\})", text, re.S)
    if obj_match:
        return obj_match.group(1).strip()

    return text


def call_llm(client: OpenAI, prompt: str, temperature: float = 0.2) -> str:
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": "你是一个严谨的生成式AI伦理风险研究助手，只输出用户要求的结果。"},
            {"role": "user", "content": prompt}
        ],
        temperature=temperature
    )
    return resp.choices[0].message.content.strip()


# =========================
# 建表
# =========================

def create_tables(conn):
    with conn.cursor() as cursor:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS risk_issues (
                risk_id INT AUTO_INCREMENT PRIMARY KEY,
                risk_name VARCHAR(255) NOT NULL UNIQUE,
                risk_desc TEXT
            );
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS post_risk_map (
                id INT AUTO_INCREMENT PRIMARY KEY,
                post_id INT NOT NULL,
                risk_id INT NOT NULL,
                UNIQUE KEY uniq_post_risk (post_id, risk_id),
                CONSTRAINT fk_post_risk_post
                    FOREIGN KEY (post_id) REFERENCES posts(post_id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE,
                CONSTRAINT fk_post_risk_risk
                    FOREIGN KEY (risk_id) REFERENCES risk_issues(risk_id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            );
        """)
    conn.commit()


def clear_old_data(conn):
    with conn.cursor() as cursor:
        if CLEAR_OLD_POST_RISK_MAP:
            cursor.execute("DELETE FROM post_risk_map")
            print("已清空 post_risk_map")

        if CLEAR_OLD_RISK_ISSUES:
            cursor.execute("DELETE FROM risk_issues")
            print("已清空 risk_issues")

    conn.commit()


# =========================
# 读取数据
# =========================

def get_all_posts(conn) -> List[Dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT post_id, title, publish_time, content, theme1, theme2, theme3
            FROM posts
            ORDER BY post_id ASC
        """)
        return cursor.fetchall()


def build_all_posts_summary(posts: List[Dict[str, Any]]) -> str:
    parts = []

    for p in posts:
        post_id = p["post_id"]
        title = safe_str(p.get("title"))
        content = truncate_text(p.get("content"))
        theme1 = safe_str(p.get("theme1"))
        theme2 = safe_str(p.get("theme2"))
        theme3 = safe_str(p.get("theme3"))

        part = f"""
帖子ID：{post_id}
标题：{title}
正文摘要：{content}
主题1：{theme1}
主题2：{theme2}
主题3：{theme3}
""".strip()
        parts.append(part)

    return "\n\n".join(parts)


# =========================
# 第一轮：提炼全局风险
# =========================

def extract_global_risks(client: OpenAI, all_posts_text: str) -> List[Dict[str, str]]:
    prompt = f"""
你是一名生成式AI伦理风险研究助手。

下面给你一批社交媒体帖子，每个帖子包含标题、正文摘要和主题信息。
请你从整体上总结：这些帖子主要反映了当前公众对生成式AI的哪些核心伦理风险认知。

要求：
1. 提炼出 {MIN_RISK_COUNT}-{MAX_RISK_COUNT} 个“全局性的核心风险类别”
2. 风险名称要简洁、学术化、适合论文写作
3. 不要过细，不要为单个帖子单独造类别
4. 风险类别尽量覆盖这批帖子中的主要讨论方向
5. 输出必须为 JSON 数组
6. 每个元素必须包含：
   - risk_name
   - risk_desc

输出格式示例：
[
  {{
    "risk_name": "学术作弊风险",
    "risk_desc": "指利用生成式AI进行论文代写、作业辅助作弊等行为引发的伦理争议"
  }},
  {{
    "risk_name": "信息真实性风险",
    "risk_desc": "指AI生成虚假信息、深度伪造和误导传播等问题"
  }}
]

帖子数据如下：
{all_posts_text}
""".strip()

    result = call_llm(client, prompt)
    print("\n===== 第一轮：全局风险提炼原始返回 =====")
    print(result)

    json_text = extract_json_text(result)
    data = json.loads(json_text)

    if not isinstance(data, list):
        raise ValueError("全局风险提炼结果不是 JSON 数组")

    clean_data = []
    for item in data:
        risk_name = safe_str(item.get("risk_name"))
        risk_desc = safe_str(item.get("risk_desc"))
        if risk_name:
            clean_data.append({
                "risk_name": risk_name,
                "risk_desc": risk_desc
            })

    if not clean_data:
        raise ValueError("没有提取到有效风险类别")

    return clean_data


def insert_risks(conn, risks: List[Dict[str, str]]):
    with conn.cursor() as cursor:
        for r in risks:
            cursor.execute("""
                INSERT INTO risk_issues (risk_name, risk_desc)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                    risk_desc = VALUES(risk_desc)
            """, (r["risk_name"], r["risk_desc"]))
    conn.commit()


def get_risk_dict(conn) -> Dict[str, int]:
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT risk_id, risk_name
            FROM risk_issues
            ORDER BY risk_id ASC
        """)
        rows = cursor.fetchall()

    return {row["risk_name"]: row["risk_id"] for row in rows}


# =========================
# 第二轮：逐帖归类
# =========================

def classify_post_risks(client: OpenAI, post: Dict[str, Any], risk_names: List[str]) -> List[str]:
    risk_text = "\n".join([f"- {name}" for name in risk_names])

    title = safe_str(post.get("title"))
    content = truncate_text(post.get("content"))
    theme1 = safe_str(post.get("theme1"))
    theme2 = safe_str(post.get("theme2"))
    theme3 = safe_str(post.get("theme3"))

    prompt = f"""
你是一名生成式AI伦理风险分类助手。

现在已有一组标准风险类别，请根据帖子的标题、正文摘要和主题信息，
判断该帖子涉及哪些核心风险类别。

标准风险类别：
{risk_text}

帖子信息：
标题：{title}
正文摘要：{content}
主题1：{theme1}
主题2：{theme2}
主题3：{theme3}

要求：
1. 只能从上面的标准风险类别中选择
2. 选择 1-3 个最相关的类别
3. 按相关性从高到低排序
4. 输出必须为 JSON 数组
5. 不要解释，不要输出多余文字

输出示例：
["学术作弊风险", "信息真实性风险"]
""".strip()

    result = call_llm(client, prompt)
    print(f"\n===== 帖子 {post['post_id']} 风险归类原始返回 =====")
    print(result)

    json_text = extract_json_text(result)
    data = json.loads(json_text)

    if not isinstance(data, list):
        raise ValueError(f"帖子 {post['post_id']} 的分类结果不是 JSON 数组")

    selected = []
    valid_set = set(risk_names)

    for item in data:
        risk_name = safe_str(item)
        if risk_name in valid_set and risk_name not in selected:
            selected.append(risk_name)

    if not selected:
        raise ValueError(f"帖子 {post['post_id']} 未匹配到有效风险类别")

    return selected


def insert_post_risk_map(conn, post_id: int, risk_ids: List[int]):
    with conn.cursor() as cursor:
        for risk_id in risk_ids:
            cursor.execute("""
                INSERT IGNORE INTO post_risk_map (post_id, risk_id)
                VALUES (%s, %s)
            """, (post_id, risk_id))
    conn.commit()


# =========================
# 主流程
# =========================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--post-id", type=int, required=False)
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection()
        client = get_client()

        print("1. 创建表...")
        create_tables(conn)

        # 如果 risk_issues 为空，初始化一次全局风险类别
        if not has_risks(conn):
            print("2. risk_issues 为空，开始初始化全局风险类别...")
            posts = get_all_posts(conn)
            if not posts:
                print("posts 表中没有数据，程序结束。")
                return

            all_posts_text = build_all_posts_summary(posts)
            risks = extract_global_risks(client, all_posts_text)
            insert_risks(conn, risks)

        risk_dict = get_risk_dict(conn)
        risk_names = list(risk_dict.keys())

        # 单帖增量更新
        if args.post_id:
            post = get_post_by_id(conn, args.post_id)
            if not post:
                print(f"未找到 post_id={args.post_id}")
                return

            selected_risk_names = classify_post_risks(client, post, risk_names)
            selected_risk_ids = [
                risk_dict[name]
                for name in selected_risk_names
                if name in risk_dict
            ]

            delete_post_risk_map(conn, args.post_id)
            insert_post_risk_map(conn, args.post_id, selected_risk_ids)

            print(f"post_id={args.post_id} 风险更新完成：{selected_risk_names}")
            return

        # 如果没传 post_id，保留全量更新能力
        posts = get_all_posts(conn)
        for idx, post in enumerate(posts, 1):
            post_id = post["post_id"]
            print(f"\n--- 正在处理帖子 {post_id} ({idx}/{len(posts)}) ---")

            try:
                selected_risk_names = classify_post_risks(client, post, risk_names)
                selected_risk_ids = [
                    risk_dict[name]
                    for name in selected_risk_names
                    if name in risk_dict
                ]

                delete_post_risk_map(conn, post_id)
                insert_post_risk_map(conn, post_id, selected_risk_ids)

                print(f"帖子 {post_id} 归类成功：{selected_risk_names}")

            except Exception as e:
                print(f"帖子 {post_id} 归类失败：{e}")

            time.sleep(1)

        print("\n全部处理完成。")

    except Exception as e:
        print(f"程序运行失败：{e}")

    finally:
        if conn:
            conn.close()


if __name__ == "__main__":
    main()