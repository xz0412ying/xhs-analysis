from workflow_ui.db import execute_sql, fetch_one
from workflow_ui.config import TASK_STATUS, TASK_STEPS


def create_task(url, title, publish_time, content):
    """
    创建一个新的分析任务
    """
    sql = """
        INSERT INTO analysis_tasks (
            task_type,
            task_status,
            progress_percent,
            current_stage,
            task_message,
            input_url,
            input_title,
            input_publish_time,
            input_content
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    params = (
        "single_post_pipeline",
        TASK_STATUS["PENDING"],
        0,
        TASK_STEPS["INIT"],
        "等待开始分析",
        url,
        title,
        publish_time,
        content
    )

    execute_sql(sql, params)

    row = fetch_one("SELECT MAX(task_id) AS task_id FROM analysis_tasks")
    return row["task_id"] if row else None


def update_task(task_id, status=None, percent=None, stage=None, message=None, post_id=None, error_message=None):
    """
    更新任务状态和进度
    参数名要和 pipeline_runner.py 保持一致：
    - status
    - percent
    - stage
    - message
    - post_id
    - error_message
    """
    sql = """
        UPDATE analysis_tasks
        SET task_status = COALESCE(%s, task_status),
            progress_percent = COALESCE(%s, progress_percent),
            current_stage = COALESCE(%s, current_stage),
            task_message = COALESCE(%s, task_message),
            post_id = COALESCE(%s, post_id),
            error_message = COALESCE(%s, error_message)
        WHERE task_id = %s
    """

    params = (
        status,
        percent,
        stage,
        message,
        post_id,
        error_message,
        task_id
    )

    execute_sql(sql, params)


def mark_task_running(task_id, stage=None, message=None, percent=None, post_id=None):
    """
    标记任务为运行中
    """
    update_task(
        task_id=task_id,
        status=TASK_STATUS["RUNNING"],
        percent=percent,
        stage=stage,
        message=message,
        post_id=post_id
    )


def mark_task_success(task_id, stage=None, message=None, percent=100, post_id=None):
    """
    标记任务成功完成
    """
    update_task(
        task_id=task_id,
        status=TASK_STATUS["SUCCESS"],
        percent=percent,
        stage=stage or TASK_STEPS["DONE"],
        message=message or "任务执行完成",
        post_id=post_id
    )


def mark_task_failed(task_id, stage=None, message=None, error_message=None, percent=100, post_id=None):
    """
    标记任务失败
    """
    update_task(
        task_id=task_id,
        status=TASK_STATUS["FAILED"],
        percent=percent,
        stage=stage or TASK_STEPS["ERROR"],
        message=message or "任务执行失败",
        post_id=post_id,
        error_message=error_message
    )


def get_task(task_id):
    """
    获取单个任务详情
    """
    sql = "SELECT * FROM analysis_tasks WHERE task_id = %s"
    return fetch_one(sql, (task_id,))


def get_latest_task():
    """
    获取最新任务
    """
    sql = """
        SELECT *
        FROM analysis_tasks
        ORDER BY task_id DESC
        LIMIT 1
    """
    return fetch_one(sql)


def reset_task(task_id):
    """
    重置某个任务为初始状态
    """
    sql = """
        UPDATE analysis_tasks
        SET task_status = %s,
            progress_percent = 0,
            current_stage = %s,
            task_message = %s,
            post_id = NULL,
            error_message = NULL
        WHERE task_id = %s
    """
    params = (
        TASK_STATUS["PENDING"],
        TASK_STEPS["INIT"],
        "等待开始分析",
        task_id
    )
    execute_sql(sql, params)