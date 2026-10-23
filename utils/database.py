"""Legacy settings API, sharing the same persistent SQLite file as config_db."""
from utils.config_db import get_connection, DB_PATH

def init_database():
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

def set_setting(key: str, value: str):
    with get_connection() as connection:
        connection.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, str(value)))

def get_setting(key: str):
    with get_connection() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None
