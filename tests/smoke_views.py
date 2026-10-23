"""Smoke test for individual Discord UI view constructors."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
views = {
    "AdminPanelView": lambda: AdminPanelView(cog),
    "GeneralView": lambda: GeneralView(cog),
    "RoleGroupsView": lambda: RoleGroupsView(cog),
    "TierRolesView": lambda: TierRolesView(cog),
    "HierarchyRolesView": lambda: HierarchyRolesView(cog),
    "HierarchyRolesView2": lambda: HierarchyRolesView2(cog),
    "TicketSettingsView": lambda: TicketSettingsView(cog),
    "TicketExtraSettingsView": lambda: TicketExtraSettingsView(cog),
    "WarnSettingsView": lambda: WarnSettingsView(cog),
    "ContractSettingsView": lambda: ContractSettingsView(cog),
    "ContractFamilyView": lambda: ContractFamilyView(cog),
    "ReactionSettingsView": lambda: ReactionSettingsView(cog),
    "VoiceToolsView": lambda: VoiceToolsView(cog),
    "ContractPanel": lambda: ContractPanel(cog),
    "ActiveContractView": lambda: ActiveContractView(cog, 1),
    "EventView": lambda: EventView(cog, 1),
}
name = sys.argv[1]
view = views[name]()
assert view.children, name
print(f"{name}: OK ({len(view.children)} components)")
