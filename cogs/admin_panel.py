import asyncio
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.config_db import get_config, set_value, parse_ids, dump_ids, GROUPS, FEATURES
from utils.permissions import is_admin, has_group_access, member_groups
from cogs.tickets import (
    update_setting as ticket_update_setting,
    get_settings as get_ticket_settings,
    get_staff_role_ids,
    save_staff_role_ids,
    get_questions as get_ticket_questions,
    add_question as add_ticket_question,
    delete_question as delete_ticket_question,
    PANEL_IMAGE_URL,
    TicketPanelView,
)
from cogs.warns import get_warn_staff_roles, add_warn_staff_role, remove_warn_staff_role

GROUP_LABELS = {'admin':'Администратор','moderator':'Модератор','checked':'Checked','family':'Family'}
FEATURE_LABELS = {'settings':'Настройки панели','tickets':'Тикеты','warns':'WARN','contracts':'Управление контрактами','contracts_start':'Запуск контрактов','contracts_join':'Запись в контракты','reactions':'Реакции','voice_panel':'Голосовая админ-панель','broadcast':'Рассылка в ЛС'}
HIERARCHY = [
    ('hierarchy_owner_role_id','Owner'), ('hierarchy_deputy_owner_role_id','Deputy Owner'),
    ('hierarchy_heads_role_ids',"Head's"), ('hierarchy_high_role_id','High'),
    ('hierarchy_recruiter_role_id','Recruiter'), ('hierarchy_main_role_id','main'),
    ('hierarchy_savage_role_id','savage'), ('hierarchy_new_savage_role_id','new savage')]


def role(guild, rid):
    try: return guild.get_role(int(rid)) if rid else None
    except (ValueError, TypeError): return None


def channel(guild, cid):
    try: return guild.get_channel(int(cid)) if cid else None
    except (ValueError, TypeError): return None


def mention_role(guild, rid):
    obj=role(guild,rid); return obj.mention if obj else '—'


def mention_channel(guild, cid):
    obj=channel(guild,cid); return obj.mention if obj else '—'


def roles_text(guild, ids):
    return ', '.join((role(guild, x).mention if role(guild, x) else f'`{x}`') for x in ids) or '—'


class RoleSetting(discord.ui.RoleSelect):
    def __init__(self, key, placeholder, multi=False, row=0):
        self.key=key; self.multi=multi
        super().__init__(placeholder=placeholder, min_values=0, max_values=25 if multi else 1, row=row, custom_id=f'savage:role:{key}')
    async def callback(self, interaction):
        if not interaction.guild or not has_group_access(interaction.user, 'settings'):
            return await interaction.response.send_message('❌ Нет доступа к настройкам.', ephemeral=True)
        ids=[r.id for r in self.values]
        set_value(interaction.guild.id,self.key,dump_ids(ids) if self.multi else (ids[0] if ids else None))
        await interaction.response.send_message('✅ Роль сохранена.',ephemeral=True)


class ChannelSetting(discord.ui.ChannelSelect):
    def __init__(self,key,placeholder,types=None,row=0):
        self.key=key
        super().__init__(placeholder=placeholder,min_values=1,max_values=1,channel_types=types or [discord.ChannelType.text],row=row,custom_id=f'savage:channel:{key}')
    async def callback(self,interaction):
        if not interaction.guild or not has_group_access(interaction.user,'settings'):
            return await interaction.response.send_message('❌ Нет доступа к настройкам.',ephemeral=True)
        set_value(interaction.guild.id,self.key,self.values[0].id)
        await interaction.response.send_message(f'✅ Сохранено: {self.values[0].mention}',ephemeral=True)


