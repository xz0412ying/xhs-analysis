import pymysql
from pymysql import Error
import traceback

class Database:
    def __init__(self):
        self.host = 'localhost'
        self.user = 'root'  # 请根据实际情况修改
        self.password = '123456'  # 请根据实际情况修改
        self.database = 'xiaohongshu_analysis'
        self.connection = None
        self.cursor = None
    
    def connect(self):
        """连接到数据库"""
        try:
            print(f"尝试连接到数据库: {self.database} @ {self.host}")
            print(f"用户名: {self.user}")
            print(f"密码长度: {len(self.password)} 字符")
            
            self.connection = pymysql.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database,
                port=3306,
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            
            print("成功连接到数据库")
            # pymysql没有get_server_info()方法，我们使用ping()方法来测试连接
            self.connection.ping()
            print("数据库连接测试成功")
            self.cursor = self.connection.cursor()
            self.create_tables()
        except Error as e:
            print(f"连接数据库失败: {e}")
            print(f"错误代码: {e.errno}")
            print(f"SQL状态: {e.sqlstate}")
            print("详细错误信息:")
            traceback.print_exc()
        except Exception as e:
            print(f"发生未知错误: {e}")
            traceback.print_exc()
    
    def create_tables(self):
        """创建必要的表（如果不存在）"""
        try:
            # 检查表是否存在
            self.cursor.execute("SHOW TABLES LIKE 'posts'")
            posts_table_exists = self.cursor.fetchone() is not None
            
            self.cursor.execute("SHOW TABLES LIKE 'comments'")
            comments_table_exists = self.cursor.fetchone() is not None
            
            if posts_table_exists and comments_table_exists:
                print("表已存在，跳过创建")
            else:
                print("表不存在，需要创建")
        except Error as e:
            print(f"检查表失败: {e}")
    
    def insert_post(self, url, title, time_mark):
        """插入帖子数据"""
        try:
            # 根据用户的数据库结构，posts表的字段是post_id、title、publish_time、content
            # 我们将url作为content字段的值，time_mark作为publish_time字段的值
            query = "INSERT INTO posts (title, publish_time, content) VALUES (%s, %s, %s)"
            self.cursor.execute(query, (title, time_mark, url))
            self.connection.commit()
            return self.cursor.lastrowid
        except Error as e:
            print(f"插入帖子失败: {e}")
            return None
    
    def insert_comment(self, post_id, content, likes):
        """插入评论数据"""
        try:
            # 根据用户的数据库结构，comments表的字段是comment_id、post_id、comment_content、like_count
            query = "INSERT INTO comments (post_id, comment_content, like_count) VALUES (%s, %s, %s)"
            self.cursor.execute(query, (post_id, content, likes))
            self.connection.commit()
        except Error as e:
            print(f"插入评论失败: {e}")
    
    def close(self):
        """关闭数据库连接"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            try:
                self.connection.close()
                print("数据库连接已关闭")
            except Exception as e:
                print(f"关闭数据库连接时发生错误: {e}")

# 测试数据库连接
def test_db_connection():
    db = Database()
    db.connect()
    db.close()

if __name__ == "__main__":
    test_db_connection()
