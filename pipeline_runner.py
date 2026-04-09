import subprocess
import sys


def run_step(cmd, name):
    print(f"\n===== {name} =====")
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")

    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError(f"{name} 执行失败")


def main(post_id, url):
    py = sys.executable

    # 1️⃣ 爬虫
    run_step(
        [py, "crawler.py", str(post_id), url],
        "爬取评论"
    )

    # 2️⃣ 主题分析（DeepSeek）
    run_step(
        [py, "theme/theme_generate_deepseek_first_post.py", str(post_id)],
        "主题分析"
    )

    # 3️⃣ 情感分析（DeepSeek）
    run_step(
        [py, "sentiment/sentiment_first_post_deepseek.py", str(post_id)],
        "情感分析"
    )

    # 4️⃣ 风险映射
    run_step(
        [py, "risk_issues_map.py", str(post_id)],
        "风险映射"
    )

    print("\n🎉 全流程完成！")