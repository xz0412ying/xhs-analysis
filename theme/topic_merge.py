# -*- coding: utf-8 -*-
"""
主题合并脚本
用于检测并合并只有单个帖子的主题，使用 DeepSeek API 进行智能匹配
"""

import json
import re
import pymysql
from openai import OpenAI
from collections import Counter

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

# 单帖主题阈值（低于此数量的主题将被合并）
SINGLE_POST_THRESHOLD = 1

# 合并置信度阈值（高于此值才进行合并）
MERGE_CONFIDENCE_THRESHOLD = 0.6


# =========================
# 数据库连接
# =========================
def get_conn():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def close_conn(conn):
    if conn:
        conn.close()


# =========================
# DeepSeek 客户端
# =========================
def get_deepseek_client():
    return OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )


# =========================
# 获取主题统计信息
# =========================
def get_topic_post_counts(conn):
    """
    获取每个主题的帖子数量
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT bertopic_theme as theme, COUNT(DISTINCT post_id) as post_count
            FROM posts
            WHERE bertopic_theme IS NOT NULL AND bertopic_theme != ''
            GROUP BY bertopic_theme
            ORDER BY post_count ASC
        """)
        result = cursor.fetchall()
    
    return {item['theme']: item['post_count'] for item in result}


def get_single_post_topics(conn):
    """
    获取只有单个帖子的主题列表
    """
    topic_counts = get_topic_post_counts(conn)
    return [theme for theme, count in topic_counts.items() if count <= SINGLE_POST_THRESHOLD]


def get_multi_post_topics(conn):
    """
    获取有多个帖子的主题列表（作为合并目标）
    """
    topic_counts = get_topic_post_counts(conn)
    return [theme for theme, count in topic_counts.items() if count > SINGLE_POST_THRESHOLD]


# =========================
# 获取主题相关的帖子内容
# =========================
def get_posts_for_topic(conn, theme):
    """
    获取指定主题下的所有帖子
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT post_id, title, content
            FROM posts
            WHERE bertopic_theme = %s
        """, (theme,))
        return cursor.fetchall()


def get_comments_for_topic(conn, theme):
    """
    获取指定主题下的所有评论
    """
    with conn.cursor() as cursor:
        cursor.execute("""
            SELECT c.comment_content
            FROM comments c
            JOIN posts p ON c.post_id = p.post_id
            WHERE p.bertopic_theme = %s
              AND c.comment_content IS NOT NULL
              AND c.comment_content != ''
        """, (theme,))
        return [item['comment_content'] for item in cursor.fetchall()]


# =========================
# 使用 DeepSeek 进行主题匹配
# =========================
def build_topic_match_prompt(source_theme, source_content, target_topics):
    """
    构建主题匹配的 prompt
    """
    topics_list = "\n".join([f"- {i+1}. {topic}" for i, topic in enumerate(target_topics)])
    
    prompt = f"""
你是一个主题匹配专家。请帮我判断以下主题应该合并到哪个现有主题中。

源主题信息：
主题名称：{source_theme}

源主题内容摘要：
{source_content[:500]}

目标主题列表（可以选择合并到其中一个，或选择"不合并"）：
{topics_list}

请按照以下 JSON 格式输出你的判断：
{{
    "matched_topic": "目标主题名称或'不合并'",
    "confidence": 0.0-1.0之间的置信度,
    "reason": "简要说明匹配理由"
}}

注意：
1. 置信度表示你对匹配结果的确定程度
2. 如果源主题与任何目标主题都不相关，请选择"不合并"
3. 输出必须是有效的 JSON 格式
"""
    return prompt.strip()


