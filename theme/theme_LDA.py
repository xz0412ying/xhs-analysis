import pymysql
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from gensim import corpora
from gensim.models import LdaModel
import gensim
import concurrent.futures

# 1. 数据库连接设置
def get_connection():
    return pymysql.connect(
        host='localhost',  # 根据你的数据库地址进行修改
        user='root',  # 根据你的数据库用户名进行修改
        password='123456',  # 根据你的数据库密码进行修改
        database='xiaohongshu_analysis',  # 根据你的数据库名称进行修改
        charset='utf8mb4'
    )

# 2. 从数据库获取数据
def fetch_data():
    conn = get_connection()
    query = """
    SELECT p.title, p.content, c.comment_content
    FROM posts p
    LEFT JOIN comments c ON p.post_id = c.post_id;
    """
    data = pd.read_sql(query, conn)
    conn.close()
    return data

# 3. 数据预处理：清洗文本
def preprocess(text):
    text = str(text)  # 确保转换为字符串类型
    text = text.lower()  # 小写化
    return text.split()  # 按空格分词（你可以用jieba进行中文分词）

# 4. 将帖子标题+内容与评论合并
def prepare_text_data(data):
    # 确保文本数据为字符串并填充NaN值
    data['title'] = data['title'].fillna('').astype(str)
    data['content'] = data['content'].fillna('').astype(str)
    data['comment_content'] = data['comment_content'].fillna('').astype(str)

    # 合并标题、内容和评论
    texts = data['title'] + ' ' + data['content'] + ' ' + data['comment_content']
    cleaned_texts = [preprocess(text) for text in texts]
    return cleaned_texts

# 5. 计算LDA模型困惑度和一致性
def compute_lda_model(k, corpus, dictionary, cleaned_texts):
    print(f"Processing {k} topics...")
    lda_model = LdaModel(corpus, num_topics=k, id2word=dictionary, passes=15)
    
    # 获取Perplexity
    perplexity = lda_model.log_perplexity(corpus)
    # 获取Coherence
    coherence_model = gensim.models.CoherenceModel(model=lda_model, corpus=corpus, texts=cleaned_texts, coherence='c_v')
    coherence = coherence_model.get_coherence()
    
    print(f"Perplexity for {k} topics: {perplexity}")  # 实时输出困惑度
    return perplexity, coherence

# 6. 使用并行计算不同主题数的LDA模型
def select_best_k(cleaned_texts):
    dictionary = corpora.Dictionary(cleaned_texts)
    corpus = [dictionary.doc2bow(text) for text in cleaned_texts]
    
    perplexities = []
    coherences = []
    
    # 使用并行计算
    with concurrent.futures.ProcessPoolExecutor() as executor:
        results = [executor.submit(compute_lda_model, k, corpus, dictionary, cleaned_texts) for k in range(2, 21)]
        for future in concurrent.futures.as_completed(results):
            perplexity, coherence = future.result()
            perplexities.append(perplexity)
            coherences.append(coherence)

    # 绘制困惑度和一致性曲线图并保存
    plt.figure(figsize=(10, 5))
    
    # 困惑度曲线
    plt.subplot(1, 2, 1)
    plt.plot(range(2, 21), perplexities, label='Perplexity', color='red')
    plt.title('Perplexity vs Number of Topics')
    plt.xlabel('Number of Topics')
    plt.ylabel('Perplexity')

    # 一致性曲线
    plt.subplot(1, 2, 2)
    plt.plot(range(2, 21), coherences, label='Coherence', color='blue')
    plt.title('Coherence vs Number of Topics')
    plt.xlabel('Number of Topics')
    plt.ylabel('Coherence')

    plt.tight_layout()
    plt.savefig('lda_perplexity_coherence_curve.png')  # 保存图像
    plt.close()  # 关闭图像，以免多次打开

    # 选择最佳主题数
    best_k = coherences.index(max(coherences)) + 2  # 因为是从2开始的
    print(f"Best number of topics: {best_k}")
    return best_k, dictionary, corpus

# 7. 使用最优主题数训练LDA模型
def train_lda(best_k, dictionary, corpus):
    print(f"Training LDA model with {best_k} topics...")  # 输出当前训练的主题数
    lda_model = LdaModel(corpus, num_topics=best_k, id2word=dictionary, passes=15)
    return lda_model

# 8. 提取主题关键词
def extract_topics(lda_model, num_words=10):
    topics = lda_model.print_topics(num_words=num_words)
    return topics

# 9. 导出主题关键词到Excel
def export_topics_to_excel(topics):
    topics_df = pd.DataFrame(topics, columns=['Topic', 'Keywords'])
    topics_df.to_excel('lda_topics.xlsx', index=False)
    print("Topics exported to lda_topics.xlsx")

# 主程序执行
if __name__ == "__main__":
    # 1. 获取数据
    print("Fetching data from the database...")
    data = fetch_data()

    # 2. 数据预处理
    print("Preparing text data...")
    cleaned_texts = prepare_text_data(data)

    # 3. 选择最佳主题数 K
    best_k, dictionary, corpus = select_best_k(cleaned_texts)

    # 4. 使用最优 K 训练LDA模型
    lda_model = train_lda(best_k, dictionary, corpus)

    # 5. 提取主题关键词
    topics = extract_topics(lda_model)

    # 6. 导出主题到Excel
    export_topics_to_excel(topics)