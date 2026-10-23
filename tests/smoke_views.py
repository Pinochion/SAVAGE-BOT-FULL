"""Smoke test: persistent Discord views must construct without component layout errors."""
from cogs.admin_panel import (
    AdminPanelView, GeneralView, RoleGroupsView, TierRolesView,
    HierarchyRolesView, HierarchyRolesView2, TicketSettingsView,
    TicketExtraSettingsView, WarnSettingsView, ContractSettingsView,
    ContractFamilyView, ReactionSettingsView,
)
from cogs.admin_tools import VoiceToolsView
from cogs.contracts import ContractPanel, ActiveContractView
from cogs.reactions import EventView

class Dummy:
    pass

cog = Dummy()
cog.bot = Dummy()
views = [
    AdminPanelView(cog), GeneralView(cog), RoleGroupsView(cog),
    TierRolesView(cog), HierarchyRolesView(cog), HierarchyRolesView2(cog),
    TicketSettingsView(cog), TicketExtraSettingsView(cog), WarnSettingsView(cog),
    ContractSettingsView(cog), ContractFamilyView(cog), ReactionSettingsView(cog),
    VoiceToolsView(cog), ContractPanel(cog), ActiveContractView(cog, 1),
    EventView(cog, 1),
]
for view in views:
    assert len(view.children) > 0, type(view).__name__
print(f"Discord view smoke test OK: {len(views)} views")
