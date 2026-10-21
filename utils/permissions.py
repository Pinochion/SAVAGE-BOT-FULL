from utils.config_db import get_config, parse_ids

GROUP_KEY = {
    "admin": "group_admin_role_ids",
    "moderator": "group_moderator_role_ids",
    "checked": "group_checked_role_ids",
    "family": "group_family_role_ids",
}
DEFAULT_FEATURE_GROUPS = {
    "settings": {"admin"},
    "tickets": {"admin", "moderator"},
    "warns": {"admin", "moderator"},
    "contracts": {"admin", "moderator"},
    "contracts_start": {"admin", "moderator"},
    "contracts_join": {"admin", "moderator", "checked", "family"},
    "reactions": {"admin", "moderator"},
    "voice_panel": {"admin", "moderator"},
    "broadcast": {"admin", "moderator"},
}


def has_any_role(member, role_ids):
    ids = set(parse_ids(role_ids) if isinstance(role_ids, str) else (role_ids or []))
    return bool(ids.intersection(r.id for r in getattr(member, "roles", [])))


def member_groups(member):
    guild = getattr(member, "guild", None)
    if guild is None:
        return set()
    cfg = get_config(guild.id)
    result = set()
    for group, key in GROUP_KEY.items():
        if has_any_role(member, cfg.get(key, "")):
            result.add(group)
    permissions = getattr(member, "guild_permissions", None)
    if permissions and permissions.administrator:
        result.add("admin")
    # Backwards compatibility until the new group roles are configured.
    if not any(cfg.get(key) for key in GROUP_KEY.values()):
        if has_any_role(member, cfg.get("admin_role_ids", "")):
            result.add("admin")
        if has_any_role(member, cfg.get("recruiter_role_ids", "")):
            result.add("moderator")
    return result


def has_group_access(member, feature):
    groups = member_groups(member)
    guild = getattr(member, "guild", None)
    if guild is None:
        return False
    cfg = get_config(guild.id)
    feature = str(feature)
    configured = cfg.get(f"permissions_{feature}")
    if configured is None:
        allowed = DEFAULT_FEATURE_GROUPS.get(feature, {"admin"})
    else:
        allowed = set(parse_ids("")) if not configured.strip() else set(
            part.strip() for part in configured.split(",") if part.strip()
        )
    return bool(groups.intersection(allowed))


def is_admin(member):
    return "admin" in member_groups(member)


def is_recruiter(member):
    return is_admin(member) or "moderator" in member_groups(member)


def can_start_contract(member):
    return has_group_access(member, "contracts_start")


def can_join_contract(member):
    return has_group_access(member, "contracts_join")


def can_start_reaction(member):
    return has_group_access(member, "reactions")
