import discord
from discord import app_commands
from discord.ext import commands

from utils.config_db import (
    get_config,
    set_value,
    parse_ids,
    dump_ids,
)

from utils.permissions import is_admin

from cogs.tickets import (
    update_setting as ticket_update_setting,
    get_settings as get_ticket_settings,
    get_questions as get_ticket_questions,
    add_question as add_ticket_question,
    delete_question as delete_ticket_question,
)

from cogs.warns import (
    get_warn_staff_roles,
    add_warn_staff_role,
    remove_warn_staff_role,
)


# =========================================================
# HELPERS
# =========================================================

def safe_parse_ids(value):
    if not value:
        return []

    try:
        return parse_ids(value)
    except Exception:
        return []


def safe_role(guild, role_id):
    if not role_id:
        return None

    try:
        return guild.get_role(int(role_id))
    except (TypeError, ValueError):
        return None


def safe_channel(guild, channel_id):
    if not channel_id:
        return None

    try:
        return guild.get_channel(int(channel_id))
    except (TypeError, ValueError):
        return None


def role_mention(guild, role_id):
    role = safe_role(guild, role_id)
    return role.mention if role else "—"


def channel_mention(guild, channel_id):
    channel = safe_channel(guild, channel_id)
    return channel.mention if channel else "—"


def role_mentions(guild, ids):
    result = []

    for role_id in ids:
        role = safe_role(guild, role_id)

        if role:
            result.append(role.mention)
        else:
            result.append(f"`{role_id}`")

    return ", ".join(result) or "—"


# =========================================================
# BASE SELECTS
# =========================================================

class RolesSelect(discord.ui.RoleSelect):

    def __init__(
        self,
        key,
        placeholder,
        min_values=0,
        max_values=10,
        row=None,
    ):
        self.key = key

        super().__init__(
            placeholder=placeholder,
            min_values=min_values,
            max_values=max_values,
            row=row,
            custom_id=f"admin:role:{key}",
        )

    async def callback(self, interaction: discord.Interaction):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Эта настройка доступна только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        ids = [role.id for role in self.values]

        set_value(
            interaction.guild.id,
            self.key,
            dump_ids(ids),
        )

        await interaction.response.send_message(
            "✅ Настройка сохранена.",
            ephemeral=True,
        )


class OneRoleSelect(discord.ui.RoleSelect):

    def __init__(
        self,
        key,
        placeholder,
        row=None,
    ):
        self.key = key

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            row=row,
            custom_id=f"admin:one_role:{key}",
        )

    async def callback(self, interaction: discord.Interaction):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Эта настройка доступна только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        role = self.values[0]

        set_value(
            interaction.guild.id,
            self.key,
            role.id,
        )

        await interaction.response.send_message(
            f"✅ Установлена роль {role.mention}.",
            ephemeral=True,
        )


class ChannelSelect(discord.ui.ChannelSelect):

    def __init__(
        self,
        key,
        placeholder,
        channel_types=(discord.ChannelType.text,),
        row=None,
    ):
        self.key = key

        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            channel_types=list(channel_types),
            row=row,
            custom_id=f"admin:channel:{key}",
        )

    async def callback(self, interaction: discord.Interaction):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Эта настройка доступна только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        channel = self.values[0]

        set_value(
            interaction.guild.id,
            self.key,
            channel.id,
        )

        await interaction.response.send_message(
            f"✅ Канал установлен: {channel.mention}.",
            ephemeral=True,
        )


# =========================================================
# MAIN PANEL
# =========================================================

