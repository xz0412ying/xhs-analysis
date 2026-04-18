import pymysql
import pandas as pd
from bertopic import BERTopic
from sentence_transformers import SentenceTransformer

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
    return text

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

# 5. 使用BERTopic提取主题
def extract_bertopic_topics(cleaned_texts):
    # 使用预训练的SentenceTransformer模型进行嵌入
    model = SentenceTransformer('paraphrase-MiniLM-L6-v2')  # 你可以根据需要选择其他模型
    
    # 转换文本为嵌入向量
    embeddings = model.encode(cleaned_texts, show_progress_bar=True)

    # 使用BERTopic进行主题提取
    topic_model = BERTopic(language="chinese")  # 根据数据语言选择（这里是中文）
    topics, probs = topic_model.fit_transform(cleaned_texts, embeddings)

    # 提取每个主题的关键词
    topic_info = topic_model.get_topic_info()
    topic_keywords = [topic_model.get_topic(i) for i in topic_info['Topic']]

    return topic_info, topic_keywords

# 6. 导出主题关键词到Excel
def export_topics_to_excel(topic_info, topic_keywords):
    # 将主题信息导出到DataFrame
    topics_df = pd.DataFrame(topic_info)
    topics_df['Keywords'] = topics_df['Topic'].apply(lambda x: ', '.join([word[0] for word in topic_keywords[x]]))
    
    # 导出到Excel文件
    topics_df.to_excel('bertopic_topics.xlsx', index=False)
    print("Topics exported to bertopic_topics.xlsx")

# 主程序执行
if __name__ == "__main__":
    # 1. 获取数据
    print("Fetching data from the database...")
    data = fetch_data()

    # 2. 数据预处理
    print("Preparing text data...")
    cleaned_texts = prepare_text_data(data)

    # 3. 使用BERTopic提取主题
    print("Extracting topics with BERTopic...")
    topic_info, topic_keywords = extract_bertopic_topics(cleaned_texts)

    # 4. 导出主题到Excel
    export_topics_to_excel(topic_info, topic_keywords)