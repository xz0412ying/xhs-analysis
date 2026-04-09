import json
import os
import re

from openai import OpenAI

from workflow_ui.db import get_connection
from workflow_ui.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL_NAME


def clean_text(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text).strip())


def create_deepseek_client():
    api_key = DEEPSEEK_API_KEY or os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法执行风险判断。")

    return OpenAI(
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL
    )


def get_post_themes(post_id: int):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT post_id, title, content, theme1, theme2, theme3
                FROM posts
                WHERE post_id = %s
            """, (post_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def get_all_risks():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name, risk_desc
                FROM risk_issues
                ORDER BY risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


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


def build_risk_judge_prompt(post, existing_risks):
    themes = [
        clean_text(post.get("theme1", "")),
        clean_text(post.get("theme2", "")),
        clean_text(post.get("theme3", "")),
    ]
    themes = [t for t in themes if t]

    risk_list = []
    for r in existing_risks:
        risk_list.append({
            "risk_id": r["risk_id"],
            "risk_name": clean_text(r["risk_name"]),
            "risk_desc": clean_text(r.get("risk_desc", "")),
        })

    prompt = f"""
你是“生成式AI伦理风险分类助手”。

现在需要根据一个帖子的 3 个主题，判断它们是否可以归入已有风险类型。
如果某个主题无法合理归入已有风险，则需要新增一个风险主题。

【帖子标题】
{clean_text(post.get("title", ""))}

【帖子正文】
{clean_text(post.get("content", ""))[:500]}

【帖子主题】
{json.dumps(themes, ensure_ascii=False)}

【已有风险类型】
{json.dumps(risk_list, ensure_ascii=False)}

请严格按照以下规则输出：

1. 对每个主题，优先匹配已有风险。
2. 只有当某个主题与现有风险明显不匹配时，才新增风险。
3. 新增风险主题命名要简洁、学术化、适合数据库字段展示，长度建议 6-16 字。
4. 同一个帖子最终风险结果可以有多个。
5. 如果 3 个主题都能归入已有风险，则 new_risks 返回空数组。
6. 只输出 JSON，不要输出解释、代码块、额外文字。

输出格式：
{{
  "matched_risk_ids": [1, 2],
  "new_risks": [
    {{
      "risk_name": "xxx",
      "risk_desc": "xxx"
    }}
  ]
}}
""".strip()

    return prompt


def call_llm_risk_classifier(post, existing_risks):
    client = create_deepseek_client()
    prompt = build_risk_judge_prompt(post, existing_risks)

    response = client.chat.completions.create(
        model=DEEPSEEK_MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "你是一个严格输出 JSON 的生成式AI伦理风险分类助手。"
            },
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

    raw_output = response.choices[0].message.content.strip()
    parsed = parse_json_from_llm_output(raw_output)

    if parsed is None:
        raise RuntimeError(f"风险分类 JSON 解析失败，模型原始输出：{raw_output}")

    matched_risk_ids = parsed.get("matched_risk_ids", [])
    new_risks = parsed.get("new_risks", [])

    if not isinstance(matched_risk_ids, list):
        matched_risk_ids = []

    if not isinstance(new_risks, list):
        new_risks = []

    valid_ids = []
    for x in matched_risk_ids:
        try:
            valid_ids.append(int(x))
        except Exception:
            pass

    normalized_new_risks = []
    for item in new_risks:
        if not isinstance(item, dict):
            continue
        risk_name = clean_text(item.get("risk_name", ""))
        risk_desc = clean_text(item.get("risk_desc", ""))
        if not risk_name:
            continue
        if not risk_desc:
            risk_desc = f"由帖子主题自动扩展生成的风险类型：{risk_name}"
        normalized_new_risks.append({
            "risk_name": risk_name,
            "risk_desc": risk_desc
        })

    return {
        "matched_risk_ids": list(set(valid_ids)),
        "new_risks": normalized_new_risks
    }


def get_or_create_risk_id(conn, risk_name: str, risk_desc: str = ""):
    risk_name = clean_text(risk_name)
    risk_desc = clean_text(risk_desc)

    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT risk_id
            FROM risk_issues
            WHERE risk_name = %s
            LIMIT 1
        """, (risk_name,))
        row = cursor.fetchone()
        if row:
            return row["risk_id"]

        cursor.execute("""
            INSERT INTO risk_issues (risk_name, risk_desc)
            VALUES (%s, %s)
        """, (risk_name, risk_desc))
        conn.commit()
        return cursor.lastrowid


def detect_risks_for_post(post_id: int):
    post = get_post_themes(post_id)
    if not post:
        raise RuntimeError(f"post_id={post_id} 不存在，无法进行风险分类。")

    existing_risks = get_all_risks()
    llm_result = call_llm_risk_classifier(post, existing_risks)

    matched_risk_ids = llm_result["matched_risk_ids"]
    new_risks = llm_result["new_risks"]

    conn = get_connection()
    try:
        final_risk_ids = set(matched_risk_ids)

        for item in new_risks:
            risk_id = get_or_create_risk_id(
                conn=conn,
                risk_name=item["risk_name"],
                risk_desc=item["risk_desc"]
            )
            final_risk_ids.add(risk_id)

        return sorted(list(final_risk_ids))
    finally:
        conn.close()


def refresh_post_risk_map(post_id: int, risk_ids):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM post_risk_map
                WHERE post_id = %s
            """, (post_id,))

            if risk_ids:
                cursor.executemany("""
                    INSERT INTO post_risk_map (post_id, risk_id)
                    VALUES (%s, %s)
                """, [(post_id, risk_id) for risk_id in risk_ids])

        conn.commit()
    finally:
        conn.close()