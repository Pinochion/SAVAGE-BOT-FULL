import sqlite3
from pathlib import Path


DATABASE_PATH = Path("database/savage.db")


def get_connection():

    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        DATABASE_PATH
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_database():

    connection = get_connection()

    connection.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    connection.commit()
    connection.close()


def set_setting(key: str, value: str):

    connection = get_connection()

    connection.execute("""
        INSERT INTO settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (key, value))

    connection.commit()
    connection.close()


def get_setting(key: str):

    connection = get_connection()

    result = connection.execute(
        "SELECT value FROM settings WHERE key = ?",
        (key,)
    ).fetchone()

    connection.close()

    if result is None:
        return None

    return result["value"]