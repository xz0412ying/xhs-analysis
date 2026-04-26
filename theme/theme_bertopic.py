# -*- coding: utf-8 -*-
import re
import math
import warnings
import pymysql
import pandas as pd
import jieba
import matplotlib.pyplot as plt

from bertopic import BERTopic
from sentence_transformers import SentenceTransformer
from sklearn.feature_extraction.text import CountVectorizer

from gensim.corpora import Dictionary
from gensim.models import CoherenceModel

warnings.filterwarnings("ignore")

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

# 中文/多语言句向量模型
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

# 输出文件
BEST_OUTPUT_FILE = "bertopic_topics_best.xlsx"
TUNING_SUMMARY_FILE = "bertopic_tuning_summary.xlsx"
TUNING_PLOT_FILE = "bertopic_tuning_curves.png"

# 向量器参数
NGRAM_RANGE = (1, 2)

# 每个主题保留的关键词数量
TOP_N_WORDS = 10

# 候选 min_topic_size 因子（围绕“评论数/帖子数”的基准值扫描）
MTS_FACTORS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.50, 0.60, 0.70, 0.80]

# 最小候选值保护
MIN_MTS_FLOOR = 5

# 综合评分权重
W_COHERENCE = 0.10
W_DIVERSITY = 0.25
W_COUNT = 0.25
W_OUTLIER = 0.40


# =========================
# 2. 停用词
# =========================
def get_stopwords():
    return {
        "的", "了", "和", "是", "就", "都", "而", "及", "与", "着", "或",
        "一个", "没有", "我们", "你们", "他们", "她们", "它们",
        "我", "你", "他", "她", "它", "这", "那", "这些", "那些",
        "啊", "呀", "吗", "呢", "吧", "哦", "哈", "哇",
        "被", "把", "让", "给", "在", "对", "向", "从", "到", "中", "上", "下",
        "也", "还", "又", "很", "太", "更", "最", "非常", "真的",
        "这个", "那个", "这样", "那样", "可以", "不能", "不会", "不是",
        "就是", "还是", "因为", "所以", "然后", "如果", "但是", "不过",
        "已经", "觉得", "感觉", "自己", "别人", "大家", "东西", "问题",
        "事情", "展开", "收起"
    }

STOPWORDS = get_stopwords()


# =========================
# 3. 数据库连接
# =========================
def get_connection():
    return pymysql.connect(**DB_CONFIG)


# =========================
# 4. 读取统计信息
# =========================
def get_post_count():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM posts")
            post_count = cursor.fetchone()[0]
        return post_count
    finally:
        conn.close()


