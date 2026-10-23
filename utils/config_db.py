"""Единая конфигурация и SQLite-хранилище SAVAGE BOT."""
import os
import sqlite3
from pathlib import Path
from typing import Optional

DATA_DIR = Path(os.getenv("DATA_DIR", "database"))
DB_PATH = DATA_DIR / "savage.db"

# Схема по умолчанию. Все новые настройки добавляются миграциями без удаления старых данных.
CONFIG_COLUMNS = {
    "admin_role_ids": "TEXT NOT NULL DEFAULT ''",
    "recruiter_role_ids": "TEXT NOT NULL DEFAULT ''",
    "main_role_id": "INTEGER",
    "default_role_id": "INTEGER",
    "academy_role_id": "INTEGER",
    "admin_panel_channel_id": "INTEGER",
    "family_role_id": "INTEGER",
    "family_role_ids": "TEXT NOT NULL DEFAULT ''",
    "contract_channel_id": "INTEGER",
    "contract_role_id": "INTEGER",
    "contract_start_role_ids": "TEXT NOT NULL DEFAULT ''",
    "contract_join_role_ids": "TEXT NOT NULL DEFAULT ''",
    "reaction_channel_id": "INTEGER",
    "reaction_start_role_ids": "TEXT NOT NULL DEFAULT ''",
    "warn_channel_id": "INTEGER",
    "warn_role_ids": "TEXT NOT NULL DEFAULT ''",
    "group_admin_role_ids": "TEXT NOT NULL DEFAULT ''",
    "group_moderator_role_ids": "TEXT NOT NULL DEFAULT ''",
    "group_checked_role_ids": "TEXT NOT NULL DEFAULT ''",
    "group_family_role_ids": "TEXT NOT NULL DEFAULT ''",
    "tier1_role_ids": "TEXT NOT NULL DEFAULT ''",
    "tier2_role_ids": "TEXT NOT NULL DEFAULT ''",
    "tier3_role_ids": "TEXT NOT NULL DEFAULT ''",
    "ticket_category_id": "INTEGER",
    "ticket_log_channel_id": "INTEGER",
    "ticket_staff_role_ids": "TEXT NOT NULL DEFAULT ''",
    "ticket_panel_channel_id": "INTEGER",
    "afk_voice_channel_id": "INTEGER",
    "vzp_role_id": "INTEGER",
    "reaction_vzp_channel_id": "INTEGER",
    "reaction_vzp_start_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_owner_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_deputy_owner_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_heads_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_high_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_recruiter_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_main_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_savage_role_ids": "TEXT NOT NULL DEFAULT ''",
    "job_new_savage_role_ids": "TEXT NOT NULL DEFAULT ''",
    "permissions_json": "TEXT NOT NULL DEFAULT '{}'",
}

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_config_database():
    conn = get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY
            )
        """)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(guild_config)")}
        for name, definition in CONFIG_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE guild_config ADD COLUMN {name} {definition}")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contracts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                starter_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                participants TEXT NOT NULL DEFAULT '',
                channel_id INTEGER,
                message_id INTEGER
            );
            CREATE TABLE IF NOT EXISTS reaction_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL DEFAULT 0,
                creator_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT 'Набор',
                event_time TEXT NOT NULL DEFAULT '',
                slots INTEGER NOT NULL DEFAULT 0,
                participants TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                event_type TEXT NOT NULL DEFAULT 'event',
                created_at TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL,
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS ticket_channels (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            );
        """)
        # Поддерживаем поля, если таблицы созданы старой версией.
        for table, columns in {
            "contracts": {"channel_id": "INTEGER", "message_id": "INTEGER"},
            "reaction_events": {
                "event_type": "TEXT NOT NULL DEFAULT 'event'",
                "created_at": "TEXT NOT NULL DEFAULT ''",
            },
        }.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        conn.commit()
    finally:
        conn.close()

def ensure_guild(guild_id: int):
    conn = get_connection()
    try:
        conn.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (int(guild_id),))
        conn.commit()
    finally:
        conn.close()

def get_config(guild_id: int) -> dict:
    ensure_guild(guild_id)
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM guild_config WHERE guild_id=?", (int(guild_id),)).fetchone()
        return dict(row) if row else {"guild_id": int(guild_id)}
    finally:
        conn.close()

def set_value(guild_id: int, key: str, value):
    if key not in CONFIG_COLUMNS:
        raise ValueError(f"Unknown config key: {key}")
    ensure_guild(guild_id)
    conn = get_connection()
    try:
        conn.execute(f"UPDATE guild_config SET {key}=? WHERE guild_id=?", (value, int(guild_id)))
        conn.commit()
    finally:
        conn.close()

def parse_ids(raw: Optional[str]):
    if not raw:
        return []
    values = raw if isinstance(raw, (list, tuple, set)) else str(raw).split(",")
    result = []
    for part in values:
        try:
            n = int(str(part).strip())
            if n > 0 and n not in result:
                result.append(n)
        except (TypeError, ValueError):
            continue
    return result

def dump_ids(ids):
    return ",".join(str(int(x)) for x in dict.fromkeys(ids) if int(x) > 0)

def user_priority(guild_config: dict, member) -> int:
    """Higher tier wins; return 3/2/1 for Tier 1/2/3, 0 for no tier."""
    for key, priority in (("tier1_role_ids", 3), ("tier2_role_ids", 2), ("tier3_role_ids", 1)):
        role_ids = set(parse_ids(guild_config.get(key, "")))
        if role_ids.intersection(role.id for role in getattr(member, "roles", [])):
            return priority
    # Compatibility with the older main/default/academy configuration.
    role_map = {
        guild_config.get("main_role_id"): 3,
        guild_config.get("default_role_id"): 2,
        guild_config.get("academy_role_id"): 1,
    }
    return max((p for role in getattr(member, "roles", []) for rid, p in role_map.items() if rid and role.id == rid), default=0)
