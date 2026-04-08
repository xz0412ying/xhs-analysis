from flask import Flask, render_template, jsonify
import pymysql

app = Flask(__name__)

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "xiaohongshu_analysis",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}


def get_connection():
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print("数据库连接失败：", e)
        raise


def get_all_risks():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name, risk_desc
                FROM risk_issues
                ORDER BY risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_posts_by_risk(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT p.post_id, p.title, p.publish_time
                FROM post_risk_map prm
                JOIN posts p ON prm.post_id = p.post_id
                WHERE prm.risk_id = %s
                ORDER BY p.post_id ASC
            """, (risk_id,))
            return cursor.fetchall()
    finally:
        conn.close()


# =========================
# Dashboard
# =========================

def get_dashboard_stats():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS cnt FROM posts")
            post_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("SELECT COUNT(*) AS cnt FROM comments")
            comment_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("SELECT COUNT(*) AS cnt FROM risk_issues")
            risk_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM comments
                WHERE sentiment_label IS NOT NULL
            """)
            labeled_comment_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT
                    COUNT(*) AS total_cnt,
                    SUM(CASE WHEN sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt
                FROM comments
                WHERE sentiment_label IS NOT NULL
            """)
            row = cursor.fetchone()
            total_cnt = row["total_cnt"] or 0
            negative_cnt = row["negative_cnt"] or 0
            negative_ratio = round((negative_cnt / total_cnt * 100), 2) if total_cnt else 0

            return {
                "post_count": post_count,
                "comment_count": comment_count,
                "risk_count": risk_count,
                "labeled_comment_count": labeled_comment_count,
                "negative_ratio": negative_ratio
            }
    finally:
        conn.close()


def get_risk_distribution():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.risk_id, r.risk_name, COUNT(*) AS cnt
                FROM post_risk_map m
                JOIN risk_issues r ON m.risk_id = r.risk_id
                GROUP BY r.risk_id, r.risk_name
                ORDER BY cnt DESC, r.risk_id ASC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_sentiment_overview():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sentiment_label, COUNT(*) AS cnt
                FROM comments
                WHERE sentiment_label IS NOT NULL
                GROUP BY sentiment_label
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_sentiment_distribution():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    r.risk_name,
                    c.sentiment_label,
                    COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE c.sentiment_label IS NOT NULL
                GROUP BY r.risk_name, c.sentiment_label
                ORDER BY r.risk_name
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_negative_rate():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    r.risk_name,
                    COUNT(*) AS total_cnt,
                    SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt,
                    ROUND(
                        SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
                        2
                    ) AS negative_rate
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE c.sentiment_label IS NOT NULL
                GROUP BY r.risk_name
                HAVING COUNT(*) > 0
                ORDER BY negative_rate DESC, total_cnt DESC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


def get_top_risks(limit=5):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.risk_name, COUNT(*) AS cnt
                FROM post_risk_map m
                JOIN risk_issues r ON m.risk_id = r.risk_id
                GROUP BY r.risk_name
                ORDER BY cnt DESC, r.risk_id ASC
                LIMIT %s
            """, (limit,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_trend_monthly(limit=5):
    top_risks = get_top_risks(limit)
    risk_names = [r["risk_name"] for r in top_risks]
    if not risk_names:
        return []

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            placeholders = ",".join(["%s"] * len(risk_names))
            sql = f"""
                SELECT
                    DATE_FORMAT(p.publish_time, '%%Y-%%m') AS month_label,
                    r.risk_name,
                    COUNT(*) AS cnt
                FROM posts p
                JOIN post_risk_map m ON p.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE p.publish_time IS NOT NULL
                  AND r.risk_name IN ({placeholders})
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m'), r.risk_name
                ORDER BY month_label ASC
            """
            cursor.execute(sql, risk_names)
            return cursor.fetchall()
    finally:
        conn.close()


def get_hot_posts(limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    p.post_id,
                    p.title,
                    p.publish_time,
                    COUNT(c.comment_id) AS comment_cnt,
                    COALESCE(SUM(c.like_count), 0) AS total_like,
                    GROUP_CONCAT(DISTINCT r.risk_name ORDER BY r.risk_id SEPARATOR '、') AS risks
                FROM posts p
                LEFT JOIN comments c ON p.post_id = c.post_id
                LEFT JOIN post_risk_map prm ON p.post_id = prm.post_id
                LEFT JOIN risk_issues r ON prm.risk_id = r.risk_id
                GROUP BY p.post_id, p.title, p.publish_time
                ORDER BY comment_cnt DESC, total_like DESC, p.post_id ASC
                LIMIT %s
            """, (limit,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_cooccurrence_matrix():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name
                FROM risk_issues
                ORDER BY risk_id ASC
            """)
            risks = cursor.fetchall()

            if not risks:
                return {"risks": [], "values": []}

            risk_ids = [r["risk_id"] for r in risks]
            risk_names = [r["risk_name"] for r in risks]

            cursor.execute("""
                SELECT
                    a.risk_id AS risk_a,
                    b.risk_id AS risk_b,
                    COUNT(*) AS cnt
                FROM post_risk_map a
                JOIN post_risk_map b
                  ON a.post_id = b.post_id
                GROUP BY a.risk_id, b.risk_id
            """)
            rows = cursor.fetchall()

            values = []
            for row in rows:
                if row["risk_a"] in risk_ids and row["risk_b"] in risk_ids:
                    x = risk_ids.index(row["risk_a"])
                    y = risk_ids.index(row["risk_b"])
                    values.append([x, y, row["cnt"]])

            return {
                "risks": risk_names,
                "values": values
            }
    finally:
        conn.close()


def get_risk_heat_scatter():
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    r.risk_name,
                    COUNT(*) AS total_cnt,
                    SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt,
                    ROUND(
                        SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) * 100.0 / COUNT(*),
                        2
                    ) AS negative_rate
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE c.sentiment_label IS NOT NULL
                GROUP BY r.risk_name
                HAVING COUNT(*) > 0
                ORDER BY total_cnt DESC
            """)
            return cursor.fetchall()
    finally:
        conn.close()


# =========================
# Risk Detail
# =========================

def get_risk_detail(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT risk_id, risk_name, risk_desc
                FROM risk_issues
                WHERE risk_id = %s
            """, (risk_id,))
            risk = cursor.fetchone()

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM post_risk_map
                WHERE risk_id = %s
            """, (risk_id,))
            post_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
            """, (risk_id,))
            comment_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.attitude_type IS NOT NULL
            """, (risk_id,))
            labeled_attitude_count = cursor.fetchone()["cnt"] or 0

            cursor.execute("""
                SELECT
                    COUNT(*) AS total_cnt,
                    SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS negative_cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.sentiment_label IS NOT NULL
            """, (risk_id,))
            row = cursor.fetchone()
            total_cnt = row["total_cnt"] or 0
            negative_cnt = row["negative_cnt"] or 0
            negative_ratio = round((negative_cnt / total_cnt * 100), 2) if total_cnt else 0

            return {
                "risk": risk,
                "post_count": post_count,
                "comment_count": comment_count,
                "labeled_attitude_count": labeled_attitude_count,
                "negative_ratio": negative_ratio
            }
    finally:
        conn.close()


def get_risk_sentiment_summary(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.sentiment_label, COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.sentiment_label IS NOT NULL
                GROUP BY c.sentiment_label
            """, (risk_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_attitude_summary(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.attitude_type, COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.attitude_type IS NOT NULL
                GROUP BY c.attitude_type
                ORDER BY cnt DESC
            """, (risk_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_theme_summary(risk_id, limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT c.assigned_theme, COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.assigned_theme IS NOT NULL
                  AND c.assigned_theme <> ''
                GROUP BY c.assigned_theme
                ORDER BY cnt DESC
                LIMIT %s
            """, (risk_id, limit))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_trend_detail(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt, COUNT(*) AS cnt
                FROM posts p
                JOIN post_risk_map m ON p.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND p.publish_time IS NOT NULL
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m')
                ORDER BY dt ASC
            """, (risk_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_negative_trend_detail(risk_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    DATE_FORMAT(p.publish_time, '%%Y-%%m') AS dt,
                    SUM(CASE WHEN c.sentiment_label = '消极' THEN 1 ELSE 0 END) AS cnt
                FROM comments c
                JOIN posts p ON c.post_id = p.post_id
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND p.publish_time IS NOT NULL
                  AND c.sentiment_label IS NOT NULL
                GROUP BY DATE_FORMAT(p.publish_time, '%%Y-%%m')
                ORDER BY dt ASC
            """, (risk_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_hot_posts(risk_id, limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT
                    p.post_id,
                    p.title,
                    p.publish_time,
                    COUNT(c.comment_id) AS comment_cnt,
                    COALESCE(SUM(c.like_count), 0) AS total_like
                FROM post_risk_map prm
                JOIN posts p ON prm.post_id = p.post_id
                LEFT JOIN comments c ON p.post_id = c.post_id
                WHERE prm.risk_id = %s
                GROUP BY p.post_id, p.title, p.publish_time
                ORDER BY comment_cnt DESC, total_like DESC, p.post_id ASC
                LIMIT %s
            """, (risk_id, limit))
            return cursor.fetchall()
    finally:
        conn.close()


def get_risk_theme_attitude_matrix(risk_id, theme_limit=8):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT assigned_theme
                FROM (
                    SELECT
                        c.assigned_theme,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN post_risk_map m ON c.post_id = m.post_id
                    WHERE m.risk_id = %s
                      AND c.assigned_theme IS NOT NULL
                      AND c.assigned_theme <> ''
                    GROUP BY c.assigned_theme
                    ORDER BY cnt DESC
                    LIMIT %s
                ) t
            """, (risk_id, theme_limit))
            top_theme_rows = cursor.fetchall()
            top_themes = [row["assigned_theme"] for row in top_theme_rows]

            if not top_themes:
                return {"themes": [], "attitudes": [], "values": []}

            placeholders = ",".join(["%s"] * len(top_themes))
            sql = f"""
                SELECT
                    c.assigned_theme,
                    c.attitude_type,
                    COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.assigned_theme IN ({placeholders})
                  AND c.attitude_type IS NOT NULL
                GROUP BY c.assigned_theme, c.attitude_type
                ORDER BY c.assigned_theme, c.attitude_type
            """
            cursor.execute(sql, [risk_id] + top_themes)
            rows = cursor.fetchall()

            attitudes = sorted(list({row["attitude_type"] for row in rows if row["attitude_type"]}))
            values = []
            for row in rows:
                if row["assigned_theme"] in top_themes and row["attitude_type"] in attitudes:
                    x = top_themes.index(row["assigned_theme"])
                    y = attitudes.index(row["attitude_type"])
                    values.append([x, y, row["cnt"]])

            return {
                "themes": top_themes,
                "attitudes": attitudes,
                "values": values
            }
    finally:
        conn.close()


def get_risk_theme_sentiment_distribution(risk_id, theme_limit=8):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT assigned_theme
                FROM (
                    SELECT
                        c.assigned_theme,
                        COUNT(*) AS cnt
                    FROM comments c
                    JOIN post_risk_map m ON c.post_id = m.post_id
                    WHERE m.risk_id = %s
                      AND c.assigned_theme IS NOT NULL
                      AND c.assigned_theme <> ''
                    GROUP BY c.assigned_theme
                    ORDER BY cnt DESC
                    LIMIT %s
                ) t
            """, (risk_id, theme_limit))
            top_theme_rows = cursor.fetchall()
            top_themes = [row["assigned_theme"] for row in top_theme_rows]

            if not top_themes:
                return []

            placeholders = ",".join(["%s"] * len(top_themes))
            sql = f"""
                SELECT
                    c.assigned_theme,
                    c.sentiment_label,
                    COUNT(*) AS cnt
                FROM comments c
                JOIN post_risk_map m ON c.post_id = m.post_id
                WHERE m.risk_id = %s
                  AND c.assigned_theme IN ({placeholders})
                  AND c.sentiment_label IS NOT NULL
                GROUP BY c.assigned_theme, c.sentiment_label
                ORDER BY c.assigned_theme, c.sentiment_label
            """
            cursor.execute(sql, [risk_id] + top_themes)
            return cursor.fetchall()
    finally:
        conn.close()


# =========================
# Post Detail
# =========================

def get_post_detail(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT post_id, title, publish_time, content, theme1, theme2, theme3
                FROM posts
                WHERE post_id = %s
            """, (post_id,))
            return cursor.fetchone()
    finally:
        conn.close()


def get_post_risks(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT r.risk_id, r.risk_name
                FROM post_risk_map m
                JOIN risk_issues r ON m.risk_id = r.risk_id
                WHERE m.post_id = %s
                ORDER BY r.risk_id ASC
            """, (post_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_sentiment_summary(post_id):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT sentiment_label, COUNT(*) AS cnt
                FROM comments
                WHERE post_id = %s
                  AND sentiment_label IS NOT NULL
                GROUP BY sentiment_label
            """, (post_id,))
            return cursor.fetchall()
    finally:
        conn.close()


def get_post_comments(post_id, limit=10):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT comment_id, comment_content, like_count, assigned_theme, sentiment_label, attitude_type
                FROM comments
                WHERE post_id = %s
                ORDER BY like_count DESC, comment_id ASC
                LIMIT %s
            """, (post_id, limit))
            return cursor.fetchall()
    finally:
        conn.close()


# =========================
# Routes
# =========================

@app.route("/")
@app.route("/dashboard")
def dashboard():
    risks = get_all_risks()
    stats = get_dashboard_stats()
    hot_posts = get_hot_posts(10)
    return render_template(
        "dashboard.html",
        page_title="总风险分析",
        risks=risks,
        current_page="dashboard",
        current_risk_id=None,
        current_post_id=None,
        posts_for_sidebar=[],
        stats=stats,
        hot_posts=hot_posts
    )


@app.route("/risk/<int:risk_id>")
def risk_detail(risk_id):
    risks = get_all_risks()
    posts_for_sidebar = get_posts_by_risk(risk_id)
    detail = get_risk_detail(risk_id)
    hot_posts = get_risk_hot_posts(risk_id, 10)
    return render_template(
        "risk_detail.html",
        page_title="单风险分析",
        risks=risks,
        current_page="risk",
        current_risk_id=risk_id,
        current_post_id=None,
        posts_for_sidebar=posts_for_sidebar,
        risk_detail=detail,
        hot_posts=hot_posts
    )


@app.route("/post/<int:post_id>")
def post_detail(post_id):
    risks = get_all_risks()
    post = get_post_detail(post_id)
    post_risks = get_post_risks(post_id)

    posts_for_sidebar = []
    current_risk_id = None
    if post_risks:
        current_risk_id = post_risks[0]["risk_id"]
        posts_for_sidebar = get_posts_by_risk(current_risk_id)

    return render_template(
        "post_detail.html",
        page_title="单帖子分析",
        risks=risks,
        current_page="post",
        current_risk_id=current_risk_id,
        current_post_id=post_id,
        posts_for_sidebar=posts_for_sidebar,
        post=post,
        post_risks=post_risks,
        post_sentiment=get_post_sentiment_summary(post_id),
        comments=get_post_comments(post_id, 10)
    )


# =========================
# APIs
# =========================

@app.route("/api/risk_distribution")
def api_risk_distribution():
    return jsonify(get_risk_distribution())


@app.route("/api/sentiment_overview")
def api_sentiment_overview():
    return jsonify(get_sentiment_overview())


@app.route("/api/risk_sentiment_distribution")
def api_risk_sentiment_distribution():
    return jsonify(get_risk_sentiment_distribution())


@app.route("/api/risk_negative_rate")
def api_risk_negative_rate():
    return jsonify(get_risk_negative_rate())


@app.route("/api/risk_trend")
def api_risk_trend():
    return jsonify(get_risk_trend_monthly(5))


@app.route("/api/risk_cooccurrence")
def api_risk_cooccurrence():
    return jsonify(get_risk_cooccurrence_matrix())


@app.route("/api/risk_heat_scatter")
def api_risk_heat_scatter():
    return jsonify(get_risk_heat_scatter())


@app.route("/api/risk/<int:risk_id>/sentiment")
def api_risk_sentiment(risk_id):
    return jsonify(get_risk_sentiment_summary(risk_id))


@app.route("/api/risk/<int:risk_id>/attitude")
def api_risk_attitude(risk_id):
    return jsonify(get_risk_attitude_summary(risk_id))


@app.route("/api/risk/<int:risk_id>/themes")
def api_risk_themes(risk_id):
    return jsonify(get_risk_theme_summary(risk_id, 10))


@app.route("/api/risk/<int:risk_id>/trend")
def api_risk_trend_detail(risk_id):
    return jsonify(get_risk_trend_detail(risk_id))


@app.route("/api/risk/<int:risk_id>/negative_trend")
def api_risk_negative_trend(risk_id):
    return jsonify(get_risk_negative_trend_detail(risk_id))


@app.route("/api/risk/<int:risk_id>/theme_attitude_matrix")
def api_risk_theme_attitude_matrix(risk_id):
    return jsonify(get_risk_theme_attitude_matrix(risk_id, 8))


@app.route("/api/risk/<int:risk_id>/theme_sentiment_distribution")
def api_risk_theme_sentiment_distribution(risk_id):
    return jsonify(get_risk_theme_sentiment_distribution(risk_id, 8))


@app.route("/api/post/<int:post_id>/sentiment")
def api_post_sentiment(post_id):
    return jsonify(get_post_sentiment_summary(post_id))


if __name__ == "__main__":
    app.run(debug=True)