def call_deepseek_match(source_theme, source_content, target_topics):
    """
    调用 DeepSeek API 进行主题匹配
    """
    client = get_deepseek_client()
    
    prompt = build_topic_match_prompt(source_theme, source_content, target_topics)
    
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个专业的文本分类和主题匹配专家，擅长分析中文文本内容。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        result = response.choices[0].message.content.strip()
        
        # 尝试解析 JSON
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            # 如果 JSON 解析失败，尝试提取结果
            match = re.search(r'"matched_topic":\s*["\'](.*?)["\']', result)
            if match:
                return {
                    "matched_topic": match.group(1),
                    "confidence": 0.7,
                    "reason": "解析结果提取"
                }
            return None
            
    except Exception as e:
        print(f"⚠️ DeepSeek API 调用失败: {e}")
        return None


# =========================
# 合并主题
# =========================
def merge_topics(conn, source_theme, target_theme):
    """
    将源主题的帖子合并到目标主题
    """
    with conn.cursor() as cursor:
        # 更新帖子的主题
        cursor.execute("""
            UPDATE posts
            SET bertopic_theme = %s
            WHERE bertopic_theme = %s
        """, (target_theme, source_theme))
    
    conn.commit()
    print_info(f"已将主题 '{source_theme}' 合并到 '{target_theme}'")


def print_info(msg):
    """
    安全打印信息，处理编码问题
    """
    try:
        print(f"✅ {msg}")
    except UnicodeEncodeError:
        # 尝试用不同编码输出
        try:
            print(f"OK {msg.encode('utf-8', errors='replace').decode('utf-8')}")
        except:
            print("OK 操作已完成")


def simulate_merge(source_theme, target_topics):
    """
    模拟匹配（当 API 不可用时使用）
    """
    # 简单的相似度匹配
    source_lower = source_theme.lower()
    
    best_match = None
    best_score = 0
    
    for target in target_topics:
        target_lower = target.lower()
        
        # 检查是否有相同的关键词
        score = 0
        source_words = set(source_lower.split())
        target_words = set(target_lower.split())
        
        common_words = source_words & target_words
        if common_words:
            score = len(common_words) / max(len(source_words), len(target_words))
        
        # 检查子字符串匹配
        if source_lower in target_lower or target_lower in source_lower:
            score = max(score, 0.7)
        
        if score > best_score:
            best_score = score
            best_match = target
    
    if best_match and best_score >= MERGE_CONFIDENCE_THRESHOLD:
        return {
            "matched_topic": best_match,
            "confidence": best_score,
            "reason": f"关键词匹配度: {best_score:.2f}"
        }
    
    return {
        "matched_topic": "不合并",
        "confidence": 0.0,
        "reason": "没有找到足够相似的主题"
    }


