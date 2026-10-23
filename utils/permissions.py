"""Centralized permission helpers. Event signup/start is intentionally open to everyone."""
from utils.config_db import get_config, parse_ids

def has_any_role(member, role_ids):
    ids = set(parse_ids(role_ids))
    return bool(ids.intersection(role.id for role in getattr(member, "roles", [])))

def is_admin(member):
    if getattr(getattr(member, "guild_permissions", None), "administrator", False):
        return True
    cfg = get_config(member.guild.id)
    return has_any_role(member, cfg.get("group_admin_role_ids") or cfg.get("admin_role_ids", ""))

def is_moderator(member):
    cfg = get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get("group_moderator_role_ids", ""))

def is_checked(member):
    cfg = get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get("group_checked_role_ids", ""))

def is_family(member):
    cfg = get_config(member.guild.id)
    ids = parse_ids(cfg.get("group_family_role_ids", "")) + parse_ids(cfg.get("family_role_ids", ""))
    if cfg.get("family_role_id"):
        ids.append(int(cfg["family_role_id"]))
    return has_any_role(member, ids)

def is_recruiter(member):
    cfg = get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get("recruiter_role_ids", ""))

def can_start_contract(member):
    cfg = get_config(member.guild.id)
    configured = cfg.get("contract_start_role_ids", "")
    return is_admin(member) or not parse_ids(configured) or has_any_role(member, configured)

def can_join_contract(member):
    cfg = get_config(member.guild.id)
    configured = cfg.get("contract_join_role_ids", "")
    return is_admin(member) or not parse_ids(configured) or has_any_role(member, configured)

def can_start_reaction(member):
    # Explicit requirement: all server members may start and join events.
    return True
