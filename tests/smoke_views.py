"""Smoke test for Discord UI view constructors."""
import sys
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
groups = {
    "admin": [AdminPanelView, GeneralView, RoleGroupsView, TierRolesView, HierarchyRolesView, HierarchyRolesView2],
    "tickets": [TicketSettingsView, TicketExtraSettingsView, WarnSettingsView],
    "contracts": [ContractSettingsView, ContractFamilyView, ContractPanel, ActiveContractView],
    "reactions": [ReactionSettingsView, EventView],
    "voice": [VoiceToolsView],
}
selected = sys.argv[1] if len(sys.argv) > 1 else "all"
classes = sum(groups.values(), []) if selected == "all" else groups[selected]
views = [cls(cog, 1) if cls in (ActiveContractView, EventView) else cls(cog) for cls in classes]
for view in views:
    assert view.children, type(view).__name__
print(f"{selected}: constructed {len(views)} views")
