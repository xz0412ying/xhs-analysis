# -*- coding: utf-8 -*-
import re
import time
import warnings

import pymysql
import pandas as pd
import matplotlib.pyplot as plt
import jieba
import gensim
from gensim import corpora
from gensim.models import LdaModel

warnings.filterwarnings("ignore")

# =========================
# 1. 基础配置
# =========================
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4"
}

BATCH_SIZE = 1000          # 每批读取多少条
TOPIC_MIN = 2              # 最小主题数
TOPIC_MAX = 20             # 最大主题数
PASSES = 10                # LDA训练轮数，太大容易慢
NUM_WORDS = 10             # 每个主题输出关键词数量

STOPWORDS_FILE = "stopwords.txt"


# =========================
# 2. 停用词
# =========================
def get_default_stopwords():
    """如果没有 stopwords.txt，就使用内置停用词"""
    return {
        "的", "了", "和", "是", "就", "都", "而", "及", "与", "着", "或", "一个",
        "没有", "我们", "你们", "他们", "她们", "它们",
        "我", "你", "他", "她", "它", "这", "那", "这些", "那些",
        "啊", "呀", "吗", "呢", "吧", "哦", "哈", "哇",
        "被", "把", "让", "给", "在", "对", "向", "从", "到", "中", "上", "下",
        "也", "还", "又", "很", "太", "更", "最", "非常", "真的",
        "一个", "一种", "一些", "这个", "那个", "这样", "那样",
        "可以", "不能", "不会", "不是", "就是", "还是", "因为", "所以",
        "然后", "如果", "但是", "不过", "已经", "觉得", "感觉",
        "自己", "别人", "大家", "东西", "问题", "事情",
        "，", "。", "！", "？", "；", "：", "“", "”", "‘", "’",
        ",", ".", "!", "?", ";", ":", "(", ")", "[", "]", "{", "}", "/", "\\",
        "-", "_", "—", "=", "+", "*", "&", "^", "%", "$", "#", "@", "~", "`",
        "nbsp", "展开", "收起"
    }


def load_stopwords(filepath=STOPWORDS_FILE):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            stopwords = set(line.strip() for line in f if line.strip())
        print(f"已加载停用词表：{filepath}，共 {len(stopwords)} 个词")
        return stopwords
    except FileNotFoundError:
        stopwords = get_default_stopwords()
        print(f"未找到 {filepath}，将使用内置停用词，共 {len(stopwords)} 个词")
        return stopwords


STOPWORDS = load_stopwords()


# =========================
# 3. jieba 初始化（只做一次）
# =========================
def init_jieba():
    print("初始化 jieba 分词器...")
    start = time.time()
    jieba.initialize()
    # 预热一次，避免后面循环里重复加载
    list(jieba.cut("初始化分词器"))
    end = time.time()
    print(f"jieba 初始化完成，耗时 {end - start:.2f} 秒")


# =========================
# 4. 数据库连接
# =========================
def get_connection():
    return pymysql.connect(**DB_CONFIG)


def fetch_data_batch(batch_size=1000, offset=0):
    conn = get_connection()
    try:
        query = f"""
        SELECT p.title, p.content, c.comment_content
        FROM posts p
        LEFT JOIN comments c ON p.post_id = c.post_id
        LIMIT {batch_size} OFFSET {offset};
        """
        data = pd.read_sql(query, conn)
        return data
    finally:
        conn.close()


def fetch_all_data(batch_size=1000):
    offset = 0
    all_data = []
    batch_index = 1
    total_rows = 0

    print("开始分批读取数据库数据...")

    while True:
        print(f"正在读取第 {batch_index} 批，OFFSET={offset} ...")
        data = fetch_data_batch(batch_size=batch_size, offset=offset)

        if data.empty:
            print("没有更多数据了，读取结束。")
            break

        rows = len(data)
        total_rows += rows
        print(f"第 {batch_index} 批读取完成，共 {rows} 条。累计 {total_rows} 条。")

        all_data.append(data)
        offset += batch_size
        batch_index += 1

    if not all_data:
        return pd.DataFrame(columns=["title", "content", "comment_content"])

    result = pd.concat(all_data, ignore_index=True)
    print(f"全部数据读取完成，总条数：{len(result)}")
    return result


# =========================
# 5. 文本预处理
# =========================
def preprocess(text):
    text = str(text).strip()

    if not text:
        return []

    # 只保留中文
    text = re.sub(r"[^\u4e00-\u9fa5]", " ", text)

    # 分词
    words = jieba.cut(text)

    # 过滤
    cleaned_words = []
    for w in words:
        w = w.strip()
        if not w:
            continue
        if w in STOPWORDS:
            continue
        if len(w) <= 1:   # 去掉单字
            continue
        cleaned_words.append(w)

    return cleaned_words


def prepare_text_data(data):
    if data.empty:
        return []

    data["title"] = data["title"].fillna("").astype(str)
    data["content"] = data["content"].fillna("").astype(str)
    data["comment_content"] = data["comment_content"].fillna("").astype(str)

    texts = data["title"] + " " + data["content"] + " " + data["comment_content"]

    cleaned_texts = []
    total = len(texts)

    print("开始进行文本预处理...")
    start_time = time.time()

    for idx, text in enumerate(texts, start=1):
        cleaned = preprocess(text)
        if cleaned:  # 空文本不加入
            cleaned_texts.append(cleaned)

        if idx % 100 == 0 or idx == total:
            print(f"已处理 {idx}/{total} 条文本")

    end_time = time.time()
    print(f"文本预处理完成，得到有效文本 {len(cleaned_texts)} 条，耗时 {end_time - start_time:.2f} 秒。")

    return cleaned_texts


