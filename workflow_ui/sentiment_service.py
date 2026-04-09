from sentiment.sentiment_first_post_deepseek import (
    create_db_connection,
    create_deepseek_client,
    fetch_comments_for_post,
    analyze_comment_with_deepseek,
    save_comment_sentiment_result
)

def run_sentiment_analysis_for_post_id(post_id, reanalyze_all=True):
    conn = create_db_connection()
    client = create_deepseek_client()
    try:
        comments = fetch_comments_for_post(conn, post_id, reanalyze_all)
        if not comments:
            return {"total": 0, "positive": 0, "neutral": 0, "negative": 0}

        positive_count = 0
        neutral_count = 0
        negative_count = 0

        for row in comments:
            comment_id = row["comment_id"]
            comment_content = row.get("comment_content", "")
            comment_theme = row.get("assigned_theme", "")

            sentiment_label, sentiment_score, attitude_type = analyze_comment_with_deepseek(
                client=client,
                comment_theme=comment_theme,
                comment_text=comment_content
            )

            save_comment_sentiment_result(
                conn=conn,
                comment_id=comment_id,
                sentiment_label=sentiment_label,
                sentiment_score=sentiment_score,
                attitude_type=attitude_type
            )
            conn.commit()

            if sentiment_label == "积极":
                positive_count += 1
            elif sentiment_label == "消极":
                negative_count += 1
            else:
                neutral_count += 1

        return {
            "total": len(comments),
            "positive": positive_count,
            "neutral": neutral_count,
            "negative": negative_count
        }
    finally:
        conn.close()