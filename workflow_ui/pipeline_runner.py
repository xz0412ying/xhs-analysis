import traceback

from workflow_ui.config import TASK_STATUS, TASK_STEPS
from workflow_ui.task_service import update_task, mark_task_success, mark_task_failed
from workflow_ui.crawler_service import crawl_and_store_post
from workflow_ui.theme_service import match_existing_theme_for_post_id
from workflow_ui.sentiment_service import run_sentiment_analysis_for_post_id


def run_single_post_pipeline(task_id, url, title, publish_time, content):
    """
    单帖完整分析流程（新版）：
    1. 爬虫抓取评论并写入数据库
    2. 主题分析（DeepSeek匹配现有主题）
    3. 情感分析 + 态度识别
    4. 输出分析页面（不再需要风险识别）
    """
    post_id = None

    try:
        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=5,
            stage=TASK_STEPS["CREATED"],
            message="任务已创建，准备开始执行"
        )

        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=12,
            stage=TASK_STEPS["CRAWLING"],
            message="正在根据小红书 URL 爬取评论"
        )

        crawl_result = crawl_and_store_post(
            url=url,
            title=title,
            publish_time=publish_time,
            content=content
        )

        post_id = crawl_result["post_id"]
        comment_count = crawl_result.get("comment_count", 0)

        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=30,
            stage=TASK_STEPS["STORING"],
            message=f"数据已写入数据库，post_id={post_id}，评论数={comment_count}",
            post_id=post_id
        )

        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=45,
            stage=TASK_STEPS["THEME"],
            message="正在匹配现有主题",
            post_id=post_id
        )

        theme_result = match_existing_theme_for_post_id(post_id)
        matched_theme = theme_result.get("matched_theme", "")

        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=62,
            stage=TASK_STEPS["THEME"],
            message=f"主题匹配完成：{matched_theme}",
            post_id=post_id
        )

        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=72,
            stage=TASK_STEPS["SENTIMENT"],
            message="正在分析评论情感与态度",
            post_id=post_id
        )

        sentiment_result = run_sentiment_analysis_for_post_id(
            post_id=post_id,
            reanalyze_all=True
        )

        total_comments = sentiment_result.get("total", 0)
        positive_count = sentiment_result.get("positive", 0)
        neutral_count = sentiment_result.get("neutral", 0)
        negative_count = sentiment_result.get("negative", 0)

        update_task(
            task_id=task_id,
            status=TASK_STATUS["RUNNING"],
            percent=95,
            stage=TASK_STEPS["SENTIMENT"],
            message=(
                f"情感分析完成：共{total_comments}条，"
                f"积极{positive_count}条，中性{neutral_count}条，消极{negative_count}条"
            ),
            post_id=post_id
        )

        mark_task_success(
            task_id=task_id,
            stage=TASK_STEPS["DONE"],
            percent=100,
            post_id=post_id,
            message=f"分析完成，post_id={post_id}，评论数={total_comments}，匹配主题={matched_theme}"
        )

    except Exception:
        error_text = traceback.format_exc()

        mark_task_failed(
            task_id=task_id,
            stage=TASK_STEPS["ERROR"],
            percent=100,
            post_id=post_id,
            message="分析流程执行失败",
            error_message=error_text
        )