class AdminPanelView(discord.ui.View):

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="⚙️ Общие настройки",
        style=discord.ButtonStyle.primary,
        custom_id="admin:general",
        row=0,
    )
    async def general(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.general_embed(interaction.guild),
            view=GeneralView(self.cog),
        )

    @discord.ui.button(
        label="🎫 Тикеты",
        style=discord.ButtonStyle.secondary,
        custom_id="admin:tickets",
        row=0,
    )
    async def tickets(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.tickets_embed(interaction.guild),
            view=TicketSettingsView(self.cog),
        )

    @discord.ui.button(
        label="⚠️ Варны",
        style=discord.ButtonStyle.secondary,
        custom_id="admin:warns",
        row=1,
    )
    async def warns(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.warns_embed(interaction.guild),
            view=WarnSettingsView(self.cog),
        )

    @discord.ui.button(
        label="📄 Контракты",
        style=discord.ButtonStyle.secondary,
        custom_id="admin:contracts",
        row=1,
    )
    async def contracts(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.contracts_embed(interaction.guild),
            view=ContractSettingsView(self.cog),
        )

    @discord.ui.button(
        label="🎬 Реакции",
        style=discord.ButtonStyle.secondary,
        custom_id="admin:reactions",
        row=1,
    )
    async def reactions(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.reactions_embed(interaction.guild),
            view=ReactionSettingsView(self.cog),
        )


# =========================================================
# BACK
# =========================================================

class BackView(discord.ui.View):

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    def add_back_button(self):
        self.add_item(
            BackButton(self.cog)
        )


class BackButton(discord.ui.Button):

    def __init__(self, cog):
        self.cog = cog

        super().__init__(
            label="◀️ Назад",
            style=discord.ButtonStyle.secondary,
            custom_id="admin:back",
            row=4,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.main_embed(interaction.guild),
            view=AdminPanelView(self.cog),
        )


# =========================================================
# EXTRA GENERAL SETTINGS: permission groups, tiers and hierarchy
# =========================================================
class OpenRoleConfigButton(discord.ui.Button):
    def __init__(self, cog, label, page, row=0):
        self.cog, self.page = cog, page
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"admin:roles:{page}", row=row)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        views = {"groups": RoleGroupsView, "tiers": TierRolesView, "hierarchy": HierarchyRolesView}
        embeds = {"groups": "Группы доступа", "tiers": "Настройка тиров", "hierarchy": "Должностная иерархия"}
        await interaction.response.edit_message(
            embed=discord.Embed(title=embeds[self.page], description="Выберите роли в списках ниже. Настройки сохраняются автоматически.", color=discord.Color.blurple()),
            view=views[self.page](self.cog),
        )

class RoleGroupsView(BackView):
    def __init__(self, cog):
        super().__init__(cog)
        self.add_item(RolesSelect("group_admin_role_ids", "Группа: Администратор", 0, 10, row=0))
        self.add_item(RolesSelect("group_moderator_role_ids", "Группа: Модератор", 0, 10, row=1))
        self.add_item(RolesSelect("group_checked_role_ids", "Группа: Checked", 0, 10, row=2))
        self.add_item(RolesSelect("group_family_role_ids", "Группа: Family", 0, 10, row=3))
        self.add_back_button()

class TierRolesView(BackView):
    def __init__(self, cog):
        super().__init__(cog)
        self.add_item(RolesSelect("tier1_role_ids", "Tier 1 — высший приоритет", 0, 10, row=0))
        self.add_item(RolesSelect("tier2_role_ids", "Tier 2 — средний приоритет", 0, 10, row=1))
        self.add_item(RolesSelect("tier3_role_ids", "Tier 3 — базовый приоритет", 0, 10, row=2))
        self.add_back_button()

class HierarchyRolesView(BackView):
    def __init__(self, cog):
        super().__init__(cog)
        self.add_item(RolesSelect("job_owner_role_ids", "Иерархия: Owner", 0, 10, row=0))
        self.add_item(RolesSelect("job_deputy_owner_role_ids", "Иерархия: Deputy Owner", 0, 10, row=1))
        self.add_item(RolesSelect("job_heads_role_ids", "Иерархия: Head's", 0, 10, row=2))
        self.add_item(RolesSelect("job_high_role_ids", "Иерархия: High", 0, 10, row=3))
        self.add_back_button()
        self.add_item(HierarchyNextButton(cog))