# =========================
# 6. LDA 训练与评估
# =========================
def build_dictionary_and_corpus(cleaned_texts):
    print("构建词典和语料...")
    dictionary = corpora.Dictionary(cleaned_texts)

    # 过滤极端词
    dictionary.filter_extremes(no_below=3, no_above=0.5)

    corpus = [dictionary.doc2bow(text) for text in cleaned_texts]

    print(f"词典大小：{len(dictionary)}")
    print(f"语料条数：{len(corpus)}")
    return dictionary, corpus


def compute_lda_model(k, corpus, dictionary, cleaned_texts):
    print(f"\n==============================")
    print(f"正在计算 {k} 个主题...")
    print(f"==============================")

    start = time.time()

    lda_model = LdaModel(
        corpus=corpus,
        num_topics=k,
        id2word=dictionary,
        passes=PASSES,
        random_state=42,
        eval_every=None
    )

    perplexity = lda_model.log_perplexity(corpus)

    coherence_model = gensim.models.CoherenceModel(
        model=lda_model,
        texts=cleaned_texts,
        dictionary=dictionary,
        coherence='c_v'
    )
    coherence = coherence_model.get_coherence()

    end = time.time()

    print(f"主题数 {k} 的困惑度 Perplexity: {perplexity}")
    print(f"主题数 {k} 的一致性 Coherence: {coherence}")
    print(f"耗时：{end - start:.2f} 秒")

    print(f"\n主题数 {k} 的主题内容：")
    topics = lda_model.print_topics(num_words=NUM_WORDS)
    for topic_id, topic in topics:
        print(f"Topic {topic_id}: {topic}")

    return perplexity, coherence, lda_model


def select_best_k(cleaned_texts):
    dictionary, corpus = build_dictionary_and_corpus(cleaned_texts)

    perplexities = []
    coherences = []
    lda_models = {}

    for k in range(TOPIC_MIN, TOPIC_MAX + 1):
        perplexity, coherence, lda_model = compute_lda_model(
            k, corpus, dictionary, cleaned_texts
        )
        perplexities.append(perplexity)
        coherences.append(coherence)
        lda_models[k] = lda_model

    # 画图
    save_metric_curve(perplexities, coherences)

    # 一致性最大对应的主题数
    best_k = coherences.index(max(coherences)) + TOPIC_MIN
    best_model = lda_models[best_k]

    print(f"\n最佳主题数为：{best_k}")
    print(f"最佳一致性：{max(coherences)}")

    return best_k, dictionary, corpus, best_model, perplexities, coherences


def save_metric_curve(perplexities, coherences):
    ks = list(range(TOPIC_MIN, TOPIC_MAX + 1))

    plt.figure(figsize=(12, 5))

    plt.subplot(1, 2, 1)
    plt.plot(ks, perplexities, marker='o')
    plt.title("Perplexity vs Number of Topics")
    plt.xlabel("Number of Topics")
    plt.ylabel("Perplexity")

    plt.subplot(1, 2, 2)
    plt.plot(ks, coherences, marker='o')
    plt.title("Coherence vs Number of Topics")
    plt.xlabel("Number of Topics")
    plt.ylabel("Coherence")

    plt.tight_layout()
    plt.savefig("lda_perplexity_coherence_curve.png", dpi=300)
    plt.close()

    print("已保存指标曲线图：lda_perplexity_coherence_curve.png")


def train_lda(best_k, dictionary, corpus):
    print(f"\n使用最佳主题数 {best_k} 重新训练最终 LDA 模型...")
    lda_model = LdaModel(
        corpus=corpus,
        num_topics=best_k,
        id2word=dictionary,
        passes=PASSES,
        random_state=42,
        eval_every=None
    )
    return lda_model


def extract_topics(lda_model, num_words=10):
    return lda_model.print_topics(num_words=num_words)


def export_topics_to_excel(topics):
    rows = []
    for topic_id, keywords in topics:
        rows.append({
            "Topic": topic_id,
            "Keywords": keywords
        })

    topics_df = pd.DataFrame(rows)
    topics_df.to_excel("lda_topics.xlsx", index=False)
    print("已导出主题结果到：lda_topics.xlsx")


# =========================
# 7. 主程序
# =========================
if __name__ == "__main__":
    total_start = time.time()

    print("===== LDA 主题分析开始 =====")

    # 初始化分词器
    init_jieba()

    # 读取全部数据
    data = fetch_all_data(batch_size=BATCH_SIZE)

    if data.empty:
        print("数据库中没有可用数据，程序结束。")
        exit()

    # 文本预处理
    cleaned_texts = prepare_text_data(data)

    if not cleaned_texts:
        print("预处理后没有有效文本，程序结束。")
        exit()

    # 选择最佳主题数
    best_k, dictionary, corpus, best_model, perplexities, coherences = select_best_k(cleaned_texts)

    # 用最佳主题数重新训练最终模型
    final_lda_model = train_lda(best_k, dictionary, corpus)

    # 提取主题
    final_topics = extract_topics(final_lda_model, num_words=NUM_WORDS)

    print("\n===== 最终主题结果 =====")
    for topic_id, topic in final_topics:
        print(f"Topic {topic_id}: {topic}")

    # 导出 Excel
    export_topics_to_excel(final_topics)

    total_end = time.time()
    print(f"\n===== 全部完成，总耗时 {total_end - total_start:.2f} 秒 =====")