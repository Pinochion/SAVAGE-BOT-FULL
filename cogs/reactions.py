"""Ивенты /event и /vzp. Запись открыта всем участникам; порядок списка определяется Tier 1 > Tier 2 > Tier 3."""
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from utils.config_db import get_connection, get_config, parse_ids, user_priority

def utcnow():
    return datetime.now(timezone.utc)

def parse_event_time(raw):
    raw = (raw or "").strip()
    for fmt in ("%H:%M", "%d.%m.%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            parsed = datetime.strptime(raw, fmt)
            if fmt == "%H:%M":
                now = datetime.now()
                parsed = parsed.replace(year=now.year, month=now.month, day=now.day)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError("Укажите время в формате ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ.")

def get_event(event_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM reaction_events WHERE id=?", (int(event_id),)).fetchone()
        return dict(row) if row else None

def get_event_by_message(message_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM reaction_events WHERE message_id=?", (int(message_id),)).fetchone()
        return dict(row) if row else None

def save_ids(event_id, ids):
    with get_connection() as conn:
        conn.execute("UPDATE reaction_events SET participants=? WHERE id=?", (",".join(map(str, dict.fromkeys(int(x) for x in ids))), int(event_id)))

def tier_order(guild, config, user_ids):
    members = []
    for position, user_id in enumerate(user_ids):
        member = guild.get_member(int(user_id))
        if member:
            members.append((user_priority(config, member), position, member))
    members.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in members]

def role_mentions(guild, config, event_type):
    if event_type == "vzp":
        ids = parse_ids(str(config.get("vzp_role_id") or ""))
    else:
        ids = parse_ids(config.get("family_role_ids", ""))
        if not ids:
            ids = parse_ids(config.get("group_family_role_ids", ""))
        if not ids and config.get("family_role_id"):
            ids = parse_ids(str(config["family_role_id"]))
    roles = [guild.get_role(role_id) for role_id in ids]
    return " ".join(role.mention for role in roles if role)

def event_embed(guild, event, config):
    ids = parse_ids(event.get("participants", ""))
    members = tier_order(guild, config, ids)
    title = event.get("title") or ("ВЗП" if event.get("event_type") == "vzp" else "Набор")
    description = f"**Создатель:** <@{event['creator_id']}>\n"
    if event.get("event_time"):
        description += f"**Время:** {event['event_time']}\n"
        if event.get("event_type") == "vzp":
            try:
                dt = datetime.strptime(event["event_time"], "%H:%M")
                dt += timedelta(minutes=20)
                description += f"**Начало ВЗП:** {dt.strftime('%H:%M')}\n"
            except ValueError:
                pass
    description += f"**Участники ({len(ids)}):**\n"
    description += "\n".join(f"{i}. {member.mention}" for i, member in enumerate(members, 1)) if members else "Пока никто не записался."
    if event.get("slots"):
        description += f"\n\n**Мест:** {event['slots']}"
    return discord.Embed(title=f"🎮 {title}", description=description, color=discord.Color.blurple())

class ParticipantModal(discord.ui.Modal):
    target = discord.ui.TextInput(label="Упоминание или ID участника", placeholder="@участник или 123456789", max_length=80)

    def __init__(self, cog, event_id, add):
        super().__init__(title="Добавить участника" if add else "Убрать участника")
        self.cog, self.event_id, self.add = cog, event_id, add

    async def on_submit(self, interaction: discord.Interaction):
        raw = str(self.target.value).strip()
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return await interaction.response.send_message("Не удалось распознать ID. Укажите упоминание или числовой ID.", ephemeral=True)
        await self.cog.change_member(interaction, self.event_id, int(digits), self.add, staff_action=True)

class EventView(discord.ui.View):
    def __init__(self, cog, event_id):
        super().__init__(timeout=None)
        self.cog, self.event_id = cog, int(event_id)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "Записаться": action = "join"
                elif item.label == "Выписаться": action = "leave"
                elif item.label == "Добавить участника": action = "add"
                else: action = "remove"
                item.custom_id = f"savage:event:{action}:{self.event_id}"

    @discord.ui.button(label="Записаться", style=discord.ButtonStyle.success, custom_id="savage:event:join")
    async def join(self, interaction, button):
        await self.cog.change_member(interaction, self.event_id, interaction.user.id, True)

    @discord.ui.button(label="Выписаться", style=discord.ButtonStyle.secondary, custom_id="savage:event:leave")
    async def leave(self, interaction, button):
        await self.cog.change_member(interaction, self.event_id, interaction.user.id, False)

    @discord.ui.button(label="Добавить участника", style=discord.ButtonStyle.primary, custom_id="savage:event:add")
    async def add(self, interaction, button):
        await interaction.response.send_modal(ParticipantModal(self.cog, self.event_id, True))

    @discord.ui.button(label="Убрать участника", style=discord.ButtonStyle.danger, custom_id="savage:event:remove")
    async def remove(self, interaction, button):
        await interaction.response.send_modal(ParticipantModal(self.cog, self.event_id, False))

class EventModal(discord.ui.Modal):
    title_input = discord.ui.TextInput(label="Название набора", placeholder="Например: Реак", max_length=100)
    time_input = discord.ui.TextInput(label="Время", placeholder="ЧЧ:ММ или ДД.ММ.ГГГГ ЧЧ:ММ", max_length=32)
    slots_input = discord.ui.TextInput(label="Количество мест (0 — без лимита)", default="0", max_length=4)

    def __init__(self, cog, event_type):
        super().__init__(title="Создать ВЗП" if event_type == "vzp" else "Создать ивент")
        self.cog, self.event_type = cog, event_type

    async def on_submit(self, interaction: discord.Interaction):
        try:
            event_time = str(self.time_input.value).strip()
            if event_time:
                parse_event_time(event_time)
            slots = int(str(self.slots_input.value).strip() or "0")
            if slots < 0:
                raise ValueError("Количество мест не может быть отрицательным.")
        except ValueError as exc:
            return await interaction.response.send_message(f"Проверьте данные: {exc}", ephemeral=True)
        await self.cog.create_event(interaction, self.event_type, str(self.title_input.value).strip(), event_time, slots)

class Reactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def restore_views(self):
        with get_connection() as conn:
            rows = conn.execute("SELECT id FROM reaction_events WHERE active=1").fetchall()
        for row in rows:
            self.bot.add_view(EventView(self, row["id"]))

    async def create_event(self, interaction, event_type, title, event_time, slots):
        if not interaction.guild:
            return await interaction.response.send_message("Команда работает только на сервере.", ephemeral=True)
        config = get_config(interaction.guild.id)
        channel_id = config.get("reaction_vzp_channel_id") if event_type == "vzp" else config.get("reaction_channel_id")
        channel_id = channel_id or config.get("reaction_channel_id")
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Не найден текстовый канал для ивентов.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO reaction_events(guild_id,channel_id,message_id,creator_id,title,event_time,slots,participants,active,event_type,created_at) VALUES(?,?,?,?,?,?,?,?,1,?,?)",
                (interaction.guild.id, channel.id, 0, interaction.user.id, title or ("ВЗП" if event_type == "vzp" else "Набор"), event_time, slots, str(interaction.user.id), event_type, utcnow().isoformat()),
            )
            event_id = cursor.lastrowid
        event = get_event(event_id)
        mentions = role_mentions(interaction.guild, config, event_type)
        message = await channel.send(
            content=mentions or None,
            embed=event_embed(interaction.guild, event, config),
            view=EventView(self, event_id),
            allowed_mentions=discord.AllowedMentions(roles=True, users=False),
        )
        with get_connection() as conn:
            conn.execute("UPDATE reaction_events SET message_id=? WHERE id=?", (message.id, event_id))
        self.bot.add_view(EventView(self, event_id))
        await interaction.followup.send(f"Ивент опубликован: {message.jump_url}", ephemeral=True)

    async def change_member(self, interaction, event_id, user_id, add, staff_action=False):
        if not interaction.guild:
            return await interaction.response.send_message("Кнопка работает только на сервере.", ephemeral=True)
        event = get_event(event_id)
        if not event or not event["active"]:
            return await interaction.response.send_message("Этот набор уже закрыт.", ephemeral=True)
        if staff_action and not (interaction.user.guild_permissions.manage_events or interaction.user.guild_permissions.administrator):
            return await interaction.response.send_message("Добавлять или убирать других участников могут только модераторы с правом управления событиями.", ephemeral=True)
        member = interaction.guild.get_member(user_id)
        if not member:
            return await interaction.response.send_message("Участник не найден на сервере.", ephemeral=True)
        ids = parse_ids(event.get("participants", ""))
        if add:
            if user_id in ids:
                return await interaction.response.send_message("Участник уже записан.", ephemeral=True)
            if event.get("slots") and len(ids) >= int(event["slots"]):
                return await interaction.response.send_message("Свободных мест больше нет.", ephemeral=True)
            ids.append(user_id)
        else:
            if user_id not in ids:
                return await interaction.response.send_message("Участник не записан.", ephemeral=True)
            ids.remove(user_id)
        save_ids(event_id, ids)
        updated = get_event(event_id)
        await interaction.response.send_message("Список обновлён.", ephemeral=True)
        channel = interaction.guild.get_channel(int(updated["channel_id"]))
        if isinstance(channel, discord.TextChannel) and updated.get("message_id"):
            try:
                msg = await channel.fetch_message(int(updated["message_id"]))
                await msg.edit(embed=event_embed(interaction.guild, updated, get_config(interaction.guild.id)), view=EventView(self, event_id))
            except discord.HTTPException:
                pass

    @app_commands.command(name="event", description="Создать обычный семейный ивент")
    async def event(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventModal(self, "event"))

    @app_commands.command(name="vzp", description="Создать набор ВЗП")
    async def vzp(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EventModal(self, "vzp"))

async def setup(bot):
    await bot.add_cog(Reactions(bot))
