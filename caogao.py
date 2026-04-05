def main():
    conn = None
    try:
        conn = get_connection()
        post = get_post_by_rank(conn, POST_RANK)
        if not post:
            print("posts 表没有数据，无法生成主题。")
            return

        comments = get_post_comments(conn, post["post_id"], limit=800)
        if not comments:
            print(f"post_id={post['post_id']} 没有评论，无法分析。")
            return

        comments_for_llm = select_representative_comments(
            comments,
            keep_count=THEME_COMMENT_SAMPLE_SIZE
        )

        print(
            f"准备分析 post_id={post['post_id']}，"
            f"原始评论 {len(comments)} 条，送入主题生成模型 {len(comments_for_llm)} 条..."
        )

        theme1, theme2, theme3 = call_llm_generate_themes(post, comments_for_llm)
        update_post_themes(conn, post["post_id"], theme1, theme2, theme3)

        print("主题写回成功：")
        print("theme1:", theme1)
        print("theme2:", theme2)
        print("theme3:", theme3)

        print("开始为评论分配主题...")
        updates, theme_count, expressive_count, normal_count = assign_comment_themes_with_llm(
            post, comments, theme1, theme2, theme3
        )
        update_comment_assigned_theme(conn, updates)

        print("评论主题写回成功：")
        print("纯表态评论数：", expressive_count)
        print("需模型分类评论数：", normal_count)
        print("各主题评论量：", dict(theme_count))

    except Exception as e:
        print("执行失败：", str(e))
        print("如缺少依赖，请安装：")
        print("python -m pip install openai pymysql jieba")
    finally:
        if conn:
            conn.close()