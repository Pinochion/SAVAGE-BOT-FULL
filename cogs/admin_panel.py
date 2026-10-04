import discord
from discord.ext import commands
from discord import app_commands
from utils.config_db import get_config, set_value, parse_ids, dump_ids, init_config_database
from utils.permissions import is_admin
from cogs.tickets import update_setting as ticket_update_setting, get_settings as get_ticket_settings
from cogs.warns import get_warn_staff_roles, add_warn_staff_role, remove_warn_staff_role


def role_mentions(guild, ids):
    return ', '.join((guild.get_role(i).mention if guild.get_role(i) else f'`{i}`') for i in ids) or '—'


class RolesSelect(discord.ui.RoleSelect):
    def __init__(self, key, placeholder, min_values=0, max_values=10):
        self.key=key
        super().__init__(placeholder=placeholder, min_values=min_values, max_values=max_values)
    async def callback(self, interaction):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.', ephemeral=True)
        ids=[r.id for r in self.values]
        set_value(interaction.guild.id, self.key, dump_ids(ids))
        await interaction.response.send_message('✅ Настройка сохранена.', ephemeral=True)


class OneRoleSelect(discord.ui.RoleSelect):
    def __init__(self, key, placeholder):
        self.key=key
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
    async def callback(self, interaction):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.', ephemeral=True)
        set_value(interaction.guild.id, self.key, self.values[0].id)
        await interaction.response.send_message(f'✅ Установлена роль {self.values[0].mention}.', ephemeral=True)


class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, key, placeholder, channel_types=(discord.ChannelType.text,)):
        self.key=key
        super().__init__(placeholder=placeholder, min_values=1, max_values=1, channel_types=list(channel_types))
    async def callback(self, interaction):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.', ephemeral=True)
        set_value(interaction.guild.id, self.key, self.values[0].id)
        await interaction.response.send_message(f'✅ Канал установлен: {self.values[0].mention}.', ephemeral=True)


class AdminPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog=cog
    @discord.ui.button(label='⚙️ Общие настройки', style=discord.ButtonStyle.primary, custom_id='admin:general')
    async def general(self, interaction, button): await interaction.response.edit_message(embed=self.cog.general_embed(interaction.guild), view=GeneralView(self.cog))
    @discord.ui.button(label='🎫 Тикеты', style=discord.ButtonStyle.secondary, custom_id='admin:tickets')
    async def tickets(self, interaction, button): await interaction.response.edit_message(embed=self.cog.tickets_embed(interaction.guild), view=TicketSettingsView(self.cog))
    @discord.ui.button(label='⚠️ Варны', style=discord.ButtonStyle.secondary, custom_id='admin:warns')
    async def warns(self, interaction, button): await interaction.response.edit_message(embed=self.cog.warns_embed(interaction.guild), view=WarnSettingsView(self.cog))
    @discord.ui.button(label='📄 Контракты', style=discord.ButtonStyle.secondary, custom_id='admin:contracts')
    async def contracts(self, interaction, button): await interaction.response.edit_message(embed=self.cog.contracts_embed(interaction.guild), view=ContractSettingsView(self.cog))
    @discord.ui.button(label='🎬 Реакции', style=discord.ButtonStyle.secondary, custom_id='admin:reactions')
    async def reactions(self, interaction, button): await interaction.response.edit_message(embed=self.cog.reactions_embed(interaction.guild), view=ReactionSettingsView(self.cog))


class BackView(discord.ui.View):
    def __init__(self,cog): super().__init__(timeout=300); self.cog=cog
    @discord.ui.button(label='◀️ Назад', style=discord.ButtonStyle.secondary)
    async def back(self, interaction, button): await interaction.response.edit_message(embed=self.cog.main_embed(interaction.guild), view=AdminPanelView(self.cog))


class GeneralView(BackView):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(RolesSelect('admin_role_ids','Администраторы',0,10))
        self.add_item(RolesSelect('recruiter_role_ids','Рекруты',0,10))
        self.add_item(OneRoleSelect('main_role_id','Роль MAIN'))
        self.add_item(OneRoleSelect('default_role_id','Роль DEFAULT'))
        self.add_item(OneRoleSelect('academy_role_id','Роль ACADEMY'))

class TicketSettingsView(BackView):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(TicketChannelSelect('panel_channel_id','Канал панели тикетов'))
        self.add_item(TicketChannelSelect('open_category_id','Категория открытых тикетов',(discord.ChannelType.category,)))
        self.add_item(TicketChannelSelect('closed_category_id','Категория закрытых тикетов',(discord.ChannelType.category,)))

class TicketChannelSelect(ChannelSelect):
    async def callback(self, interaction):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.',ephemeral=True)
        ticket_update_setting(interaction.guild.id,self.key,self.values[0].id)
        await interaction.response.send_message('✅ Настройка тикетов сохранена.',ephemeral=True)

class WarnSettingsView(BackView):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(WarnChannelSelect('warn_channel_id','Канал варнов'))
        self.add_item(WarnStaffSelect('warn_staff','Роли, выдающие WARN',0,10))

