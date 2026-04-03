import time
import os
import pandas as pd
from DrissionPage import ChromiumPage

def crawl_xiaohongshu_comments(url, progress_callback=None):
    """
    爬取小红书帖子的评论
    :param url: 小红书帖子URL
    :param progress_callback: 进度回调函数，接收当前进度和总进度
    :return: 评论列表，每个元素包含 content, likes
    """
    try:
        print("开始爬取小红书评论...")
        
        # 创建 ChromiumPage 实例
        page = ChromiumPage()
        
        # 打开页面
        print(f"打开页面: {url}")
        page.get(url)
        
        # 等待页面加载
        print("等待页面加载...")
        time.sleep(5)  # 增加等待时间
        
        # 检查是否有登录模态框
        print("检查是否有登录模态框...")
        try:
            # 尝试关闭登录模态框
            close_buttons = page.eles('.close, .cancel, .close-btn, .modal-close')
            if close_buttons:
                print(f"找到 {len(close_buttons)} 个关闭按钮，尝试关闭登录模态框")
                for button in close_buttons:
                    try:
                        button.click()
                        time.sleep(2)
                        break
                    except:
                        pass
        except Exception as e:
            print(f"检查登录模态框时出错: {str(e)}")
        
        # 自动下滑加载更多评论
        print("开始自动下滑加载更多评论...")
        
        # 记录初始页面高度
        last_height = page.scroll.to_bottom()
        time.sleep(2)  # 增加等待时间
        
        # 下滑次数
        scroll_count = 0
        max_scrolls = 10  # 大幅增加下滑次数以加载更多评论
        no_change_count = 0  # 记录页面高度无变化的次数
        
        while scroll_count < max_scrolls:
            # 尝试点击"加载更多"按钮
            try:
                load_more_buttons = page.eles('.load-more, .load-more-btn, .load-more-button, .more-btn, .next-page, .loadMore, .load-more-comments, .load-more-btn-text, .btn-load-more, .load-more-btn-text, .load-more-btn-primary, .load-more-btn-secondary, .load-more-btn-normal, .load-more-btn-large, .load-more-btn-small, .load-more-btn-default, .load-more-btn-block, .load-more-btn-inline, .load-more-btn-link, .load-more-btn-outline, .load-more-btn-solid, .load-more-btn-danger, .load-more-btn-success, .load-more-btn-warning, .load-more-btn-info, .load-more-btn-light, .load-more-btn-dark, .load-more-btn-disabled')
                if load_more_buttons:
                    print(f"找到 {len(load_more_buttons)} 个加载更多按钮，尝试点击")
                    for button in load_more_buttons:
                        try:
                            button.click()
                            print("点击了加载更多按钮")
                            time.sleep(2)  # 等待加载
                            break
                        except Exception as e:
                            print(f"点击加载更多按钮失败: {str(e)}")
                            pass
            except Exception as e:
                print(f"查找加载更多按钮时出错: {str(e)}")
            
            # 智能滚动策略：分阶段滚动
            try:
                # 先滚动到页面的50%位置
                page.scroll.to(percentage=50)
                time.sleep(2)  # 等待加载
                # 再滚动到页面的80%位置
                page.scroll.to(percentage=80)
                time.sleep(2)  # 等待加载
                # 最后滚动到底部
                new_height = page.scroll.to_bottom()
            except Exception:
                # 如果滚动到百分比位置失败，直接滚动到底部
                new_height = page.scroll.to_bottom()
            
            # 等待新内容加载
            time.sleep(2)  # 大幅增加等待时间，确保评论加载完成
            
            # 如果页面高度没有变化，说明没有更多内容了
            if new_height == last_height:
                no_change_count += 1
                print(f"页面高度无变化，次数: {no_change_count}")
                if no_change_count >= 8:  # 连续8次无变化就停止
                    break
            else:
                no_change_count = 0
            
            last_height = new_height
            scroll_count += 1
            print(f"已下滑 {scroll_count} 次，当前页面高度: {new_height}")
            
            # 调用进度回调函数
            if progress_callback:
                progress = min(int((scroll_count / max_scrolls) * 100), 100)
                progress_callback(progress, max_scrolls)
        
        # 保存页面源码以便分析
        page_source = page.html
        with open('page_source.html', 'w', encoding='utf-8') as f:
            f.write(page_source)
        print("已保存页面源码到 page_source.html")
        
        # 尝试查找评论元素
        print("开始查找评论元素...")
        
        # 只使用 .comment-item 选择器
        comment_selector = '.comment-item'
        comment_elements = page.eles(comment_selector)
        print(f"使用 {comment_selector} 找到 {len(comment_elements)} 个评论元素")
        
        comments = []
        
        # 遍历评论元素
        for i, element in enumerate(comment_elements):
            try:
                # 获取评论的完整文本
                comment_text = element.text.strip()
                
                # 过滤掉太短的内容
                if len(comment_text) < 20:
                    continue
                
                # 分割评论文本，提取各个字段
                lines = comment_text.split('\n')
                
                if len(lines) >= 2:
                    # 提取id（第一行）
                    comment_id = lines[0].strip()
                    
                    # 提取评论内容（第二行）
                    comment_content = lines[1].strip()
                    
                    # 提取点赞数
                    likes = ""
                    # 搜索整个评论文本中的点赞信息
                    import re
                    # 匹配包含"赞"、"点赞"等关键词的部分
                    likes_pattern = r'(?:赞|点赞|likes?)[：:]*\s*(\d+)'
                    likes_match = re.search(likes_pattern, comment_text)
                    if likes_match:
                        likes = likes_match.group(1)
                    else:
                        # 如果没有找到明确的点赞标识，尝试在所有行中搜索数字
                        for line in lines:
                            line = line.strip()
                            # 排除明显不是点赞数的数字（如ID或其他数字）
                            if line and line.isdigit() and len(line) <= 5:  # 点赞数通常不会超过5位数
                                likes = line
                                break
                    
                    comments.append({
                        "id": comment_id,
                        "content": comment_content,
                        "likes": likes
                    })
                    print(f"已提取第 {i+1} 条评论")
                    print(f"  ID: {comment_id}")
                    print(f"  内容: {comment_content[:50]}...")
                    print(f"  点赞: {likes}")
            except Exception as e:
                # 处理单个评论提取失败的情况
                pass
        
        # 移除其他通用方法的尝试，只保留 .comment-item 的爬虫
        
        # 关闭页面
        page.close()
        
        # 去重
        unique_comments = []
        seen_contents = set()
        for comment in comments:
            if comment['content'] not in seen_contents:
                seen_contents.add(comment['content'])
                unique_comments.append(comment)
        
        print(f"共爬取到 {len(unique_comments)} 条评论")
        return unique_comments
        
    except Exception as e:
        print(f"爬取失败: {str(e)}")
        return []

