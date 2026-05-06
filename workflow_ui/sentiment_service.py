import pymysql
import random
from openai import OpenAI

# 从 sentiment_first_post_deepseek 导入配置和现有函数
from sentiment.sentiment_first_post_deepseek import (
    DB_CONFIG,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    MODEL_NAME,
    build_prompt,
    call_llm,
    parse_json
)

def is_valid_api_key(api_key):
    """检查API key是否有效"""
    if not api_key or api_key.strip() == "":
        return False
    # 检查是否包含中文字符（占位符）
    if any('\u4e00' <= c <= '\u9fff' for c in api_key):
        return False
    return True

def create_db_connection():
    """创建数据库连接"""
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)

def create_deepseek_client():
    """创建DeepSeek客户端"""
    return OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)

def analyze_comment_with_mock(comment_theme, comment_text):
    """模拟分析单条评论的情感和态度（用于测试）"""
    sentiment_labels = ["积极", "中性", "消极"]
    sentiment_probs = [0.4, 0.4, 0.2]  # 积极40%, 中性40%, 消极20%
    
    attitude_types = ["支持", "认可", "担忧", "警惕", "质疑", "反对", "愤怒", "疑惑", "调侃", "无明显态度"]
    
    # 根据评论内容简单判断情感倾向
    positive_words = ["好", "棒", "喜欢", "推荐", "满意", "不错", "优秀", "赞", "完美", "惊喜"]
    negative_words = ["差", "烂", "失望", "不好", "不满意", "垃圾", "坑", "贵", "慢", "瑕疵"]
    
    text = comment_text.lower()
    positive_count = sum(1 for w in positive_words if w in text)
    negative_count = sum(1 for w in negative_words if w in text)
    
    if positive_count > negative_count:
        sentiment_label = "积极"
        sentiment_score = random.randint(7, 10)
    elif negative_count > positive_count:
        sentiment_label = "消极"
        sentiment_score = random.randint(0, 3)
    else:
        sentiment_label = random.choices(sentiment_labels, weights=sentiment_probs)[0]
        if sentiment_label == "积极":
            sentiment_score = random.randint(6, 10)
        elif sentiment_label == "消极":
            sentiment_score = random.randint(0, 4)
        else:
            sentiment_score = random.randint(4, 6)
    
    # 根据情感标签选择态度类型
    if sentiment_label == "积极":
        attitude_type = random.choice(["支持", "认可"])
    elif sentiment_label == "消极":
        attitude_type = random.choice(["担忧", "警惕", "质疑", "反对"])
    else:
        attitude_type = random.choice(["无明显态度", "疑惑", "调侃"])
    
    return sentiment_label, sentiment_score, attitude_type

def fetch_comments_for_post(conn, post_id, reanalyze_all=True):
    """获取指定帖子的评论"""
    with conn.cursor() as c:
        sql = """
        SELECT c.comment_id, c.comment_content, c.assigned_theme
        FROM comments c
        JOIN posts p ON c.post_id = p.post_id
        WHERE c.post_id = %s
        """
        if not reanalyze_all:
            sql += " AND c.attitude_type IS NULL"
        sql += " ORDER BY c.comment_id ASC"
        c.execute(sql, (post_id,))
        return c.fetchall()

def analyze_comment_with_deepseek(client, comment_theme, comment_text):
    """分析单条评论的情感和态度"""
    prompt = f"""
按主题和评论判断情感，输出JSON：

sentiment_label=[积极,中性,消极]
sentiment_score=0-10整数
attitude_type=[支持,认可,担忧,警惕,质疑,反对,愤怒,疑惑,调侃,无明显态度]

只输出JSON对象。

主题={comment_theme[:30] if comment_theme else ""}
评论={comment_text[:150]}
""".strip()
    
    raw = call_llm(client, prompt)
    result = parse_json(raw)
    
    if isinstance(result, list) and len(result) > 0:
        result = result[0]
    elif not isinstance(result, dict):
        result = {}
    
    sentiment_label = result.get("sentiment_label", "中性")
    sentiment_score = result.get("sentiment_score", 5)
    attitude_type = result.get("attitude_type", "无明显态度")
    
    return sentiment_label, sentiment_score, attitude_type

def save_comment_sentiment_result(conn, comment_id, sentiment_label, sentiment_score, attitude_type):
    """保存评论情感分析结果"""
    with conn.cursor() as c:
        c.execute("""
        UPDATE comments
        SET sentiment_label=%s,
            sentiment_score=%s,
            attitude_type=%s
        WHERE comment_id=%s
        """, (sentiment_label, sentiment_score, attitude_type, comment_id))

def run_sentiment_analysis_for_post_id(post_id, reanalyze_all=True):
    """对指定帖子进行情感分析"""
    conn = create_db_connection()
    
    # 检查API key是否有效
    use_mock = not is_valid_api_key(DEEPSEEK_API_KEY)
    if use_mock:
        print("警告：没有有效的 DEEPSEEK_API_KEY，使用模拟情感分析")
    
    client = None if use_mock else create_deepseek_client()
    
    try:
        comments = fetch_comments_for_post(conn, post_id, reanalyze_all)
        if not comments:
            return {"total": 0, "positive": 0, "neutral": 0, "negative": 0}

        positive_count = 0
        neutral_count = 0
        negative_count = 0

        for row in comments:
            comment_id = row["comment_id"]
            comment_content = row.get("comment_content", "")
            comment_theme = row.get("assigned_theme", "")

            if use_mock:
                sentiment_label, sentiment_score, attitude_type = analyze_comment_with_mock(
                    comment_theme=comment_theme,
                    comment_text=comment_content
                )
            else:
                sentiment_label, sentiment_score, attitude_type = analyze_comment_with_deepseek(
                    client=client,
                    comment_theme=comment_theme,
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

        return {
            "total": len(comments),
            "positive": positive_count,
            "neutral": neutral_count,
            "negative": negative_count
        }
    finally:
        conn.close()