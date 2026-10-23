"""Совместимый интерфейс к общей базе savage.db."""
from utils.config_db import DB_PATH, get_connection as _get_connection

DATABASE_PATH = DB_PATH

def get_connection():
    return _get_connection()

def init_database():
    connection = get_connection()
    try:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        connection.commit()
    finally:
        connection.close()

def set_setting(key: str, value: str):
    connection = get_connection()
    try:
        connection.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        connection.commit()
    finally:
        connection.close()

def get_setting(key: str):
    connection = get_connection()
    try:
        result = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return result["value"] if result else None
    finally:
        connection.close()