def save_comments_to_excel(comments, filename):
    """
    保存评论到Excel文件
    :param comments: 评论列表
    :param filename: 文件名
    :return: Excel文件路径
    """
    try:
        print(f"开始保存评论到Excel: {filename}")
        print(f"评论数量: {len(comments)}")
        
        if comments:
            # 转换为DataFrame
            df = pd.DataFrame(comments)
            print(f"DataFrame形状: {df.shape}")
            print(f"DataFrame列: {list(df.columns)}")
            
            # 确保列顺序
            expected_columns = ['id', 'content', 'likes']
            for col in expected_columns:
                if col not in df.columns:
                    df[col] = ""
            df = df[expected_columns]
            
            # 确保 dataset 文件夹存在
            dataset_dir = os.path.join(os.getcwd(), 'dataset')
            if not os.path.exists(dataset_dir):
                os.makedirs(dataset_dir)
                print(f"创建了 dataset 文件夹: {dataset_dir}")
            
            # 保存为Excel文件
            excel_path = os.path.join(dataset_dir, filename)
            print(f"Excel文件路径: {excel_path}")
            
            # 尝试保存
            df.to_excel(excel_path, index=False)
            print(f"成功保存Excel文件: {excel_path}")
            
            # 验证文件是否存在
            if os.path.exists(excel_path):
                print(f"文件已存在，大小: {os.path.getsize(excel_path)} bytes")
            else:
                print("文件保存失败，文件不存在")
            
            return excel_path
        else:
            print("没有评论数据可保存")
            return None
    except Exception as e:
        print(f"保存Excel文件失败: {str(e)}")
        # 尝试使用当前目录保存
        try:
            if comments:
                df = pd.DataFrame(comments)
                # 确保列顺序
                expected_columns = ['id', 'content', 'likes']
                for col in expected_columns:
                    if col not in df.columns:
                        df[col] = ""
                df = df[expected_columns]
                excel_path = os.path.join(os.getcwd(), filename)
                df.to_excel(excel_path, index=False)
                print(f"成功保存到当前目录: {excel_path}")
                return excel_path
        except Exception as e2:
            print(f"备用保存方法也失败: {str(e2)}")
        return None

if __name__ == "__main__":
    # 测试URL
    test_url = "https://www.xiaohongshu.com/explore/698fe871000000000a0287af"
    
    # 爬取评论
    comments = crawl_xiaohongshu_comments(test_url)
    
    # 生成Excel文件名
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"xiaohongshu_comments_{timestamp}.xlsx"
    
    # 保存为Excel文件
    excel_path = save_comments_to_excel(comments, filename)
    
    if excel_path:
        print(f"爬取完成，Excel文件已保存: {excel_path}")
    else:
        print("爬取失败，未能保存Excel文件")
    
    # 显示前5条评论
    if comments:
        print("\n前5条评论预览:")
        for i, comment in enumerate(comments[:5]):
            print(f"{i+1}. 点赞: {comment['likes']}")
            print(f"   内容: {comment['content'][:100]}...")
            print()
    else:
        print("未爬取到任何评论")