class HierarchyNextButton(discord.ui.Button):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(label="Следующие роли ▶", style=discord.ButtonStyle.primary, custom_id="admin:roles:hierarchy2", row=4)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        await interaction.response.edit_message(
            embed=discord.Embed(title="📋 Должностная иерархия — часть 2", description="Выберите роли иерархии. Настройки сохраняются автоматически.", color=discord.Color.blurple()),
            view=HierarchyRolesView2(self.cog),
        )

class HierarchyRolesView2(BackView):
    def __init__(self, cog):
        super().__init__(cog)
        self.add_item(RolesSelect("job_recruiter_role_ids", "Иерархия: Recruiter", 0, 10, row=0))
        self.add_item(RolesSelect("job_main_role_ids", "Иерархия: main", 0, 10, row=1))
        self.add_item(RolesSelect("job_savage_role_ids", "Иерархия: savage", 0, 10, row=2))
        self.add_item(RolesSelect("job_new_savage_role_ids", "Иерархия: new savage", 0, 10, row=3))
        self.add_back_button()

# =========================================================
# GENERAL
# =========================================================

class GeneralView(BackView):

    def __init__(self, cog):
        super().__init__(cog)

        self.add_item(OpenRoleConfigButton(cog, "👥 Группы доступа", "groups", row=0))
        self.add_item(OpenRoleConfigButton(cog, "🏆 Тиры", "tiers", row=0))
        self.add_item(OpenRoleConfigButton(cog, "📋 Иерархия", "hierarchy", row=0))
        self.add_item(OneRoleSelect("main_role_id", "Роль MAIN", row=1))
        self.add_item(OneRoleSelect("default_role_id", "Роль DEFAULT", row=2))
        self.add_item(OneRoleSelect("academy_role_id", "Роль ACADEMY", row=3))
        self.add_back_button()


# =========================================================
# TICKETS
# =========================================================

class TicketChannelSelect(ChannelSelect):

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        ticket_update_setting(
            interaction.guild.id,
            self.key,
            self.values[0].id,
        )

        await interaction.response.send_message(
            "✅ Настройка тикетов сохранена.",
            ephemeral=True,
        )


class TicketStaffSelect(RolesSelect):
    def __init__(self):
        super().__init__("ticket_staff_roles", "Роли поддержки тикетов", 0, 10, row=3)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        ticket_update_setting(interaction.guild.id, "staff_role_id", dump_ids([role.id for role in self.values]))
        await interaction.response.send_message("✅ Роли поддержки тикетов сохранены.", ephemeral=True)

class TicketMemberRoleSelect(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder="Роль, выдаваемая кандидату", min_values=1, max_values=1, row=0, custom_id="admin:ticket:member-role")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        ticket_update_setting(interaction.guild.id, "member_role_id", self.values[0].id)
        await interaction.response.send_message(f"✅ Роль кандидата сохранена: {self.values[0].mention}.", ephemeral=True)

class TicketMoreButton(discord.ui.Button):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(label="Доп. настройки ▶", style=discord.ButtonStyle.primary, custom_id="admin:tickets:more", row=4)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        await interaction.response.edit_message(
            embed=discord.Embed(title="🎫 Дополнительные настройки тикетов", description="Выберите роль, которую бот выдаёт кандидату после обработки тикета.", color=discord.Color.blurple()),
            view=TicketExtraSettingsView(self.cog),
        )

class TicketQuestionModal(discord.ui.Modal, title="Настройка вопроса тикета"):
    number = discord.ui.TextInput(label="Номер вопроса (1–5)", placeholder="1", max_length=1)
    question = discord.ui.TextInput(label="Текст вопроса (пусто — удалить)", style=discord.TextStyle.paragraph, required=False, max_length=300, placeholder="Введите новый текст вопроса")

    def __init__(self):
        super().__init__()

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        try:
            number = int(str(self.number.value).strip())
            if number < 1 or number > 5:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("Номер вопроса должен быть от 1 до 5.", ephemeral=True)
        question = str(self.question.value).strip()
        if question:
            add_ticket_question(interaction.guild.id, number, question)
            result = f"Вопрос №{number} сохранён."
        else:
            delete_ticket_question(interaction.guild.id, number)
            result = f"Вопрос №{number} удалён. Если вопросов не осталось, добавьте новый текст."
        await interaction.response.send_message(result, ephemeral=True)

class TicketQuestionsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="❓ Настроить вопросы", style=discord.ButtonStyle.primary, custom_id="admin:tickets:questions", row=1)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        questions = get_ticket_questions(interaction.guild.id)
        text = "\n".join(f"**{row['question_number']}.** {row['question']}" for row in questions) or "Вопросы не настроены."
        await interaction.response.send_message(
            embed=discord.Embed(title="❓ Вопросы заявки", description=text + "\n\nНажмите кнопку, чтобы изменить вопрос по номеру 1–5. Пустой текст удаляет вопрос.", color=discord.Color.blurple()),
            view=TicketQuestionsView(),
            ephemeral=True,
        )

class TicketQuestionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="Изменить / удалить вопрос", style=discord.ButtonStyle.secondary)
    async def edit_question(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TicketQuestionModal())

class TicketExtraSettingsView(BackView):
    def __init__(self, cog):
        super().__init__(cog)
        self.add_item(TicketMemberRoleSelect())
        self.add_item(TicketQuestionsButton())
        self.add_back_button()

class TicketSettingsView(BackView):

    def __init__(self, cog):
        super().__init__(cog)

        self.add_item(
            TicketChannelSelect(
                "panel_channel_id",
                "Канал панели тикетов",
                row=0,
            )
        )

        self.add_item(
            TicketChannelSelect(
                "open_category_id",
                "Категория открытых тикетов",
                (discord.ChannelType.category,),
                row=1,
            )
        )

        self.add_item(
            TicketChannelSelect(
                "closed_category_id",
                "Категория закрытых тикетов",
                (discord.ChannelType.category,),
                row=2,
            )
        )
        self.add_item(TicketStaffSelect())
        self.add_back_button()
        self.add_item(TicketMoreButton(cog))


# =========================================================
# WARNS
# =========================================================