class WarnChannelSelect(ChannelSelect):
    async def callback(self, interaction):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.',ephemeral=True)
        set_value(interaction.guild.id,'warn_channel_id',self.values[0].id)
        await interaction.response.send_message('✅ Канал варнов сохранён.',ephemeral=True)

class WarnStaffSelect(RolesSelect):
    async def callback(self, interaction):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.',ephemeral=True)
        old=get_warn_staff_roles(interaction.guild.id)
        new=[r.id for r in self.values]
        for rid in old:
            if rid not in new: remove_warn_staff_role(interaction.guild.id,rid)
        for rid in new:
            if rid not in old: add_warn_staff_role(interaction.guild.id,rid)
        await interaction.response.send_message('✅ Роли WARN сохранены.',ephemeral=True)

class ContractSettingsView(BackView):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(ChannelSelect('contract_channel_id','Канал контрактов'))
        self.add_item(RolesSelect('contract_start_role_ids','Кто может начинать набор',1,10))
        self.add_item(RolesSelect('contract_join_role_ids','Кто может заходить в набор',1,10))
        self.add_item(OneRoleSelect('family_role_id','Общая роль фамы'))

class ReactionSettingsView(BackView):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(ChannelSelect('reaction_channel_id','Канал реакций'))
        self.add_item(RolesSelect('reaction_start_role_ids','Кто может запускать набор',1,10))


class AdminPanel(commands.Cog):
    def __init__(self, bot): self.bot=bot; init_config_database()
    def main_embed(self,guild): return discord.Embed(title='⚙️ S A V A G E — ADMIN PANEL',description='Выберите раздел настройки ниже.',color=discord.Color.blurple())
    def general_embed(self,guild):
        c=get_config(guild.id); return discord.Embed(title='⚙️ Общие настройки',description=f"**Администраторы:** {role_mentions(guild,parse_ids(c['admin_role_ids']))}\n**Рекруты:** {role_mentions(guild,parse_ids(c['recruiter_role_ids']))}\n**MAIN:** {guild.get_role(c['main_role_id']).mention if c['main_role_id'] and guild.get_role(c['main_role_id']) else '—'}\n**DEFAULT:** {guild.get_role(c['default_role_id']).mention if c['default_role_id'] and guild.get_role(c['default_role_id']) else '—'}\n**ACADEMY:** {guild.get_role(c['academy_role_id']).mention if c['academy_role_id'] and guild.get_role(c['academy_role_id']) else '—'}\n\nПриоритет: **MAIN → DEFAULT → ACADEMY**",color=discord.Color.blurple())
    def tickets_embed(self,guild):
        c=get_ticket_settings(guild.id); return discord.Embed(title='🎫 Настройка тикетов',description=f"**Панель:** <#{c['panel_channel_id']}>\n**Открытые:** <#{c['open_category_id']}>\n**Закрытые:** <#{c['closed_category_id']}>",color=discord.Color.blurple())
    def warns_embed(self,guild):
        c=get_config(guild.id); return discord.Embed(title='⚠️ Настройка варнов',description=f"**Канал варнов:** <#{c['warn_channel_id']}>\n**Роли WARN:** {role_mentions(guild,get_warn_staff_roles(guild.id))}",color=discord.Color.orange())
    def contracts_embed(self,guild):
        c=get_config(guild.id); return discord.Embed(title='📄 Настройка контрактов',description=f"**Канал:** <#{c['contract_channel_id']}>\n**Старт:** {role_mentions(guild,parse_ids(c['contract_start_role_ids']))}\n**Участие:** {role_mentions(guild,parse_ids(c['contract_join_role_ids']))}\n**Роль фамы:** {guild.get_role(c['family_role_id']).mention if c['family_role_id'] and guild.get_role(c['family_role_id']) else '—'}\n**Таймер:** 15 минут",color=discord.Color.blurple())
    def reactions_embed(self,guild):
        c=get_config(guild.id); return discord.Embed(title='🎬 Настройка реакций',description=f"**Канал:** <#{c['reaction_channel_id']}>\n**Запуск:** {role_mentions(guild,parse_ids(c['reaction_start_role_ids']))}\n**Иерархия:** MAIN → DEFAULT → ACADEMY",color=discord.Color.blurple())
    @app_commands.command(name='admin-panel',description='Открыть или опубликовать панель настройки фамы')
    @app_commands.describe(channel='Канал, куда опубликовать постоянную админ-панель')
    async def admin_panel(self, interaction, channel: discord.TextChannel | None = None):
        if not is_admin(interaction.user): return await interaction.response.send_message('❌ Нет доступа.', ephemeral=True)
        if channel:
            set_value(interaction.guild.id,'admin_panel_channel_id',channel.id)
            embed=self.main_embed(interaction.guild)
            await channel.send(embed=embed,view=AdminPanelView(self))
            return await interaction.response.send_message(f'✅ Панель опубликована в {channel.mention}.',ephemeral=True)
        await interaction.response.send_message(embed=self.main_embed(interaction.guild),view=AdminPanelView(self),ephemeral=True)

async def setup(bot): await bot.add_cog(AdminPanel(bot))
