"""Shared SQLite configuration and durable application tables.

The database lives in DATA_DIR (Bothost: /app/data) when configured. Existing
columns are migrated in place so upgrades do not erase server settings.
"""
import os
import sqlite3
from pathlib import Path
from typing import Optional

DATA_DIR = Path(os.getenv("DATA_DIR", "database"))
DB_PATH = DATA_DIR / "savage.db"

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
    "reaction_vzp_channel_id": "INTEGER",
    "reaction_vzp_start_role_ids": "TEXT NOT NULL DEFAULT ''",
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
    "vzp_role_id": "INTEGER",
    "afk_channel_id": "INTEGER",
    "ticket_category_id": "INTEGER",
    "ticket_log_channel_id": "INTEGER",
    "ticket_support_role_ids": "TEXT NOT NULL DEFAULT ''",
    "ticket_staff_role_ids": "TEXT NOT NULL DEFAULT ''",
    "ticket_panel_channel_id": "INTEGER",
    "contract_duration_minutes": "INTEGER NOT NULL DEFAULT 15",
}

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn

def init_config_database():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id INTEGER PRIMARY KEY
            )
        """)
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(guild_config)")}
        for name, sql_type in CONFIG_COLUMNS.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE guild_config ADD COLUMN {name} {sql_type}")
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
                message_id INTEGER NOT NULL,
                creator_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                event_time TEXT NOT NULL,
                slots INTEGER NOT NULL DEFAULT 0,
                participants TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                event_type TEXT NOT NULL DEFAULT 'event',
                created_at TEXT
            );
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1
            );
        """)
        # Add newer optional columns to databases created by older bot versions.
        migrations = {
            "contracts": {"channel_id": "INTEGER", "message_id": "INTEGER"},
            "reaction_events": {"event_type": "TEXT NOT NULL DEFAULT 'event'", "created_at": "TEXT"},
        }
        for table, columns in migrations.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for name, sql_type in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")

def ensure_guild(guild_id: int):
    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (int(guild_id),))

def get_config(guild_id: int) -> dict:
    ensure_guild(guild_id)
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM guild_config WHERE guild_id=?", (int(guild_id),)).fetchone()
        return dict(row) if row else {"guild_id": int(guild_id)}

def set_value(guild_id: int, key: str, value):
    if key not in CONFIG_COLUMNS:
        raise ValueError(f"Unknown config key: {key}")
    ensure_guild(guild_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE guild_config SET {key}=? WHERE guild_id=?", (value, int(guild_id)))

def parse_ids(raw: Optional[str]):
    if raw is None or raw == "":
        return []
    if isinstance(raw, (list, tuple, set)):
        parts = raw
    else:
        parts = str(raw).replace(";", ",").split(",")
    result = []
    for part in parts:
        try:
            value = int(str(part).strip())
            if value > 0 and value not in result:
                result.append(value)
        except (TypeError, ValueError):
            continue
    return result

def dump_ids(ids):
    return ",".join(str(value) for value in dict.fromkeys(int(x) for x in ids if str(x).isdigit() and int(x) > 0))

def user_priority(guild_config: dict, member) -> int:
    """Higher number means earlier in signup ordering: Tier 1 > Tier 2 > Tier 3."""
    tier_keys = (
        ("tier1_role_ids", 3),
        ("tier2_role_ids", 2),
        ("tier3_role_ids", 1),
    )
    role_ids = {role.id for role in getattr(member, "roles", [])}
    for key, priority in tier_keys:
        configured = parse_ids(guild_config.get(key, ""))
        if role_ids.intersection(configured):
            return priority
    # Legacy role columns remain supported during migration.
    legacy = (
        (guild_config.get("main_role_id"), 3),
        (guild_config.get("default_role_id"), 2),
        (guild_config.get("academy_role_id"), 1),
    )
    return max((priority for role_id, priority in legacy if role_id and role_id in role_ids), default=0)