class WarnChannelSelect(ChannelSelect):

    def __init__(self):
        super().__init__(
            "warn_channel_id",
            "Канал варнов",
            row=0,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        set_value(
            interaction.guild.id,
            "warn_channel_id",
            self.values[0].id,
        )

        await interaction.response.send_message(
            "✅ Канал WARN сохранён.",
            ephemeral=True,
        )


class WarnStaffSelect(RolesSelect):

    def __init__(self):
        super().__init__(
            "warn_staff",
            "Роли, выдающие WARN",
            0,
            10,
            row=1,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        old = get_warn_staff_roles(
            interaction.guild.id
        )

        new = [
            role.id
            for role in self.values
        ]

        for role_id in old:
            if role_id not in new:
                remove_warn_staff_role(
                    interaction.guild.id,
                    role_id,
                )

        for role_id in new:
            if role_id not in old:
                add_warn_staff_role(
                    interaction.guild.id,
                    role_id,
                )

        await interaction.response.send_message(
            "✅ Роли WARN сохранены.",
            ephemeral=True,
        )


class WarnSettingsView(BackView):

    def __init__(self, cog):
        super().__init__(cog)

        self.add_item(
            WarnChannelSelect()
        )

        self.add_item(
            WarnStaffSelect()
        )

        self.add_back_button()


# =========================================================
# CONTRACTS
# =========================================================

class ContractSettingsView(BackView):

    def __init__(self, cog):
        super().__init__(cog)

        self.add_item(
            ChannelSelect(
                "contract_channel_id",
                "Канал контрактов",
                row=0,
            )
        )

        self.add_item(
            OneRoleSelect(
                "contract_role_id",
                "Роль контракта",
                row=1,
            )
        )

        self.add_item(
            RolesSelect(
                "family_role_ids",
                "Роли Family для упоминания",
                0,
                10,
                row=2,
            )
        )
        self.add_item(ContractFamilyButton(cog))
        self.add_back_button()


class ContractFamilyButton(discord.ui.Button):

    def __init__(self, cog):
        self.cog = cog

        super().__init__(
            label="👥 Основная роль / семья",
            style=discord.ButtonStyle.primary,
            custom_id="admin:contract_family",
            row=4,
        )

    async def callback(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Нет доступа.",
                ephemeral=True,
            )

        await interaction.response.edit_message(
            embed=self.cog.contract_family_embed(
                interaction.guild
            ),
            view=ContractFamilyView(self.cog),
        )


class ContractFamilyView(BackView):

    def __init__(self, cog):
        super().__init__(cog)

        self.add_item(
            OneRoleSelect(
                "family_role_id",
                "Основная роль / семья",
                row=0,
            )
        )

        self.add_back_button()


# =========================================================
# REACTIONS
# =========================================================

class ReactionSettingsView(BackView):

    def __init__(self, cog):
        super().__init__(cog)

        self.add_item(
            ChannelSelect(
                "reaction_channel_id",
                "Канал обычных реакций",
                row=0,
            )
        )

        self.add_item(
            ChannelSelect(
                "reaction_vzp_channel_id",
                "Канал VZP",
                row=1,
            )
        )
        self.add_item(
            OneRoleSelect(
                "vzp_role_id",
                "Роль для упоминания в VZP",
                row=2,
            )
        )
        self.add_back_button()


# =========================================================
# ADMIN COG
# =========================================================

class AdminPanel(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):

        self.bot.add_view(
            AdminPanelView(self)
        )

        self.bot.add_view(
            GeneralView(self)
        )

        self.bot.add_view(RoleGroupsView(self))
        self.bot.add_view(TierRolesView(self))
        self.bot.add_view(HierarchyRolesView(self))
        self.bot.add_view(HierarchyRolesView2(self))

        self.bot.add_view(
            TicketSettingsView(self)
        )
        self.bot.add_view(TicketExtraSettingsView(self))

        self.bot.add_view(
            WarnSettingsView(self)
        )

        self.bot.add_view(
            ContractSettingsView(self)
        )

        self.bot.add_view(
            ContractFamilyView(self)
        )

        self.bot.add_view(
            ReactionSettingsView(self)
        )

        print(
            "✅ Persistent admin panel views зарегистрированы"
        )

    # =====================================================
    # EMBEDS
    # =====================================================

    def main_embed(self, guild):

        return discord.Embed(
            title="⚙️ Панель администратора",
            description=(
                "Выберите раздел настройки:\n\n"

                "⚙️ **Общие настройки**\n"
                "Роли групп доступа, тиров и иерархии.\n\n"

                "🎫 **Тикеты**\n"
                "Каналы и категории тикетов.\n\n"

                "⚠️ **Варны**\n"
                "Канал и роли для WARN.\n\n"

                "📄 **Контракты**\n"
                "Канал, роли и набор контрактов.\n\n"

                "🎬 **Реакции**\n"
                "Настройки системы реакций."
            ),
            color=discord.Color.blurple(),
        )

    def general_embed(self, guild):
        config = get_config(guild.id)
        def roles_for(key):
            return role_mentions(guild, safe_parse_ids(config.get(key, "")))
        return discord.Embed(
            title="⚙️ Общие настройки",
            description=(
                f"**Группы доступа**\n"
                f"Администратор: {roles_for('group_admin_role_ids')}\n"
                f"Модератор: {roles_for('group_moderator_role_ids')}\n"
                f"Checked: {roles_for('group_checked_role_ids')}\n"
                f"Family: {roles_for('group_family_role_ids')}\n\n"
                f"**Тиры (сортировка ивентов)**\n"
                f"Tier 1: {roles_for('tier1_role_ids')}\n"
                f"Tier 2: {roles_for('tier2_role_ids')}\n"
                f"Tier 3: {roles_for('tier3_role_ids')}\n\n"
                f"**Старые основные роли**\n"
                f"MAIN: {role_mention(guild, config.get('main_role_id'))}\n"
                f"DEFAULT: {role_mention(guild, config.get('default_role_id'))}\n"
                f"ACADEMY: {role_mention(guild, config.get('academy_role_id'))}\n\n"
                "Все участники могут запускать ивенты и записываться. В списке выше Tier 1, затем Tier 2, затем Tier 3; участники без тира — внизу."
            ),
            color=discord.Color.blue(),
        )

    def tickets_embed(self, guild):

        # sqlite3.Row -> dict
        settings = dict(
            get_ticket_settings(guild.id)
        )

        return discord.Embed(
            title="🎫 Настройка тикетов",
            description=(
                f"**Канал панели:**\n"
                f"{channel_mention(guild, settings.get('panel_channel_id'))}\n\n"

                f"**Открытые тикеты:**\n"
                f"{channel_mention(guild, settings.get('open_category_id'))}\n\n"

                f"**Закрытые тикеты:**\n"
                f"{channel_mention(guild, settings.get('closed_category_id'))}"
            ),
            color=discord.Color.blue(),
        )

    def warns_embed(self, guild):

        config = get_config(guild.id)

        warn_roles = get_warn_staff_roles(
            guild.id
        )

        return discord.Embed(
            title="⚠️ Настройки WARN",
            description=(
                f"**Канал WARN:**\n"
                f"{channel_mention(guild, config.get('warn_channel_id'))}\n\n"

                f"**Роли, выдающие WARN:**\n"
                f"{role_mentions(guild, warn_roles)}"
            ),
            color=discord.Color.orange(),
        )

    def contracts_embed(self, guild):

        config = get_config(guild.id)

        start_roles = safe_parse_ids(
            config.get("contract_start_role_ids")
        )

        join_roles = safe_parse_ids(
            config.get("contract_join_role_ids")
        )

        return discord.Embed(
            title="📄 Настройки контрактов",
            description=(
                f"**Канал контрактов:**\n"
                f"{channel_mention(guild, config.get('contract_channel_id'))}\n\n"

                f"**Роль контракта:**\n"
                f"{role_mention(guild, config.get('contract_role_id'))}\n\n"

                f"**Кто может запускать:**\n"
                f"{role_mentions(guild, start_roles)}\n\n"

                f"**Кто может участвовать:**\n"
                f"{role_mentions(guild, join_roles)}\n\n"

                f"**Основная роль / семья:**\n"
                f"{role_mention(guild, config.get('family_role_id'))}"
            ),
            color=discord.Color.blurple(),
        )

    def contract_family_embed(self, guild):

        config = get_config(guild.id)

        return discord.Embed(
            title="👥 Основная роль / семья",
            description=(
                "Укажите роль, которую бот будет "
                "упоминать при запуске контракта.\n\n"

                f"**Текущая роль:** "
                f"{role_mention(guild, config.get('family_role_id'))}"
            ),
            color=discord.Color.blurple(),
        )

    def reactions_embed(self, guild):

        config = get_config(guild.id)

        reaction_roles = safe_parse_ids(
            config.get("reaction_start_role_ids")
        )

        vzp_roles = safe_parse_ids(
            config.get("reaction_vzp_start_role_ids")
        )

        return discord.Embed(
            title="🎬 Настройка Реакций",
            description=(
                f"**Обычные реакции — канал:**\n"
                f"{channel_mention(guild, config.get('reaction_channel_id'))}\n\n"

                f"**Обычные реакции — роли запуска:**\n"
                f"{role_mentions(guild, reaction_roles)}\n\n"

                f"**VZP — канал:**\n"
                f"{channel_mention(guild, config.get('reaction_vzp_channel_id'))}\n\n"

                f"**VZP — роли запуска:**\n"
                f"{role_mentions(guild, vzp_roles)}\n\n"

                "Все могут запускать ивенты и записываться. Список участников сортируется по Tier 1 → Tier 2 → Tier 3; без тира участник ниже."
            ),
            color=discord.Color.blurple(),
        )

    # =====================================================
    # COMMAND
    # =====================================================

    @app_commands.command(
        name="admin",
        description="Открыть панель администратора",
    )
    async def admin(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Команда работает только на сервере.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ У вас нет доступа к панели администратора.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            embed=self.main_embed(interaction.guild),
            view=AdminPanelView(self),
        )


async def setup(bot):
    await bot.add_cog(
        AdminPanel(bot)
    )
