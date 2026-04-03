import re
import time
import pymysql
from DrissionPage import ChromiumPage


# =========================
# 1. 数据库配置
# =========================
DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4"
}


# =========================
# 2. 通用工具函数
# =========================
def safe_text(ele):
    """安全获取元素文本"""
    try:
        if ele:
            return ele.text.strip()
    except Exception:
        pass
    return ""


def extract_number(text):
    """
    提取点赞数字
    支持：
    - 赞 -> 0
    - 56 -> 56
    - 1.2万 -> 12000
    """
    if not text:
        return 0

    text = text.strip()

    if text == "赞":
        return 0

    if "万" in text:
        match = re.search(r'([\d.]+)\s*万', text)
        if match:
            return int(float(match.group(1)) * 10000)

    match = re.search(r'(\d+)', text)
    if match:
        return int(match.group(1))

    return 0


# =========================
# 3. 评论提取逻辑
# =========================
def get_comment_content_by_lines(full_text):
    """
    按你当前观察到的小红书评论结构提取正文：
    第1行：用户名
    第2行：评论内容
    第3行：时间/地区
    第4行：点赞/回复
    """
    if not full_text:
        return ""

    lines = [x.strip() for x in full_text.split('\n') if x.strip()]

    if len(lines) >= 2:
        return lines[1]

    return ""


def get_like_count_from_element(comment_ele):
    """
    从评论元素内部直接找点赞数：
    - 点赞数字通常在 .count
    - 第一个 .count 通常对应爱心点赞
    - 如果显示的是“赞”，说明点赞数为 0
    """
    try:
        count_eles = comment_ele.eles('.count')
        if not count_eles:
            return 0

        first_count_text = safe_text(count_eles[0])
        return extract_number(first_count_text)

    except Exception:
        return 0


def crawl_comments_by_url(url, max_scrolls=10):
    """
    根据帖子 URL 爬取评论内容和点赞量
    返回：
    [
        {"comment_content": "...", "like_count": 12},
        ...
    ]
    """
    page = None
    comments = []

    try:
        page = ChromiumPage()
        print(f"打开页面: {url}")
        page.get(url)
        time.sleep(5)

        # 尝试关闭弹窗
        close_selectors = ['.close', '.cancel', '.close-btn', '.modal-close']
        for selector in close_selectors:
            try:
                btns = page.eles(selector)
                for btn in btns:
                    try:
                        btn.click()
                        time.sleep(1)
                        break
                    except Exception:
                        pass
            except Exception:
                pass

        print("开始滚动加载评论...")

        last_height = 0
        no_change_count = 0

        for i in range(max_scrolls):
            try:
                # 尝试点击展开更多
                more_btns = page.eles('text=展开更多, text=加载更多, text=查看更多')
                for btn in more_btns:
                    try:
                        btn.click()
                        time.sleep(1)
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                page.scroll.to_bottom()
                time.sleep(2)
                new_height = page.run_js("return document.body.scrollHeight")
            except Exception:
                new_height = last_height

            if new_height == last_height:
                no_change_count += 1
            else:
                no_change_count = 0

            last_height = new_height
            print(f"已滚动 {i + 1}/{max_scrolls} 次")

            if no_change_count >= 3:
                print("页面没有更多新内容了")
                break

        # 尝试多个评论选择器
        selectors = [
            '.comment-item',
            '.parent-comment',
            '.note-comment-item'
        ]

        comment_elements = []
        for selector in selectors:
            try:
                eles = page.eles(selector)
                if eles and len(eles) > len(comment_elements):
                    comment_elements = eles
                    print(f"使用选择器 {selector} 找到 {len(eles)} 个评论元素")
            except Exception:
                pass

        seen = set()

        for i, ele in enumerate(comment_elements, start=1):
            try:
                full_text = safe_text(ele)
                if not full_text:
                    continue

                comment_content = get_comment_content_by_lines(full_text)
                if not comment_content:
                    continue

                like_count = get_like_count_from_element(ele)

                # 去重
                if comment_content in seen:
                    continue
                seen.add(comment_content)

                comments.append({
                    "comment_content": comment_content,
                    "like_count": like_count
                })

                print(f"第{i}条 -> 评论: {comment_content} | 点赞: {like_count}")

            except Exception as e:
                print(f"第{i}条提取失败: {e}")
                continue

        print(f"共爬取到 {len(comments)} 条评论")
        return comments

    except Exception as e:
        print("爬取评论失败：", str(e))
        return []

    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass


# =========================
# 4. 数据库操作
# =========================
def get_connection():
    """连接 MySQL"""
    return pymysql.connect(**DB_CONFIG)


def insert_post(conn, title, publish_time, content):
    """
    插入帖子到 posts 表
    返回新插入的 post_id
    """
    sql = """
        INSERT INTO posts (title, publish_time, content)
        VALUES (%s, %s, %s)
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (title, publish_time, content))
        conn.commit()
        return cursor.lastrowid


def insert_comments(conn, post_id, comments):
    """
    批量插入评论到 comments 表
    字段：
    - post_id
    - comment_content
    - like_count
    """
    if not comments:
        return

    sql = """
        INSERT INTO comments (post_id, comment_content, like_count)
        VALUES (%s, %s, %s)
    """

    values = []
    for c in comments:
        values.append((
            post_id,
            c["comment_content"],
            c["like_count"]
        ))

    with conn.cursor() as cursor:
        cursor.executemany(sql, values)
        conn.commit()


# =========================
# 5. 主程序
# =========================
def main():
    conn = None

    try:
        print("=== 小红书帖子评论采集程序 ===")
        url = input("请输入帖子URL：").strip()
        title = input("请输入帖子标题：").strip()
        publish_time = input("请输入发布时间：").strip()
        content = input("请输入帖子内容：").strip()

        # 连接数据库
        conn = get_connection()
        print("数据库连接成功")

        # 1. 插入帖子
        post_id = insert_post(conn, title, publish_time, content)
        print(f"帖子已写入 posts 表，post_id = {post_id}")

        # 2. 根据 URL 爬取评论
        comments = crawl_comments_by_url(url)

        # 3. 插入评论
        insert_comments(conn, post_id, comments)
        print(f"评论已写入 comments 表，共 {len(comments)} 条")

        print("全部完成")

    except Exception as e:
        print("程序执行失败：", str(e))

    finally:
        if conn:
            try:
                conn.close()
                print("数据库连接已关闭")
            except Exception:
                pass


if __name__ == "__main__":
    main()