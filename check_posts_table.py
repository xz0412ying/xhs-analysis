import pymysql

# 连接数据库
conn = pymysql.connect(
    host='127.0.0.1',
    port=3306,
    user='root',
    password='123456',
    database='xiaohongshu_analysis',
    charset='utf8mb4',
    cursorclass=pymysql.cursors.DictCursor
)

# 创建游标
cursor = conn.cursor()

# 检查posts表结构
print('Posts table structure:')
cursor.execute('DESCRIBE posts')
for row in cursor.fetchall():
    print(row)

# 检查posts表中的数据样本
print('\nPosts table data sample:')
cursor.execute('SELECT post_id, title, publish_time FROM posts LIMIT 5')
for row in cursor.fetchall():
    print(row)

# 检查publish_time字段的类型和格式
print('\nChecking publish_time field format:')
cursor.execute('SELECT publish_time FROM posts WHERE publish_time IS NOT NULL LIMIT 10')
for i, row in enumerate(cursor.fetchall()):
    print(f'Row {i+1}: {row["publish_time"]}, Type: {type(row["publish_time"])}')

# 关闭连接
cursor.close()
conn.close()