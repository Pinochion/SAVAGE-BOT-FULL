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
        admin_panel_channel_id INTEGER,
        family_role_id INTEGER,
        contract_channel_id INTEGER,
        contract_start_role_ids TEXT NOT NULL DEFAULT '',
        contract_join_role_ids TEXT NOT NULL DEFAULT '',
        reaction_channel_id INTEGER,
        reaction_start_role_ids TEXT NOT NULL DEFAULT '',
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
        'admin_role_ids','recruiter_role_ids','main_role_id','default_role_id','academy_role_id',
        'admin_panel_channel_id','family_role_id','contract_channel_id','contract_start_role_ids',
        'contract_join_role_ids','reaction_channel_id','reaction_start_role_ids','warn_channel_id'
    }
    if key not in allowed:
        raise ValueError(f'Unknown config key: {key}')
    ensure_guild(guild_id)
    conn = get_connection()
    conn.execute(f"UPDATE guild_config SET {key}=? WHERE guild_id=?", (value, guild_id))
    conn.commit(); conn.close()


def parse_ids(raw: Optional[str]):
    if not raw:
        return []
    out=[]
    for part in str(raw).split(','):
        try:
            n=int(part.strip())
            if n and n not in out: out.append(n)
        except ValueError:
            pass
    return out


def dump_ids(ids):
    return ','.join(str(int(x)) for x in dict.fromkeys(ids))


def user_priority(guild_config: dict, member) -> int:
    role_map = {
        guild_config.get('main_role_id'): 3,
        guild_config.get('default_role_id'): 2,
        guild_config.get('academy_role_id'): 1,
    }
    return max((p for r in member.roles for rid,p in role_map.items() if rid and r.id == rid), default=0)
