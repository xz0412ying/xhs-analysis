"""
总调度脚本：协调爬虫、主题分析、情感分析和风险映射
"""
import sys
import subprocess


def run_step(cmd, name):
    """运行单个步骤并输出结果"""
    print(f"\n===== {name} =====")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"{name} 执行失败")
    
    return result.returncode == 0


def run_pipeline(url, title, publish_time, content):
    """
    运行完整的分析流程
    
    Args:
        url: 小红书帖子URL
        title: 帖子标题
        publish_time: 发布时间
        content: 帖子内容
    """
    py = sys.executable
    
    # 1️⃣ 爬虫：爬取评论
    result = run_step_with_output(
        [py, "crawler/xhs_crawler.py", url, title, publish_time, content],
        "爬取评论"
    )
    
    # 从爬虫输出中获取post_id
    post_id = extract_post_id(result)
    if not post_id:
        raise RuntimeError("无法从爬虫输出中获取post_id")
    
    print(f"提取到 post_id: {post_id}")
    
    # 2️⃣ 主题分析（DeepSeek）
    if not run_step(
        [py, "analysis/ds_theme.py", str(post_id)],
        "主题分析"
    ):
        raise RuntimeError("主题分析执行失败")
    
    # 3️⃣ 情感分析（DeepSeek）
    if not run_step(
        [py, "analysis/ds_sentiment.py", str(post_id)],
        "情感分析"
    ):
        raise RuntimeError("情感分析执行失败")
    
    # 4️⃣ 风险映射
    if not run_step(
        [py, "risk_issues_map.py", str(post_id)],
        "风险映射"
    ):
        raise RuntimeError("风险映射执行失败")
    
    print("\n🎉 全流程完成！")
    return True


def run_step_with_output(cmd, name):
    """运行单个步骤并返回输出"""
    print(f"\n===== {name} =====")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"{name} 执行失败")
    
    return result


def extract_post_id(output_text):
    """从爬虫输出中提取post_id"""
    import re
    match = re.search(r"POST_ID:(\d+)", output_text)
    if match:
        return int(match.group(1))
    return None


if __name__ == "__main__":
    # 从命令行获取参数
    if len(sys.argv) < 5:
        print("用法: python orchestrator.py <url> <title> <publish_time> <content>")
        sys.exit(1)
    
    url = sys.argv[1]
    title = sys.argv[2]
    publish_time = sys.argv[3]
    content = sys.argv[4]
    
    try:
        run_pipeline(url, title, publish_time, content)
    except Exception as e:
        print(f"流程执行失败: {e}")
        sys.exit(1)