class PermissionSetting(discord.ui.Select):
    def __init__(self,feature,row=0,scope='general'):
        self.feature=feature; self.scope=scope
        options=[discord.SelectOption(label=GROUP_LABELS[g],value=g,description=f'Разрешить группе: {GROUP_LABELS[g]}') for g in GROUPS]
        super().__init__(placeholder=f'Кто может: {FEATURE_LABELS[feature]}',min_values=1,max_values=4,options=options,row=row,custom_id=f'savage:permission:{feature}:{scope}')
    async def callback(self,interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message('❌ Только администратор может менять права.',ephemeral=True)
        set_value(interaction.guild.id,f'permissions_{self.feature}',','.join(self.values))
        await interaction.response.send_message('✅ Права доступа сохранены.',ephemeral=True)


class BackButton(discord.ui.Button):
    def __init__(self, destination='manage', source='back'):
        self.destination=destination
        super().__init__(label='◀️ Назад',style=discord.ButtonStyle.secondary,row=4,custom_id=f'savage:back:{destination}:{source}')
    async def callback(self,interaction):
        cog=interaction.client.get_cog('AdminPanel')
        if not interaction.guild or not has_group_access(interaction.user,'settings'):
            return await interaction.response.send_message('❌ Нет доступа.',ephemeral=True)
        if self.destination=='general': embed,view=cog.general_embed(interaction.guild),GeneralMenu(cog)
        else: embed,view=cog.manage_embed(interaction.guild),ManagePanel(cog)
        await interaction.response.edit_message(embed=embed,view=view)


class ManagePanel(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None); self.cog=cog
    async def open(self,i,feature):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        mapping={'general':(self.cog.general_embed(i.guild),GeneralMenu(self.cog)),
                 'tickets':(self.cog.tickets_embed(i.guild),TicketSettings(self.cog)),
                 'warns':(self.cog.warns_embed(i.guild),WarnSettings(self.cog)),
                 'contracts':(self.cog.contracts_embed(i.guild),ContractSettings(self.cog)),
                 'reactions':(self.cog.reactions_embed(i.guild),ReactionSettings(self.cog))}
        e,v=mapping[feature]; await i.response.edit_message(embed=e,view=v)
    @discord.ui.button(label='⚙️ Общие настройки',style=discord.ButtonStyle.primary,row=0,custom_id='savage:manage:general')
    async def general(self,i,b): await self.open(i,'general')
    @discord.ui.button(label='🎫 Тикеты',style=discord.ButtonStyle.secondary,row=0,custom_id='savage:manage:tickets')
    async def tickets(self,i,b): await self.open(i,'tickets')
    @discord.ui.button(label='⚠️ WARN',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:manage:warns')
    async def warns(self,i,b): await self.open(i,'warns')
    @discord.ui.button(label='📄 Контракты',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:manage:contracts')
    async def contracts(self,i,b): await self.open(i,'contracts')
    @discord.ui.button(label='🎬 Реакции',style=discord.ButtonStyle.secondary,row=2,custom_id='savage:manage:reactions')
    async def reactions(self,i,b): await self.open(i,'reactions')


class GeneralMenu(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None); self.cog=cog
    async def go(self,i,view):
        if not i.guild or not has_group_access(i.user,'settings'): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        await i.response.edit_message(embed=view.embed(i.guild) if hasattr(view,'embed') else self.cog.general_embed(i.guild),view=view)
    @discord.ui.button(label='👥 Группы ролей',style=discord.ButtonStyle.primary,row=0,custom_id='savage:general:groups')
    async def groups(self,i,b): await self.go(i,GroupRoles(self.cog))
    @discord.ui.button(label='🏛️ Иерархия ролей',style=discord.ButtonStyle.secondary,row=0,custom_id='savage:general:hierarchy')
    async def hierarchy(self,i,b): await self.go(i,HierarchyRoles(self.cog))
    @discord.ui.button(label='🎖️ Tiers',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:general:tiers')
    async def tiers(self,i,b): await self.go(i,TierRoles(self.cog))
    @discord.ui.button(label='🔐 Права доступа',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:general:permissions')
    async def permissions(self,i,b): await self.go(i,PermissionSettings(self.cog))
    @discord.ui.button(label='◀️ В главное меню',style=discord.ButtonStyle.secondary,row=4,custom_id='savage:general:back')
    async def back(self,i,b):
        if not i.guild or not has_group_access(i.user,'settings'): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        await i.response.edit_message(embed=self.cog.manage_embed(i.guild),view=ManagePanel(self.cog))


class SimpleSettings(discord.ui.View):
    def __init__(self,cog): super().__init__(timeout=None); self.cog=cog
    def add_back(self,destination='general',source=None): self.add_item(BackButton(destination, source or self.__class__.__name__.lower()))


class GroupRoles(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        for row,(key,label) in enumerate([('group_admin_role_ids','Администратор'),('group_moderator_role_ids','Модератор'),('group_checked_role_ids','Checked'),('group_family_role_ids','Family')]): self.add_item(RoleSetting(key,f'Роли группы: {label}',multi=True,row=row))
        self.add_back()
    def embed(self,guild):
        c=get_config(guild.id)
        return discord.Embed(title='👥 Группы ролей',description='Назначьте Discord-роль каждой группе. Эти группы используются для выдачи доступа к функциям.',color=discord.Color.blurple()).add_field(name='Администратор',value=mention_role(guild,c.get('group_admin_role_id'))).add_field(name='Модератор',value=mention_role(guild,c.get('group_moderator_role_id'))).add_field(name='Checked',value=mention_role(guild,c.get('group_checked_role_id'))).add_field(name='Family',value=mention_role(guild,c.get('group_family_role_id')))


class HierarchyRoles(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        # Split across pages because Discord permits only five component rows per view.
        for row,(key,label) in enumerate(HIERARCHY[:4]): self.add_item(RoleSetting(key,f'{label} — роль',multi=key.endswith('_ids'),row=row))
        self.add_item(BackButton('general','hierarchy1'))
        self.add_item(HierarchyPageButton(cog,1))
    def embed(self,guild): return discord.Embed(title='🏛️ Иерархия ролей — 1/2',description='Owner → Deputy Owner → Head\'s → High. Эти должности сохраняются отдельно от групп доступа и Tiers.',color=discord.Color.blurple())

class HierarchyPageButton(discord.ui.Button):
    def __init__(self,cog,page): self.cog=cog; self.page=page; super().__init__(label='Далее ▶️' if page == 1 else '◀️ Назад к первой',style=discord.ButtonStyle.primary,row=4,custom_id=f'savage:hierarchy:page:{page}')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        view=HierarchyRolesPage2(self.cog); await i.response.edit_message(embed=view.embed(i.guild),view=view)

class HierarchyRolesPage2(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        for row,(key,label) in enumerate(HIERARCHY[4:]): self.add_item(RoleSetting(key,f'{label} — роль',row=row))
        self.add_item(BackButton('general','hierarchy2'))
        self.add_item(HierarchyPageButton(cog,0))
    def embed(self,guild): return discord.Embed(title='🏛️ Иерархия ролей — 2/2',description='Recruiter → main → savage → new savage.',color=discord.Color.blurple())


class TierRoles(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        for row,(key,label) in enumerate([('tier_1_role_id','Tier 1 — высший приоритет'),('tier_2_role_id','Tier 2 — средний приоритет'),('tier_3_role_id','Tier 3 — низший приоритет')]): self.add_item(RoleSetting(key,label,row=row))
        self.add_back()
    def embed(self,guild):
        c=get_config(guild.id)
        return discord.Embed(title='🎖️ Tiers',description=f"Tier 1: {mention_role(guild,c.get('tier_1_role_id'))}\nTier 2: {mention_role(guild,c.get('tier_2_role_id'))}\nTier 3: {mention_role(guild,c.get('tier_3_role_id'))}\n\nTier 1 выше Tier 2, Tier 2 выше Tier 3. Без тира участник располагается ниже всех.",color=discord.Color.blurple())

class PermissionSettings(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(PermissionSetting('settings',0)); self.add_item(PermissionSetting('tickets',1)); self.add_item(PermissionSetting('warns',2)); self.add_item(PermissionSetting('contracts',3)); self.add_item(BackButton('general'))
        # Other feature permissions are available on the second page button.
        self.add_item(PermissionPageButton(cog))
    def embed(self,guild): return discord.Embed(title='🔐 Права доступа — 1/2',description='Выберите группы, которым разрешены настройки и управление тикетами, WARN и контрактами. Несколько групп могут иметь доступ.',color=discord.Color.blurple())
class PermissionPageButton(discord.ui.Button):
    def __init__(self,cog): self.cog=cog; super().__init__(label='Далее ▶️',style=discord.ButtonStyle.primary,row=4,custom_id='savage:permissions:page2')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        v=PermissionSettingsPage2(self.cog); await i.response.edit_message(embed=v.embed(i.guild),view=v)
class PermissionSettingsPage2(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog); self.add_item(PermissionSetting('reactions',0)); self.add_item(PermissionSetting('voice_panel',1)); self.add_item(PermissionSetting('broadcast',2)); self.add_item(BackButton('general','permissions2'))
    def embed(self,guild): return discord.Embed(title='🔐 Права доступа — 2/2',description='Настройте группы, которым разрешены реакции, голосовая админ-панель и рассылка в ЛС.',color=discord.Color.blurple())


class TicketSettings(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(TicketChannelSetting('panel_channel_id','Канал панели заявок',row=0))
        self.add_item(TicketChannelSetting('open_category_id','Категория открытых заявок',[discord.ChannelType.category],row=1))
        self.add_item(TicketChannelSetting('closed_category_id','Категория закрытых заявок',[discord.ChannelType.category],row=2))
        self.add_item(TicketStaffRolesSetting('Роли сотрудников / рекрутов',row=3))
        self.add_item(TicketPageButton(cog,page=1))
        self.add_back('manage')
    def embed(self,guild):
        return self.cog.tickets_embed(guild)

class TicketChannelSetting(ChannelSetting):
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        ticket_update_setting(i.guild.id,self.key,self.values[0].id)
        await i.response.send_message('✅ Настройка тикетов сохранена.',ephemeral=True)

class TicketStaffRolesSetting(discord.ui.RoleSelect):
    def __init__(self, placeholder, row=0):
        super().__init__(placeholder=placeholder,min_values=0,max_values=25,row=row,custom_id='savage:ticket:staff-roles')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        save_staff_role_ids(i.guild.id,[r.id for r in self.values])
        await i.response.send_message('✅ Роли сотрудников тикетов сохранены.',ephemeral=True)

class TicketMemberRoleSetting(discord.ui.RoleSelect):
    def __init__(self):
        super().__init__(placeholder='Роль принятого участника',min_values=0,max_values=1,row=0,custom_id='savage:ticket:member-role')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        role_id=self.values[0].id if self.values else None
        ticket_update_setting(i.guild.id,'member_role_id',role_id)
        await i.response.send_message('✅ Роль принятого участника сохранена.',ephemeral=True)

class TicketPageButton(discord.ui.Button):
    def __init__(self,cog,page):
        self.cog=cog; self.page=page
        super().__init__(label='Вопросы и роль принятого ▶️' if page==1 else '◀️ К настройкам каналов',style=discord.ButtonStyle.primary,row=4,custom_id=f'savage:ticket:page:{page}')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        view=TicketSettingsPage2(self.cog) if self.page==1 else TicketSettings(self.cog)
        await i.response.edit_message(embed=view.embed(i.guild),view=view)

class TicketQuestionsModal(discord.ui.Modal):
    def __init__(self,guild_id):
        super().__init__(title='Вопросы анкеты тикетов')
        self.guild_id=guild_id
        current={int(row['question_number']):row['question'] for row in get_ticket_questions(guild_id)}
        self.fields_by_number={}
        for number in range(1,6):
            field=discord.ui.TextInput(
                label=f'Вопрос {number}',
                default=current.get(number,'')[:200] or None,
                max_length=200,
                required=False,
                placeholder='Пустое поле отключает вопрос'
            )
            self.fields_by_number[number]=field
            self.add_item(field)
    async def on_submit(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        for number,field in self.fields_by_number.items():
            question=(field.value or '').strip()
            if question:
                add_ticket_question(i.guild.id,number,question)
            else:
                delete_ticket_question(i.guild.id,number)
        await i.response.send_message('✅ Вопросы анкеты сохранены. Пустые поля отключены.',ephemeral=True)

class TicketSettingsPage2(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(TicketMemberRoleSetting())
        self.add_item(TicketQuestionsButton())
        self.add_item(TicketPublishButton())
        self.add_item(TicketPageButton(cog,page=2))
        self.add_back('manage')
    def embed(self,guild):
        settings=get_ticket_settings(guild.id)
        role=guild.get_role(settings['member_role_id']) if settings['member_role_id'] else None
        questions=get_ticket_questions(guild.id)
        question_text='\n'.join(f"{row['question_number']}. {row['question']}" for row in questions) or 'Не настроены'
        return discord.Embed(title='🎫 Тикеты — дополнительные настройки',description=f'**Роль принятого:** {role.mention if role else "Не настроено"}\n\n**Вопросы анкеты:**\n{question_text}\n\nЗдесь можно изменить вопросы и опубликовать панель подачи заявки.',color=discord.Color.blue())

class TicketQuestionsButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='📝 Настроить вопросы анкеты',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:ticket:questions')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        await i.response.send_modal(TicketQuestionsModal(i.guild.id))

class TicketPublishButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='📨 Опубликовать панель заявок',style=discord.ButtonStyle.success,row=2,custom_id='savage:ticket:publish')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        settings=get_ticket_settings(i.guild.id)
        channel_id=settings['panel_channel_id']
        channel=i.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel,discord.TextChannel):
            return await i.response.send_message('❌ Сначала выберите текстовый канал панели на первой странице настроек тикетов.',ephemeral=True)
        tickets_cog=i.client.get_cog('Tickets')
        if tickets_cog is None:
            return await i.response.send_message('❌ Модуль тикетов не загружен.',ephemeral=True)
        embed=discord.Embed(
            title='ТИКЕТЫ В СЕМЬЮ SAVAGE',
            description=(
                '## Требования:\n'
                '> Возраст 15+\n'
                '> Активность и участие во фракционном/семейном контенте.\n'
                '> Готовность сменить фамилию.\n'
                '> Персонаж с 5 уровнем.\n\n'
                '## Что мы можем предложить:\n'
                '> Дружный состав семьи.\n'
                '> Опытный high стак.\n'
                '> Блат во фракциях.\n'
                '> Премиальный автопарк.\n\n'
                'Нажми кнопку **«Подать заявку»** ниже, чтобы заполнить анкету.'
            ),
            color=discord.Color.from_rgb(0,0,0)
        )
        embed.set_image(url=PANEL_IMAGE_URL)
        embed.set_footer(text='S A V A G E • Система заявок')
        await channel.send(embed=embed,view=TicketPanelView(tickets_cog))
        await i.response.send_message(f'✅ Панель заявок опубликована в {channel.mention}.',ephemeral=True)
class WarnSettings(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(ChannelSetting('warn_channel_id','Канал WARN',row=0))
        self.add_item(RoleSetting('warn_access_role_id','Право доступа к WARN: роль и выше',row=1))
        self.add_back('manage')
class WarnRoleSetting(RoleSetting):
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        if self.key=='warn_staff':
            old=set(get_warn_staff_roles(i.guild.id)); new={r.id for r in self.values}
            for rid in old-new: remove_warn_staff_role(i.guild.id,rid)
            for rid in new-old: add_warn_staff_role(i.guild.id,rid)
        else: set_value(i.guild.id,self.key,dump_ids([r.id for r in self.values]) if self.multi else self.values[0].id)
        await i.response.send_message('✅ Роли WARN сохранены.',ephemeral=True)
class ContractSettings(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog); self.add_item(ChannelSetting('contract_channel_id','Канал контрактов',row=0)); self.add_item(RoleSetting('contract_role_id','Роль семьи для упоминания',row=1)); self.add_item(PermissionSetting('contracts_start',row=2,scope='contractsettings')); self.add_item(PermissionSetting('contracts_join',row=3,scope='contractsettings'));  self.add_back('manage')
class ReactionSettings(SimpleSettings):
    def __init__(self,cog):
        super().__init__(cog)
        self.add_item(ChannelSetting('reaction_channel_id','Канал обычных реакций',row=0))
        self.add_item(ChannelSetting('reaction_vzp_channel_id','Канал VZP',row=1))
        self.add_item(RoleSetting('reaction_access_role_id','Право запуска наборов: роль и выше',row=2))
        self.add_item(PublishReactionPanelButton(cog,row=3))
        self.add_back('manage')

class PublishReactionPanelButton(discord.ui.Button):
    def __init__(self,cog,row=3):
        self.cog=cog
        super().__init__(label='📨 Опубликовать панель запуска наборов',style=discord.ButtonStyle.success,row=row,custom_id='savage:reaction:publish-panel')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'settings'):
            return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        cfg=get_config(i.guild.id)
        channel_id=cfg.get('reaction_channel_id') or cfg.get('reaction_vzp_channel_id')
        channel=i.guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel,discord.TextChannel):
            return await i.response.send_message('❌ Сначала настройте канал обычных реакций или VZP.',ephemeral=True)
        embed=discord.Embed(
            title='🎬 Запуск набора',
            description='Нажмите кнопку нужного типа набора. Запуск доступен роли, выбранной в настройках реакций, и всем ролям выше.',
            color=discord.Color.blurple()
        )
        await channel.send(embed=embed,view=ReactionLaunchView(self.cog))
        await i.response.send_message(f'✅ Панель запуска опубликована в {channel.mention}.',ephemeral=True)

class ReactionLaunchView(discord.ui.View):
    def __init__(self,cog):
        super().__init__(timeout=None)
        self.add_item(StartReactionButton(cog,'default',row=0))
        self.add_item(StartReactionButton(cog,'vzp',row=0))

class StartReactionButton(discord.ui.Button):
    def __init__(self,cog,reaction_type,row=3):
        self.cog=cog; self.reaction_type=reaction_type
        label='▶️ Запустить обычный набор' if reaction_type=='default' else '▶️ Запустить VZP'
        super().__init__(label=label,style=discord.ButtonStyle.success if reaction_type=='default' else discord.ButtonStyle.secondary,row=row,custom_id=f'savage:reaction:start:{reaction_type}')
    async def callback(self,i):
        from utils.permissions import can_start_reaction
        from cogs.reactions import ReactionModal
        if not i.guild or not can_start_reaction(i.user):
            return await i.response.send_message('❌ Нет права запускать наборы. Проверьте роль доступа в настройках реакций.',ephemeral=True)
        await i.response.send_modal(ReactionModal(i.client.get_cog('Reactions'),self.reaction_type))


class BroadcastModal(discord.ui.Modal,title='Рассылка участникам семьи'):
    message=discord.ui.TextInput(label='Текст сообщения',style=discord.TextStyle.paragraph,max_length=1900,required=True)
    def __init__(self,cog): super().__init__(); self.cog=cog
    async def on_submit(self,i):
        if not i.guild or not has_group_access(i.user,'broadcast'): return await i.response.send_message('❌ Нет доступа к рассылке.',ephemeral=True)
        cfg=get_config(i.guild.id); role_ids=set()
        for key,_ in HIERARCHY:
            val=cfg.get(key); role_ids.update(parse_ids(val) if key.endswith('_ids') else ([int(val)] if val else []))
        for key in ('group_family_role_ids',):
            if cfg.get(key): role_ids.update(parse_ids(cfg[key]))
        members=[m for m in i.guild.members if not m.bot and any(r.id in role_ids for r in m.roles)]
        await i.response.send_message(f'📨 Начинаю рассылку {len(members)} участникам. Результат пришлю после завершения.',ephemeral=True)
        sent=failed=0
        for member in members:
            try: await member.send(self.message.value); sent+=1
            except (discord.Forbidden,discord.HTTPException): failed+=1
            await asyncio.sleep(0.15)
        try: await i.followup.send(f'✅ Рассылка завершена. Доставлено: {sent}; не доставлено: {failed}.',ephemeral=True)
        except discord.HTTPException: pass


class VoiceTargetSelect(discord.ui.UserSelect):
    def __init__(self,cog): self.cog=cog; super().__init__(placeholder='Выберите участника',min_values=1,max_values=1,row=0,custom_id='savage:voice:target')
    async def callback(self,i):
        if not i.guild or not has_group_access(i.user,'voice_panel'): return await i.response.send_message('❌ Нет доступа.',ephemeral=True)
        target=self.values[0]
        if not isinstance(target,discord.Member) or not target.voice or not target.voice.channel: return await i.response.send_message('Участник не находится в голосовом канале.',ephemeral=True)
        if not target.voice.self_deaf: return await i.response.send_message('❌ Нельзя использовать функцию: у участника включены наушники. Нужен выключенный звук в наушниках (deaf).',ephemeral=True)
        self.cog.start_unmute_cycle(target)
        try: await target.send('🔔 Пожалуйста, включи наушники (сними self-deaf). Бот будет перемещать тебя между голосовыми каналами и вернёт в исходный канал, когда ты включишь наушники.')
        except discord.HTTPException: pass
        await i.response.send_message(f'🔔 Участнику {target.mention} отправлено уведомление. Перемещения начаты; после снятия deaf он вернётся в исходный канал.',ephemeral=True)

class VoicePanelView(discord.ui.View):
    def __init__(self,cog): super().__init__(timeout=None); self.cog=cog
    async def allowed(self,i):
        if not i.guild: await i.response.send_message('Только на сервере.',ephemeral=True); return False
        if not has_group_access(i.user,'voice_panel'): await i.response.send_message('❌ Нет доступа к голосовой админ-панели.',ephemeral=True); return False
        return True
    @discord.ui.button(label='📣 Всех ко мне',style=discord.ButtonStyle.primary,row=0,custom_id='savage:voice:pull')
    async def pull(self,i,b):
        if not await self.allowed(i): return
        if not i.user.voice or not i.user.voice.channel: return await i.response.send_message('Сначала зайди в голосовой канал.',ephemeral=True)
        target=i.user.voice.channel; moved=0
        for vc in i.guild.voice_channels:
            if vc.id == target.id: continue
            for m in list(vc.members):
                if m.id!=i.user.id:
                    try: await m.move_to(target,reason=f'Всех ко мне: {i.user}'); moved+=1
                    except discord.HTTPException: pass
        await i.response.send_message(f'✅ Перемещено участников: {moved}.',ephemeral=True)
    @discord.ui.button(label='😴 Спящих в AFK',style=discord.ButtonStyle.secondary,row=0,custom_id='savage:voice:afk')
    async def afk(self,i,b):
        if not await self.allowed(i): return
        afk=i.guild.afk_channel
        if not isinstance(afk,discord.VoiceChannel): return await i.response.send_message('Сначала настройте AFK-канал в общих настройках сервера Discord или в конфигурации бота.',ephemeral=True)
        moved=0
        for vc in i.guild.voice_channels:
            if vc.id==afk.id: continue
            for m in list(vc.members):
                if m.voice and m.voice.self_deaf:
                    try: await m.move_to(afk,reason='Перемещение deaf-участника в AFK'); moved+=1
                    except discord.HTTPException: pass
        await i.response.send_message(f'✅ В AFK перемещено: {moved}.',ephemeral=True)
    @discord.ui.button(label='🔔 Размутить',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:voice:unmute')
    async def unmute(self,i,b):
        if not await self.allowed(i): return
        await i.response.send_message('Выберите участника с выключенными наушниками:',view=discord.ui.View(timeout=60).add_item(VoiceTargetSelect(self.cog)),ephemeral=True)
    @discord.ui.button(label='🔔 Размутить всех',style=discord.ButtonStyle.secondary,row=1,custom_id='savage:voice:unmuteall')
    async def unmuteall(self,i,b):
        if not await self.allowed(i): return
        targets=[m for vc in i.guild.voice_channels for m in vc.members if m.voice and (m.voice.deaf or m.voice.self_deaf)]
        for m in targets:
            self.cog.start_unmute_cycle(m)
            try: await m.send('🔔 Пожалуйста, включи наушники (сними self-deaf). Бот будет перемещать тебя между голосовыми каналами и вернёт в исходный канал, когда ты включишь наушники.')
            except discord.HTTPException: pass
        await i.response.send_message(f'🔔 Запущен цикл для {len(targets)} участников с выключенными наушниками. Участники с включёнными наушниками не затронуты.',ephemeral=True)
    @discord.ui.button(label='✉️ Рассылка в ЛС',style=discord.ButtonStyle.primary,row=2,custom_id='savage:voice:broadcast')
    async def broadcast(self,i,b):
        if not i.guild or not has_group_access(i.user,'broadcast'): return await i.response.send_message('❌ Нет доступа к рассылке.',ephemeral=True)
        await i.response.send_modal(BroadcastModal(self.cog))


class AdminPanel(commands.Cog):
    def __init__(self,bot): self.bot=bot; self.unmute_targets={}; self.unmute_task.start()
    async def cog_load(self):
        for view in (ManagePanel(self),GeneralMenu(self),GroupRoles(self),HierarchyRoles(self),HierarchyRolesPage2(self),TierRoles(self),PermissionSettings(self),PermissionSettingsPage2(self),TicketSettings(self),TicketSettingsPage2(self),WarnSettings(self),ContractSettings(self),ReactionSettings(self),ReactionLaunchView(self),VoicePanelView(self)):
            self.bot.add_view(view)
    def manage_embed(self,g): return discord.Embed(title='⚙️ УПРАВЛЕНИЕ БОТОМ',description='Настройки тикетов, WARN, контрактов, реакций и прав доступа. Выберите раздел ниже.',color=discord.Color.blurple())
    def voice_embed(self,g): return discord.Embed(title='🛠️ АДМИН ПАНЕЛЬ',description='📣 **Всех ко мне** — переместить участников в ваш голосовой канал.\n😴 **Спящих в AFK** — переместить участников с выключенными наушниками в AFK.\n🔔 **Размутить** — выбрать участника, уведомить его и перемещать до снятия deaf.\n🔔 **Размутить всех** — то же самое для всех участников с выключенными наушниками.\n✉️ **Рассылка в ЛС** — отправить текст участникам семейства.',color=discord.Color.dark_teal())
    def general_embed(self,g):
        c=get_config(g.id)
        return discord.Embed(title='⚙️ Общие настройки',description=f"**Группы ролей**\nАдминистратор: {roles_text(g,parse_ids(c.get('group_admin_role_ids')))}\nМодератор: {roles_text(g,parse_ids(c.get('group_moderator_role_ids')))}\nChecked: {roles_text(g,parse_ids(c.get('group_checked_role_ids')))}\nFamily: {roles_text(g,parse_ids(c.get('group_family_role_ids')))}\n\n**Иерархия**\n"+' → '.join(f"{name}: {mention_role(g,c.get(key)) if not key.endswith('_ids') else roles_text(g,parse_ids(c.get(key)))}" for key,name in HIERARCHY)+f"\n\n**Tiers**\nTier 1: {mention_role(g,c.get('tier_1_role_id'))}\nTier 2: {mention_role(g,c.get('tier_2_role_id'))}\nTier 3: {mention_role(g,c.get('tier_3_role_id'))}",color=discord.Color.blue())
    def tickets_embed(self,g):
        s=dict(get_ticket_settings(g.id))
        staff_text=roles_text(g,get_staff_role_ids(g.id))
        member_role=mention_role(g,s.get('member_role_id'))
        return discord.Embed(title='🎫 Настройка тикетов',description=f"Канал панели: {mention_channel(g,s.get('panel_channel_id'))}\nОткрытая категория: {mention_channel(g,s.get('open_category_id'))}\nЗакрытая категория: {mention_channel(g,s.get('closed_category_id'))}\nРоли сотрудников: {staff_text}\nРоль принятого: {member_role}",color=discord.Color.blue())
    def warns_embed(self,g):
        c=get_config(g.id)
        return discord.Embed(title='⚠️ Настройки WARN',description=f"Канал WARN: {mention_channel(g,c.get('warn_channel_id'))}\nПраво выдавать и снимать WARN: {mention_role(g,c.get('warn_access_role_id'))} и все роли выше.",color=discord.Color.orange())
    def contracts_embed(self,g):
        c=get_config(g.id)
        return discord.Embed(title='📄 Настройки контрактов',description=f"Канал: {mention_channel(g,c.get('contract_channel_id'))}\nРоль семьи: {mention_role(g,c.get('contract_role_id') or c.get('family_role_id'))}\n\nПрава запуска и записи настраиваются ниже по группам ролей.",color=discord.Color.blurple())
    def reactions_embed(self,g):
        c=get_config(g.id)
        return discord.Embed(title='🎬 Настройки реакций',description=f"Обычные реакции: {mention_channel(g,c.get('reaction_channel_id'))}\nVZP: {mention_channel(g,c.get('reaction_vzp_channel_id'))}\nРоль запуска наборов: {mention_role(g,c.get('reaction_access_role_id'))} и все роли выше.\n\nНажмите «Опубликовать панель запуска наборов», чтобы участники с нужной ролью могли запускать наборы кнопками.",color=discord.Color.blurple())
    def start_unmute_cycle(self,member):
        if member.voice and member.voice.self_deaf: self.unmute_targets[member.id]=member.voice.channel.id
    def cog_unload(self):
        self.unmute_task.cancel()

    @tasks.loop(seconds=3)
    async def unmute_task(self):
        for uid,original_channel_id in list(self.unmute_targets.items()):
            member=None
            for guild in self.bot.guilds:
                member=guild.get_member(uid)
                if member: break
            if not member or not member.voice:
                self.unmute_targets.pop(uid,None); continue
            if not member.voice.self_deaf:
                original=member.guild.get_channel(original_channel_id)
                if isinstance(original,discord.VoiceChannel):
                    try: await member.move_to(original,reason='Вернуть после снятия deaf')
                    except discord.HTTPException: pass
                self.unmute_targets.pop(uid,None); continue
            channels=[vc for vc in member.guild.voice_channels if vc.id!=member.voice.channel.id]
            if channels:
                try: await member.move_to(channels[0],reason='Побуждение снять deaf по запросу админ-панели')
                except discord.HTTPException: pass
    @unmute_task.before_loop
    async def before_unmute_task(self): await self.bot.wait_until_ready()
    @app_commands.command(name='admin-panel-channel',description='Установить канал админ-панелей')
    @app_commands.describe(channel='Текстовый канал, где будут опубликованы панели')
    async def admin_panel_channel(self,i:discord.Interaction,channel:discord.TextChannel):
        if not i.guild or not is_admin(i.user): return await i.response.send_message('❌ Только администратор может настроить канал.',ephemeral=True)
        set_value(i.guild.id,'admin_panel_channel_id',channel.id); await i.response.send_message(f'✅ Канал админ-панелей: {channel.mention}',ephemeral=True)
    @app_commands.command(name='admin-panel-send',description='Опубликовать две админ-панели в настроенном канале')
    async def admin_panel_send(self,i:discord.Interaction):
        if not i.guild or not is_admin(i.user): return await i.response.send_message('❌ Только администратор может отправить панели.',ephemeral=True)
        target=channel(i.guild,get_config(i.guild.id).get('admin_panel_channel_id'))
        if not isinstance(target,discord.TextChannel): return await i.response.send_message('❌ Сначала выполни /admin-panel-channel и выбери канал.',ephemeral=True)
        await target.send(embed=self.manage_embed(i.guild),view=ManagePanel(self))
        await target.send(embed=self.voice_embed(i.guild),view=VoicePanelView(self))
        await i.response.send_message(f'✅ Две панели отправлены в {target.mention}.',ephemeral=True)

async def setup(bot): await bot.add_cog(AdminPanel(bot))