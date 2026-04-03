from flask import Flask, render_template, request, send_file, jsonify, redirect
import time
import os
import threading
import pandas as pd
from crawler.xiaohongshu_crawler import crawl_xiaohongshu_comments, save_comments_to_excel
from db import Database

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

# 存储爬取进度的全局变量
crawl_progress = {}

# 数据集目录
DATASET_DIR = os.path.join(os.getcwd(), 'dataset')

# 确保数据集目录存在
if not os.path.exists(DATASET_DIR):
    os.makedirs(DATASET_DIR)

@app.route('/')
def home():
    # 获取dataset目录中的Excel文件（原始数据文件）
    excel_files = get_excel_files()
    return render_template('index.html', excel_files=excel_files)

@app.route('/crawl', methods=['GET', 'POST'])
def crawl():
    if request.method == 'POST':
        # 获取用户输入的URL、标题、时间标记和文件名
        url = request.form.get('url')
        title = request.form.get('title')
        time_mark = request.form.get('time_mark')
        filename = request.form.get('filename')
        
        if not url:
            return render_template('index.html', error='请输入帖子URL', excel_files=get_excel_files())
        
        if not title:
            return render_template('index.html', error='请输入帖子标题', excel_files=get_excel_files())
        
        if not time_mark:
            return render_template('index.html', error='请输入时间标记', excel_files=get_excel_files())
        
        if not filename:
            return render_template('index.html', error='请输入Excel文件名', excel_files=get_excel_files())
        
        # 生成任务ID
        task_id = str(int(time.time()))
        
        # 初始化进度
        crawl_progress[task_id] = {
            'status': 'running',
            'progress': 0,
            'max_scrolls': 300,
            'current_scroll': 0,
            'comments': None,
            'excel_filename': None,
            'url': url,
            'title': title,
            'time_mark': time_mark,
            'filename': filename
        }
        
        # 启动爬取线程
        def crawl_task():
            db = None
            try:
                # 连接数据库
                db = Database()
                db.connect()
                
                # 插入帖子数据
                post_id = db.insert_post(url, title, time_mark)
                if not post_id:
                    crawl_progress[task_id]['status'] = 'error'
                    crawl_progress[task_id]['error'] = '插入帖子数据失败'
                    return
                
                # 定义进度回调函数
                def progress_callback(progress, max_scrolls):
                    crawl_progress[task_id]['progress'] = progress
                    crawl_progress[task_id]['current_scroll'] = int((progress / 100) * max_scrolls)
                
                # 爬取小红书评论
                comments = crawl_xiaohongshu_comments(url, progress_callback)
                # 清理文件名中的非法字符（Windows不允许的字符：< > : " / \ | ? *）
                import re
                cleaned_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
                # 在文件名前面添加时间标记
                filename_with_ext = f"{time_mark}_{cleaned_filename}.xlsx"
                # 保存为Excel文件
                excel_path = save_comments_to_excel(comments, filename_with_ext, title)
                
                # 插入评论数据
                for comment in comments:
                    db.insert_comment(post_id, comment['content'], comment['likes'])
                
                if not comments:
                    crawl_progress[task_id]['status'] = 'error'
                    crawl_progress[task_id]['error'] = '未爬取到任何评论'
                    return
                
                if not excel_path:
                    crawl_progress[task_id]['status'] = 'error'
                    crawl_progress[task_id]['error'] = '保存Excel文件失败'
                    return
                
                # 更新状态
                crawl_progress[task_id]['status'] = 'completed'
                crawl_progress[task_id]['comments'] = comments
                crawl_progress[task_id]['excel_filename'] = os.path.basename(excel_path)
                crawl_progress[task_id]['comment_count'] = len(comments)
            except Exception as e:
                crawl_progress[task_id]['status'] = 'error'
                crawl_progress[task_id]['error'] = str(e)
            finally:
                if db:
                    db.close()
        
        threading.Thread(target=crawl_task).start()
        
        # 重定向到进度页面
        return render_template('progress.html', task_id=task_id, url=url)
    
    return render_template('index.html', excel_files=get_excel_files())

@app.route('/progress/<task_id>')
def get_progress(task_id):
    if task_id in crawl_progress:
        return jsonify(crawl_progress[task_id])
    else:
        return jsonify({'status': 'not_found'})

@app.route('/result/<task_id>')
def result(task_id):
    if task_id in crawl_progress and crawl_progress[task_id]['status'] == 'completed':
        data = crawl_progress[task_id]
        return render_template('result.html', 
                           url=data['url'], 
                           title=data['title'], 
                           comment_count=data['comment_count'], 
                           preview_comments=data['comments'][:10],  # 显示10条评论
                           excel_filename=data['excel_filename'])
    else:
        # 任务不存在或未完成，重定向回首页
        return redirect('/')

@app.route('/download/<filename>')
def download(filename):
    # 构建Excel文件路径
    excel_path = os.path.join(DATASET_DIR, filename)
    if os.path.exists(excel_path):
        return send_file(excel_path, as_attachment=True)
    else:
        return "文件不存在", 404

def get_excel_files():
    """获取dataset目录中的Excel文件（原始数据文件）"""
    if os.path.exists(DATASET_DIR):
        return sorted([f for f in os.listdir(DATASET_DIR) if f.endswith('.xlsx')])
    return []

if __name__ == '__main__':
    app.run(debug=True)