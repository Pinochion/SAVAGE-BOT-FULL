"""Единые проверки прав. Запуск и участие в ивентах доступны всем участникам."""
from utils.config_db import get_config, parse_ids

def has_any_role(member, role_ids):
    ids = set(parse_ids(role_ids) if isinstance(role_ids, str) else (role_ids or []))
    return bool(ids.intersection(role.id for role in getattr(member, "roles", [])))

def is_admin(member):
    if getattr(getattr(member, "guild_permissions", None), "administrator", False):
        return True
    guild = getattr(member, "guild", None)
    if guild is None:
        return False
    cfg = get_config(guild.id)
    return has_any_role(member, cfg.get("group_admin_role_ids", "")) or has_any_role(member, cfg.get("admin_role_ids", ""))

def is_recruiter(member):
    if is_admin(member):
        return True
    guild = getattr(member, "guild", None)
    return bool(guild and has_any_role(member, get_config(guild.id).get("recruiter_role_ids", "")))

def can_start_contract(member):
    return bool(getattr(member, "guild", None))

def can_join_contract(member):
    return bool(getattr(member, "guild", None))

def can_start_reaction(member):
    return bool(getattr(member, "guild", None))

def can_manage_warns(member):
    if is_admin(member):
        return True
    guild = getattr(member, "guild", None)
    if guild is None:
        return False
    cfg = get_config(guild.id)
    return has_any_role(member, cfg.get("warn_role_ids", "")) or has_any_role(member, cfg.get("recruiter_role_ids", ""))
