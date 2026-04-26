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

# 检查comments表结构
print('Comments table structure:')
cursor.execute('DESCRIBE comments')
for row in cursor.fetchall():
    print(row)

# 检查posts表结构
print('\nPosts table structure:')
cursor.execute('DESCRIBE posts')
for row in cursor.fetchall():
    print(row)

# 检查comments表中的数据
print('\nComments table data sample:')
cursor.execute('SELECT * FROM comments LIMIT 5')
for row in cursor.fetchall():
    print(row)

# 检查情感和态度数据
print('\nSentiment data sample:')
cursor.execute('SELECT sentiment_label, COUNT(*) FROM comments WHERE sentiment_label IS NOT NULL GROUP BY sentiment_label')
for row in cursor.fetchall():
    print(row)

print('\nAttitude data sample:')
cursor.execute('SELECT attitude_type, COUNT(*) FROM comments WHERE attitude_type IS NOT NULL GROUP BY attitude_type')
for row in cursor.fetchall():
    print(row)

# 检查时间数据
print('\nComment time data sample:')
cursor.execute('SELECT comment_time FROM comments WHERE comment_time IS NOT NULL LIMIT 5')
for row in cursor.fetchall():
    print(row)

# 关闭连接
cursor.close()
conn.close()