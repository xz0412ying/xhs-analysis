import threading
from flask import Blueprint, render_template, request, jsonify, redirect, url_for
from workflow_ui.task_service import create_task, get_task
from workflow_ui.pipeline_runner import run_single_post_pipeline

workflow_bp = Blueprint("workflow_bp", __name__)

@workflow_bp.route("/workflow/new", methods=["GET", "POST"])
def workflow_new():
    if request.method == "GET":
        return render_template("workflow_submit.html", page_title="新建分析任务")

    url = request.form.get("url", "").strip()
    title = request.form.get("title", "").strip()
    publish_time = request.form.get("publish_time", "").strip()
    content = request.form.get("content", "").strip()

    task_id = create_task(url, title, publish_time, content)

    thread = threading.Thread(
        target=run_single_post_pipeline,
        args=(task_id, url, title, publish_time, content),
        daemon=True
    )
    thread.start()

    return redirect(url_for("workflow_bp.workflow_progress", task_id=task_id))

@workflow_bp.route("/workflow/task/<int:task_id>")
def workflow_progress(task_id):
    return render_template("workflow_progress.html", page_title="任务进度", task_id=task_id)

@workflow_bp.route("/api/workflow/task/<int:task_id>")
def api_workflow_task(task_id):
    task = get_task(task_id)
    return jsonify(task or {})