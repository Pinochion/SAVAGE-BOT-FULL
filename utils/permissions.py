from utils.config_db import get_config, parse_ids


def has_any_role(member, role_ids):
    ids=set(parse_ids(role_ids) if isinstance(role_ids,str) else role_ids)
    return bool(ids.intersection(r.id for r in member.roles))


def is_admin(member):
    if member.guild_permissions.administrator:
        return True
    cfg=get_config(member.guild.id)
    return has_any_role(member, cfg.get('admin_role_ids',''))


def is_recruiter(member):
    cfg=get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get('recruiter_role_ids',''))


def can_start_contract(member):
    cfg=get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get('contract_start_role_ids',''))


def can_join_contract(member):
    cfg=get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get('contract_join_role_ids',''))


def can_start_reaction(member):
    cfg=get_config(member.guild.id)
    return is_admin(member) or has_any_role(member, cfg.get('reaction_start_role_ids',''))