def get_comment_count():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*)
                FROM comments
                WHERE comment_content IS NOT NULL
                  AND comment_content <> ''
            """)
            comment_count = cursor.fetchone()[0]
        return comment_count
    finally:
        conn.close()


def fetch_data():
    conn = get_connection()
    try:
        query = """
        SELECT p.title, p.content, c.comment_content
        FROM posts p
        LEFT JOIN comments c ON p.post_id = c.post_id
        WHERE c.comment_content IS NOT NULL
          AND c.comment_content <> '';
        """
        data = pd.read_sql(query, conn)
        return data
    finally:
        conn.close()


# =========================
# 5. 文本预处理
# =========================
def preprocess_to_tokens(text):
    text = str(text).strip()

    if not text:
        return []

    # 仅保留中文
    text = re.sub(r"[^\u4e00-\u9fa5]", " ", text)

    words = jieba.lcut(text)

    words = [
        w.strip() for w in words
        if w.strip()
        and w.strip() not in STOPWORDS
        and len(w.strip()) > 1
    ]

    return words


def prepare_text_data(data):
    data["title"] = data["title"].fillna("").astype(str)
    data["content"] = data["content"].fillna("").astype(str)
    data["comment_content"] = data["comment_content"].fillna("").astype(str)

    texts = data["title"] + " " + data["content"] + " " + data["comment_content"]

    tokenized_texts = []
    cleaned_texts = []
    total = len(texts)

    print("开始文本预处理...")
    for idx, text in enumerate(texts, start=1):
        tokens = preprocess_to_tokens(text)
        if tokens:
            tokenized_texts.append(tokens)
            cleaned_texts.append(" ".join(tokens))

        if idx % 100 == 0 or idx == total:
            print(f"已处理 {idx}/{total} 条")

    print(f"文本预处理完成，有效文本数：{len(cleaned_texts)}")
    return tokenized_texts, cleaned_texts


# =========================
# 6. 调参候选集生成
# =========================
def auto_base_min_topic_size(comment_count, post_count):
    """
    当前脚本里的基准：评论数 / 帖子数
    """
    if post_count <= 0:
        return 5
    return max(MIN_MTS_FLOOR, math.ceil(comment_count / post_count))


def build_candidate_mts(base_mts):
    """
    围绕基准值构造候选 min_topic_size
    """
    candidates = []
    for factor in MTS_FACTORS:
        mts = max(MIN_MTS_FLOOR, round(base_mts * factor))
        candidates.append(mts)

    # 去重并排序
    candidates = sorted(list(set(candidates)))
    return candidates


def get_target_topic_count(post_count):
    """
    用帖子数量估一个“合理主题数”
    这里取帖子数的 1/2，最小为 5
    """
    return max(5, round(post_count * 0.5))


# =========================
# 7. 评价指标
# =========================
def topic_diversity(topic_word_lists, topk=10):
    words = []
    for topic_words in topic_word_lists:
        words.extend(topic_words[:topk])

    if not words:
        return 0.0

    return len(set(words)) / len(words)


def compute_topic_coherence(topic_word_lists, tokenized_texts):
    """
    使用 c_v 一致性
    """
    # 保证 topics 是 list[list[str]]
    clean_topics = []
    for topic in topic_word_lists:
        if not isinstance(topic, list):
            continue

        clean_topic = []
        for w in topic:
            if w is None:
                continue
            w = str(w).strip()
            if w:
                clean_topic.append(w)

        if len(clean_topic) >= 2:
            clean_topics.append(clean_topic)

    if not clean_topics:
        return 0.0

    dictionary = Dictionary(tokenized_texts)
    if len(dictionary) == 0:
        return 0.0

    try:
        cm = CoherenceModel(
            topics=clean_topics,
            texts=tokenized_texts,
            dictionary=dictionary,
            coherence="c_v"
        )
        return cm.get_coherence()
    except Exception as e:
        print(f"⚠️ coherence 计算失败：{e}")
        print(f"⚠️ clean_topics 示例：{clean_topics[:3]}")
        return 0.0


def extract_topic_word_lists(topic_model, topic_info, topn=10):
    """
    只取有效主题（不含 -1）
    返回 [['词1','词2',...], ['词1',...], ...]
    """
    topic_word_lists = []

    valid_rows = topic_info[topic_info["Topic"] != -1]
    for _, row in valid_rows.iterrows():
        topic_id = row["Topic"]
        topic_words = topic_model.get_topic(topic_id)
        if topic_words:
            words = [word for word, score in topic_words[:topn]]
            if words:
                topic_word_lists.append(words)

    return topic_word_lists


def compute_count_score(num_topics, target_topic_count):
    """
    主题数量越接近目标值，得分越高
    """
    return 1.0 / (1.0 + abs(num_topics - target_topic_count))


# =========================
# 8. 单次 BERTopic 训练与评估
# =========================
def run_single_bertopic(cleaned_texts, tokenized_texts, embeddings, vectorizer_model,
                        embedding_model, min_topic_size, target_topic_count):
    print("\n" + "=" * 70)
    print(f"开始评估 min_topic_size = {min_topic_size}")

    topic_model = BERTopic(
        embedding_model=embedding_model,
        vectorizer_model=vectorizer_model,
        language="multilingual",
        min_topic_size=min_topic_size,
        calculate_probabilities=False,
        verbose=False
    )

    topics, probs = topic_model.fit_transform(cleaned_texts, embeddings)
    topic_info = topic_model.get_topic_info()

    total_docs = len(cleaned_texts)

    # 有效主题数（不算 -1）
    num_topics = len(topic_info[topic_info["Topic"] != -1])

    # 离群比例
    outlier_count = 0
    if -1 in topic_info["Topic"].values:
        outlier_count = int(topic_info.loc[topic_info["Topic"] == -1, "Count"].iloc[0])

    outlier_ratio = outlier_count / total_docs if total_docs > 0 else 1.0

    # 提取主题词
    topic_word_lists = extract_topic_word_lists(topic_model, topic_info, topn=TOP_N_WORDS)

    # 一致性
    coherence_c_v = compute_topic_coherence(topic_word_lists, tokenized_texts)

    # 差异度
    diversity = topic_diversity(topic_word_lists, topk=TOP_N_WORDS)

    # 数量合理性
    count_score = compute_count_score(num_topics, target_topic_count)

    # 综合分数
    final_score = (
        W_COHERENCE * coherence_c_v
        + W_DIVERSITY * diversity
        + W_COUNT * count_score
        + W_OUTLIER * (1 - outlier_ratio)
    )

    # 对离群比例过高的情况做额外惩罚
    if outlier_ratio > 0.25:
        final_score -= 0.10
    if outlier_ratio > 0.35:
        final_score -= 0.15

    print(f"有效主题数 num_topics = {num_topics}")
    print(f"离群比例 outlier_ratio = {outlier_ratio:.4f}")
    print(f"一致性 coherence_c_v = {coherence_c_v:.4f}")
    print(f"差异度 topic_diversity = {diversity:.4f}")
    print(f"主题数量得分 count_score = {count_score:.4f}")
    print(f"综合得分 final_score = {final_score:.4f}")

    return {
        "min_topic_size": min_topic_size,
        "num_topics": num_topics,
        "outlier_ratio": outlier_ratio,
        "coherence_c_v": coherence_c_v,
        "topic_diversity": diversity,
        "count_score": count_score,
        "final_score": final_score
    }, topic_model, topic_info


# =========================
# 9. 导出最优主题
# =========================
def export_topics_to_excel(topic_model, topic_info, output_file):
    rows = []

    for _, row in topic_info.iterrows():
        topic_id = row["Topic"]
        count = row["Count"]
        name = row["Name"]

        if topic_id == -1:
            keywords = "离群主题"
        else:
            topic_words = topic_model.get_topic(topic_id)
            if topic_words:
                keywords = ", ".join([word for word, score in topic_words[:10]])
            else:
                keywords = ""

        rows.append({
            "Topic": topic_id,
            "Count": count,
            "Name": name,
            "Keywords": keywords
        })

    df = pd.DataFrame(rows)
    df.to_excel(output_file, index=False)
    print(f"最优主题结果已导出到：{output_file}")


# =========================
# 10. 绘图
# =========================
def plot_tuning_curves(summary_df, target_topic_count, output_file):
    x = summary_df["min_topic_size"]

    plt.figure(figsize=(14, 10))

    # 图1：一致性
    plt.subplot(2, 2, 1)
    plt.plot(x, summary_df["coherence_c_v"], marker="o")
    plt.title("Coherence (c_v) vs min_topic_size")
    plt.xlabel("min_topic_size")
    plt.ylabel("Coherence (c_v)")

    # 图2：有效主题数
    plt.subplot(2, 2, 2)
    plt.plot(x, summary_df["num_topics"], marker="o")
    plt.axhline(y=target_topic_count, linestyle="--")
    plt.title("Number of Topics vs min_topic_size")
    plt.xlabel("min_topic_size")
    plt.ylabel("Number of Valid Topics")

    # 图3：离群比例
    plt.subplot(2, 2, 3)
    plt.plot(x, summary_df["outlier_ratio"], marker="o")
    plt.title("Outlier Ratio vs min_topic_size")
    plt.xlabel("min_topic_size")
    plt.ylabel("Outlier Ratio")

    # 图4：综合得分
    plt.subplot(2, 2, 4)
    plt.plot(x, summary_df["final_score"], marker="o")
    plt.title("Final Score vs min_topic_size")
    plt.xlabel("min_topic_size")
    plt.ylabel("Final Score")

    plt.tight_layout()
    plt.savefig(output_file, dpi=300)
    plt.close()

    print(f"调参曲线图已保存到：{output_file}")


# =========================
# 11. 主程序
# =========================
if __name__ == "__main__":
    print("===== BERTopic 自动调参开始 =====")

    post_count = get_post_count()
    comment_count = get_comment_count()

    print(f"帖子数：{post_count}")
    print(f"评论数：{comment_count}")

    base_mts = auto_base_min_topic_size(comment_count, post_count)
    target_topic_count = get_target_topic_count(post_count)

    print(f"基准 min_topic_size（评论数/帖子数）= {base_mts}")
    print(f"目标主题数（帖子数*0.5）= {target_topic_count}")

    candidate_mts = build_candidate_mts(base_mts)
    print(f"候选 min_topic_size 列表：{candidate_mts}")

    print("读取数据库数据...")
    data = fetch_data()

    if data.empty:
        print("数据库中没有可用评论数据，程序结束。")
        exit()

    print(f"读取完成，共 {len(data)} 条文本。")

    tokenized_texts, cleaned_texts = prepare_text_data(data)

    if not cleaned_texts:
        print("预处理后没有有效文本，程序结束。")
        exit()

    print("加载句向量模型...")
    embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print("统一生成文本向量（只做一次）...")
    embeddings = embedding_model.encode(
        cleaned_texts,
        show_progress_bar=True
    )

    print("构建向量器...")
    vectorizer_model = CountVectorizer(
        tokenizer=lambda x: x.split(),
        lowercase=False,
        ngram_range=NGRAM_RANGE
    )

    results = []
    best_score = -1
    best_mts = None
    best_topic_model = None
    best_topic_info = None

    for mts in candidate_mts:
        try:
            result_row, topic_model, topic_info = run_single_bertopic(
                cleaned_texts=cleaned_texts,
                tokenized_texts=tokenized_texts,
                embeddings=embeddings,
                vectorizer_model=vectorizer_model,
                embedding_model=embedding_model,
                min_topic_size=mts,
                target_topic_count=target_topic_count
            )

            results.append(result_row)

            if result_row["final_score"] > best_score:
                best_score = result_row["final_score"]
                best_mts = mts
                best_topic_model = topic_model
                best_topic_info = topic_info

        except Exception as e:
            print(f"min_topic_size={mts} 运行失败：{e}")
            results.append({
                "min_topic_size": mts,
                "num_topics": None,
                "outlier_ratio": None,
                "coherence_c_v": None,
                "topic_diversity": None,
                "count_score": None,
                "final_score": None
            })

    summary_df = pd.DataFrame(results)
    summary_df = summary_df.sort_values("min_topic_size").reset_index(drop=True)
    summary_df.to_excel(TUNING_SUMMARY_FILE, index=False)
    print(f"调参结果表已导出到：{TUNING_SUMMARY_FILE}")

    # 只对成功行画图
    plot_df = summary_df.dropna().copy()
    if not plot_df.empty:
        plot_tuning_curves(plot_df, target_topic_count, TUNING_PLOT_FILE)

    print("\n===== 自动调参完成 =====")
    print(f"最优 min_topic_size = {best_mts}")
    print(f"最优综合得分 = {best_score:.4f}")

    if best_topic_model is not None and best_topic_info is not None:
        print("\n最优主题信息预览：")
        print(best_topic_info.head(20))
        export_topics_to_excel(best_topic_model, best_topic_info, BEST_OUTPUT_FILE)

    print("===== BERTopic 自动调参结束 =====")