import subprocess
import sys
import pymysql


DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4"
}


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def update_task(task_id, status=None, current_step=None, progress_percent=None, message=None, error_message=None):
    conn = get_connection()
    try:
        fields = []
        values = []

        if status is not None:
            fields.append("status = %s")
            values.append(status)
        if current_step is not None:
            fields.append("current_step = %s")
            values.append(current_step)
        if progress_percent is not None:
            fields.append("progress_percent = %s")
            values.append(progress_percent)
        if message is not None:
            fields.append("message = %s")
            values.append(message)
        if error_message is not None:
            fields.append("error_message = %s")
            values.append(error_message)

        if not fields:
            return

        values.append(task_id)

        sql = f"""
            UPDATE analysis_tasks
            SET {", ".join(fields)}
            WHERE task_id = %s
        """

        with conn.cursor() as cursor:
            cursor.execute(sql, values)
        conn.commit()
    finally:
        conn.close()


def run_step(cmd, name, task_id, progress_percent):
    update_task(
        task_id=task_id,
        status="running",
        current_step=name,
        progress_percent=progress_percent,
        message=f"{name}中..."
    )

    print(f"\n===== {name} =====")
    print("命令：", " ".join(cmd))

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore"
    )

    print("returncode:", result.returncode)
    print("stdout:")
    print(result.stdout)
    print("stderr:")
    print(result.stderr)

    if result.returncode != 0:
        update_task(
            task_id=task_id,
            status="failed",
            current_step=name,
            progress_percent=progress_percent,
            message=f"{name}失败",
            error_message=result.stderr[:2000] if result.stderr else "未知错误"
        )
        raise RuntimeError(f"{name} 执行失败")


def main(task_id, post_id, url):
    py = sys.executable

    try:
        update_task(
            task_id=task_id,
            status="running",
            current_step="任务启动",
            progress_percent=5,
            message="任务已创建，准备开始分析"
        )

        # 1. 爬虫：爬取评论
        run_step(
            [py, "crawler.py", "--post-id", str(post_id), "--url", url],
            "评论爬取与入库",
            task_id,
            25
        )

        # 2. 主题分析
        run_step(
            [py, "theme/theme_generate_deepseek_first_post.py", "--post-id", str(post_id)],
            "主题分析",
            task_id,
            50
        )

        # 3. 情感分析
        run_step(
            [py, "sentiment/sentiment_first_post_deepseek.py", "--post-id", str(post_id)],
            "情感与态度分析",
            task_id,
            75
        )

        # 4. 风险映射
        run_step(
            [py, "risk_issues_map.py", "--post-id", str(post_id)],
            "风险映射更新",
            task_id,
            95
        )

        update_task(
            task_id=task_id,
            status="completed",
            current_step="分析完成",
            progress_percent=100,
            message="全部流程已完成"
        )

        print("\n🎉 全流程完成！")

    except Exception as e:
        update_task(
            task_id=task_id,
            status="failed",
            current_step="执行失败",
            message="分析流程执行失败",
            error_message=str(e)
        )
        raise


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("用法: python pipeline_runner.py <task_id> <post_id> <url>")
        sys.exit(1)

    main(int(sys.argv[1]), int(sys.argv[2]), sys.argv[3])