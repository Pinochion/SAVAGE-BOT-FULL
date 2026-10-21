import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path("database/savage.db")


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_config_database():
    conn = get_connection()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS guild_config (
        guild_id INTEGER PRIMARY KEY,
        admin_role_ids TEXT NOT NULL DEFAULT '',
        recruiter_role_ids TEXT NOT NULL DEFAULT '',
        main_role_id INTEGER,
        default_role_id INTEGER,
        academy_role_id INTEGER,
        tier_1_role_id INTEGER,
        tier_2_role_id INTEGER,
        tier_3_role_id INTEGER,
        group_admin_role_ids TEXT NOT NULL DEFAULT '',
        group_moderator_role_ids TEXT NOT NULL DEFAULT '',
        group_checked_role_ids TEXT NOT NULL DEFAULT '',
        group_family_role_ids TEXT NOT NULL DEFAULT '',
        permissions_settings TEXT NOT NULL DEFAULT 'admin',
        permissions_tickets TEXT NOT NULL DEFAULT 'admin,moderator',
        permissions_warns TEXT NOT NULL DEFAULT 'admin,moderator',
        permissions_contracts TEXT NOT NULL DEFAULT 'admin,moderator',
        permissions_contracts_start TEXT NOT NULL DEFAULT 'admin,moderator',
        permissions_contracts_join TEXT NOT NULL DEFAULT 'admin,moderator,checked,family',
        permissions_reactions TEXT NOT NULL DEFAULT 'admin,moderator',
        permissions_voice_panel TEXT NOT NULL DEFAULT 'admin,moderator',
        permissions_broadcast TEXT NOT NULL DEFAULT 'admin,moderator',
        hierarchy_owner_role_id INTEGER,
        hierarchy_deputy_owner_role_id INTEGER,
        hierarchy_heads_role_ids TEXT NOT NULL DEFAULT '',
        hierarchy_high_role_id INTEGER,
        hierarchy_recruiter_role_id INTEGER,
        hierarchy_main_role_id INTEGER,
        hierarchy_savage_role_id INTEGER,
        hierarchy_new_savage_role_id INTEGER,
        admin_panel_channel_id INTEGER,
        family_role_id INTEGER,
        contract_channel_id INTEGER,
        contract_role_id INTEGER,
        contract_start_role_ids TEXT NOT NULL DEFAULT '',
        contract_join_role_ids TEXT NOT NULL DEFAULT '',
        reaction_channel_id INTEGER,
        reaction_vzp_channel_id INTEGER,
        reaction_start_role_ids TEXT NOT NULL DEFAULT '',
        reaction_vzp_start_role_ids TEXT NOT NULL DEFAULT '',
        warn_channel_id INTEGER
    );
    CREATE TABLE IF NOT EXISTS contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        starter_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        ends_at TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        participants TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS reaction_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        channel_id INTEGER NOT NULL,
        message_id INTEGER NOT NULL,
        creator_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        event_time TEXT NOT NULL,
        slots INTEGER NOT NULL,
        participants TEXT NOT NULL DEFAULT '',
        active INTEGER NOT NULL DEFAULT 1
    );
    """)
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(guild_config)")}
    additions = {
        "tier_1_role_id": "INTEGER",
        "tier_2_role_id": "INTEGER",
        "tier_3_role_id": "INTEGER",
        "group_admin_role_ids": "TEXT NOT NULL DEFAULT ''",
        "group_moderator_role_ids": "TEXT NOT NULL DEFAULT ''",
        "group_checked_role_ids": "TEXT NOT NULL DEFAULT ''",
        "group_family_role_ids": "TEXT NOT NULL DEFAULT ''",
        "permissions_settings": "TEXT NOT NULL DEFAULT 'admin'",
        "permissions_tickets": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "permissions_warns": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "permissions_contracts": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "permissions_contracts_start": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "permissions_contracts_join": "TEXT NOT NULL DEFAULT 'admin,moderator,checked,family'",
        "permissions_reactions": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "permissions_voice_panel": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "permissions_broadcast": "TEXT NOT NULL DEFAULT 'admin,moderator'",
        "hierarchy_owner_role_id": "INTEGER",
        "hierarchy_deputy_owner_role_id": "INTEGER",
        "hierarchy_heads_role_ids": "TEXT NOT NULL DEFAULT ''",
        "hierarchy_high_role_id": "INTEGER",
        "hierarchy_recruiter_role_id": "INTEGER",
        "hierarchy_main_role_id": "INTEGER",
        "hierarchy_savage_role_id": "INTEGER",
        "hierarchy_new_savage_role_id": "INTEGER",
        "contract_role_id": "INTEGER",
        "reaction_vzp_channel_id": "INTEGER",
        "reaction_vzp_start_role_ids": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in additions.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE guild_config ADD COLUMN {name} {definition}")
    # Keep old tier roles as a migration source when new tier fields are unset.
    conn.execute("UPDATE guild_config SET tier_1_role_id=COALESCE(tier_1_role_id, main_role_id), tier_2_role_id=COALESCE(tier_2_role_id, default_role_id), tier_3_role_id=COALESCE(tier_3_role_id, academy_role_id)")
    conn.commit()
    conn.close()


def ensure_guild(guild_id: int):
    conn = get_connection()
    conn.execute("INSERT OR IGNORE INTO guild_config (guild_id) VALUES (?)", (guild_id,))
    conn.commit()
    conn.close()


def get_config(guild_id: int) -> dict:
    ensure_guild(guild_id)
    conn = get_connection()
    row = conn.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
    conn.close()
    return dict(row)


def set_value(guild_id: int, key: str, value):
    allowed = {
        "admin_role_ids", "recruiter_role_ids", "main_role_id", "default_role_id",
        "academy_role_id", "tier_1_role_id", "tier_2_role_id", "tier_3_role_id",
        "group_admin_role_ids", "group_moderator_role_ids", "group_checked_role_ids",
        "group_family_role_ids", "permissions_settings", "permissions_tickets",
        "permissions_warns", "permissions_contracts", "permissions_contracts_start",
        "permissions_contracts_join", "permissions_reactions", "permissions_voice_panel",
        "permissions_broadcast", "hierarchy_owner_role_id", "hierarchy_deputy_owner_role_id",
        "hierarchy_heads_role_ids", "hierarchy_high_role_id", "hierarchy_recruiter_role_id",
        "hierarchy_main_role_id", "hierarchy_savage_role_id", "hierarchy_new_savage_role_id",
        "admin_panel_channel_id", "family_role_id", "contract_channel_id", "contract_role_id",
        "contract_start_role_ids", "contract_join_role_ids", "reaction_channel_id",
        "reaction_vzp_channel_id", "reaction_start_role_ids", "reaction_vzp_start_role_ids",
        "warn_channel_id"
    }
    if key not in allowed:
        raise ValueError(f"Unknown config key: {key}")
    ensure_guild(guild_id)
    conn = get_connection()
    conn.execute(f"UPDATE guild_config SET {key}=? WHERE guild_id=?", (value, guild_id))
    conn.commit()
    conn.close()


def parse_ids(raw: Optional[str]):
    if not raw:
        return []
    out = []
    for part in str(raw).split(","):
        try:
            n = int(part.strip())
            if n and n not in out:
                out.append(n)
        except ValueError:
            pass
    return out


def dump_ids(ids):
    return ",".join(str(int(x)) for x in dict.fromkeys(ids))


def user_priority(guild_config: dict, member) -> int:
    role_map = {
        guild_config.get("tier_1_role_id") or guild_config.get("main_role_id"): 3,
        guild_config.get("tier_2_role_id") or guild_config.get("default_role_id"): 2,
        guild_config.get("tier_3_role_id") or guild_config.get("academy_role_id"): 1,
    }
    return max(
        (priority for role in member.roles for role_id, priority in role_map.items() if role_id and role.id == role_id),
        default=0,
    )