# =========================
# 主程序
# =========================
def main(use_api=True):
    print("===== 主题合并脚本开始 =====")
    
    conn = get_conn()
    
    try:
        # 获取主题统计
        topic_counts = get_topic_post_counts(conn)
        print(f"\n总主题数: {len(topic_counts)}")
        
        # 获取单帖主题和多帖主题
        single_topics = get_single_post_topics(conn)
        multi_topics = get_multi_post_topics(conn)
        
        print(f"单帖主题数: {len(single_topics)}")
        print(f"多帖主题数: {len(multi_topics)}")
        
        if single_topics:
            print("\n单帖主题列表:")
            for i, topic in enumerate(single_topics, 1):
                print(f"  {i}. {topic}")
        
        if not multi_topics:
            print("\n❌ 没有找到多帖主题作为合并目标，无法进行合并")
            return
        
        # 如果没有单帖主题，直接退出
        if not single_topics:
            print("\n✅ 没有需要合并的单帖主题")
            return
        
        # 统计结果
        merge_results = []
        merged_count = 0
        skipped_count = 0
        
        # 逐个处理单帖主题
        for source_theme in single_topics:
            print(f"\n{'='*60}")
            print(f"处理主题: {source_theme}")
            
            # 获取主题内容
            posts = get_posts_for_topic(conn, source_theme)
            comments = get_comments_for_topic(conn, source_theme)
            
            # 构建内容摘要
            content_parts = []
            for post in posts[:2]:
                content_parts.append(f"帖子标题: {post['title']}")
                if post['content']:
                    content_parts.append(f"帖子内容: {post['content'][:100]}...")
            
            for comment in comments[:3]:
                content_parts.append(f"评论: {comment[:50]}...")
            
            source_content = "\n".join(content_parts)
            
            print(f"相关帖子数: {len(posts)}")
            print(f"相关评论数: {len(comments)}")
            
            # 进行匹配
            if use_api:
                result = call_deepseek_match(source_theme, source_content, multi_topics)
            else:
                result = simulate_merge(source_theme, multi_topics)
            
            if result:
                matched_topic = result.get("matched_topic", "不合并")
                confidence = result.get("confidence", 0.0)
                reason = result.get("reason", "")
                
                print(f"匹配结果: {matched_topic}")
                print(f"置信度: {confidence:.2f}")
                print(f"理由: {reason}")
                
                # 记录结果
                merge_results.append({
                    "source_theme": source_theme,
                    "matched_topic": matched_topic,
                    "confidence": confidence,
                    "reason": reason
                })
                
                # 如果置信度足够高，进行合并
                if matched_topic != "不合并" and confidence >= MERGE_CONFIDENCE_THRESHOLD:
                    merge_topics(conn, source_theme, matched_topic)
                    merged_count += 1
                else:
                    print(f"警告: 跳过合并（置信度不足或选择不合并）")
                    skipped_count += 1
            else:
                print(f"错误: 匹配失败，跳过此主题")
                skipped_count += 1
        
        # 输出统计结果
        print(f"\n{'='*60}")
        print("合并统计:")
        print(f"  处理的单帖主题: {len(single_topics)}")
        print(f"  成功合并: {merged_count}")
        print(f"  跳过/不合并: {skipped_count}")
        
        # 输出合并详情
        if merge_results:
            print("\n合并详情:")
            for res in merge_results:
                status = "OK" if res['matched_topic'] != "不合并" and res['confidence'] >= MERGE_CONFIDENCE_THRESHOLD else "--"
                print(f"  [{status}] {res['source_theme']} -> {res['matched_topic']} (置信度: {res['confidence']:.2f})")
        
        # 删除没有帖子的主题
        delete_empty_topics(conn)
    
    finally:
        close_conn(conn)
    
    print("\n===== 主题合并脚本结束 =====")


def delete_empty_topics(conn):
    """
    删除没有帖子的主题（同时清理 posts 和 theme_bertopic 表）
    """
    with conn.cursor() as cursor:
        # 获取所有主题及其帖子数量
        cursor.execute("""
            SELECT t.theme, COUNT(DISTINCT p.post_id) as post_count
            FROM theme_bertopic t
            LEFT JOIN posts p ON t.theme = p.bertopic_theme
            GROUP BY t.theme
            HAVING COUNT(DISTINCT p.post_id) = 0
        """)
        empty_topics = cursor.fetchall()
        
        if empty_topics:
            print(f"\n删除空主题 ({len(empty_topics)}个):")
            deleted_count = 0
            for row in empty_topics:
                theme = row[0]
                
                # 删除 theme_bertopic 表中的空主题
                cursor.execute("""
                    DELETE FROM theme_bertopic
                    WHERE theme = %s
                """, (theme,))
                
                deleted_count += 1
                if deleted_count <= 20:  # 只显示前20个
                    print(f"  删除主题: {theme}")
            
            if deleted_count > 20:
                print(f"  ... 还有 {deleted_count - 20} 个空主题已删除")
            
            conn.commit()
            print(f"已删除 {deleted_count} 个空主题")
        else:
            print("\n没有需要删除的空主题")


if __name__ == "__main__":
    import sys
    
    # 检查是否使用 API（默认使用，加 --simulate 参数则使用模拟模式）
    use_api = "--simulate" not in sys.argv
    
    if not use_api:
        print("注意: 使用模拟模式进行主题匹配")
    
    main(use_api=use_api)
