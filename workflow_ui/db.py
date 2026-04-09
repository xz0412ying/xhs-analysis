import pymysql
from workflow_ui.config import DB_CONFIG


def get_connection():
    return pymysql.connect(**DB_CONFIG)


def execute_sql(sql, params=None, many=False):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if many:
                cursor.executemany(sql, params)
            else:
                cursor.execute(sql, params)
            conn.commit()
            return cursor.rowcount
    finally:
        conn.close()


def fetch_one(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()
    finally:
        conn.close()


def fetch_all(sql, params=None):
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()
    finally:
        conn.close()