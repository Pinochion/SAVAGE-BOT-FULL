"""Дополнительная панель голосовых инструментов и семейная рассылка."""
import asyncio
import discord
from discord import app_commands
from discord.ext import commands

from utils.config_db import get_config, set_value, parse_ids
from utils.permissions import is_admin

JOB_KEYS = (
    "job_owner_role_ids", "job_deputy_owner_role_ids", "job_heads_role_ids",
    "job_high_role_ids", "job_recruiter_role_ids", "job_main_role_ids",
    "job_savage_role_ids", "job_new_savage_role_ids",
)

def family_member(member, config):
    role_ids = set()
    for key in JOB_KEYS:
        role_ids.update(parse_ids(config.get(key, "")))
    # Совместимость с текущей основной ролью семьи и настройкой Family.
    role_ids.update(parse_ids(config.get("family_role_ids", "")))
    if config.get("family_role_id"):
        role_ids.update(parse_ids(str(config["family_role_id"])))
    return bool(role_ids.intersection(role.id for role in member.roles))

class MoveMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(placeholder="Выберите участника для «Размутить»", min_values=1, max_values=1, custom_id="admin-tools:unmute-one:user")

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("Нет доступа.", ephemeral=True)
        member = interaction.guild.get_member(self.values[0].id)
        if not member:
            return await interaction.response.send_message("Участник не найден.", ephemeral=True)
        if not member.voice or not member.voice.channel:
            return await interaction.response.send_message("Участник не находится в голосовом канале.", ephemeral=True)
        if not member.voice.self_deaf and not member.voice.deaf:
            return await interaction.response.send_message("У участника не выключен звук на стороне Discord.", ephemeral=True)
        await interaction.response.send_message(f"Запускаю ограниченную попытку вернуть звук для {member.mention}. Процесс остановится, когда участник включит звук или покинет голосовой канал.", ephemeral=True)
        self.cog.bot.loop.create_task(self.cog.nudge_unmute(member))

class VoiceToolsView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        self.add_item(MoveMemberSelect(cog))

    async def interaction_check(self, interaction):
        if not interaction.guild or not is_admin(interaction.user):
            await interaction.response.send_message("У вас нет доступа к панели голосовых инструментов.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📥 Всех ко мне", style=discord.ButtonStyle.primary, custom_id="admin-tools:move-all")
    async def move_all(self, interaction, button):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("Сначала зайдите в голосовой канал.", ephemeral=True)
        target = interaction.user.voice.channel
        moved, failed = 0, 0
        for channel in interaction.guild.voice_channels:
            for member in list(channel.members):
                if member.bot or member.id == interaction.user.id or channel.id == target.id:
                    continue
                try:
                    await member.move_to(target, reason=f"Всех ко мне: {interaction.user}")
                    moved += 1
                except discord.HTTPException:
                    failed += 1
        await interaction.response.send_message(f"Перемещено: {moved}. Не удалось переместить: {failed}.", ephemeral=True)

    @discord.ui.button(label="😴 Спящих в AFK", style=discord.ButtonStyle.secondary, custom_id="admin-tools:move-deaf")
    async def move_deaf(self, interaction, button):
        config = get_config(interaction.guild.id)
        channel_id = config.get("afk_voice_channel_id")
        target = interaction.guild.get_channel(int(channel_id)) if channel_id else interaction.guild.afk_channel
        if not isinstance(target, discord.VoiceChannel):
            return await interaction.response.send_message("Сначала выберите AFK-канал в настройках сервера или настройте его в панели.", ephemeral=True)
        moved, failed = 0, 0
        for channel in interaction.guild.voice_channels:
            if channel.id == target.id:
                continue
            for member in list(channel.members):
                if member.bot or not member.voice or not (member.voice.self_deaf or member.voice.deaf):
                    continue
                try:
                    await member.move_to(target, reason=f"Перемещение в AFK: {interaction.user}")
                    moved += 1
                except discord.HTTPException:
                    failed += 1
        await interaction.response.send_message(f"В AFK перемещено: {moved}. Ошибок: {failed}.", ephemeral=True)

    @discord.ui.button(label="🔊 Размутить всех", style=discord.ButtonStyle.secondary, custom_id="admin-tools:unmute-all")
    async def unmute_all(self, interaction, button):
        members = []
        for channel in interaction.guild.voice_channels:
            for member in channel.members:
                if not member.bot and member.voice and (member.voice.self_deaf or member.voice.deaf):
                    members.append(member)
        if not members:
            return await interaction.response.send_message("Нет участников с выключенным звуком.", ephemeral=True)
        await interaction.response.send_message(f"Начинаю ограниченную обработку {len(members)} участников. Для каждого максимум 8 перемещений; остановка при включении звука.", ephemeral=True)
        self.cog.bot.loop.create_task(self.cog.nudge_many(members))

    @discord.ui.button(label="✉️ Рассылка в ЛС", style=discord.ButtonStyle.success, custom_id="admin-tools:broadcast")
    async def broadcast(self, interaction, button):
        await interaction.response.send_modal(BroadcastModal(self.cog))

class BroadcastModal(discord.ui.Modal, title="Рассылка семье"):
    message_text = discord.ui.TextInput(label="Текст сообщения", style=discord.TextStyle.paragraph, min_length=1, max_length=1800, placeholder="Введите сообщение для участников семьи")

    def __init__(self, cog):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("Нет доступа.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        config = get_config(interaction.guild.id)
        members = [m for m in interaction.guild.members if not m.bot and family_member(m, config)]
        sent = failed = 0
        for member in members:
            try:
                await member.send(str(self.message_text.value))
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
            await asyncio.sleep(0.35)
        await interaction.followup.send(f"Рассылка завершена. Отправлено: {sent}; не доставлено: {failed}.", ephemeral=True)

class AdminTools(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.active_nudges = set()

    async def cog_load(self):
        self.bot.add_view(VoiceToolsView(self))

    async def nudge_many(self, members):
        for member in members:
            try:
                await self.nudge_unmute(member)
            except Exception as exc:
                print(f"[UNMUTE TOOL] {member.id}: {type(exc).__name__}: {exc}")

    async def nudge_unmute(self, member):
        if member.id in self.active_nudges:
            return
        self.active_nudges.add(member.id)
        try:
            original_channel = member.voice.channel if member.voice else None
            if original_channel is None:
                return
            try:
                await member.send("Пожалуйста, включите звук в голосовом канале. Бот временно перемещает вас между каналами и остановится, когда звук будет включён.")
            except discord.HTTPException:
                pass
            guild = member.guild
            alternates = [c for c in guild.voice_channels if c.id != original_channel.id]
            if not alternates:
                return
            attempts = 0
            while attempts < 8:
                await asyncio.sleep(3)
                if not member.voice or not member.voice.channel:
                    break
                if not (member.voice.self_deaf or member.voice.deaf):
                    break
                destination = alternates[attempts % len(alternates)]
                try:
                    await member.move_to(destination, reason="Ограниченная проверка включения звука")
                    await asyncio.sleep(1)
                    if member.voice and member.voice.channel and (member.voice.self_deaf or member.voice.deaf):
                        await member.move_to(original_channel, reason="Возврат в исходный голосовой канал")
                except (discord.Forbidden, discord.HTTPException):
                    break
                attempts += 1
            if member.voice and member.voice.channel and not (member.voice.self_deaf or member.voice.deaf):
                try:
                    await member.move_to(original_channel, reason="Возврат после включения звука")
                except discord.HTTPException:
                    pass
        finally:
            self.active_nudges.discard(member.id)

    @app_commands.command(name="admin-panel-channel", description="Выбрать канал для панелей SAVAGE BOT")
    @app_commands.describe(channel="Текстовый канал, куда публиковать панели")
    async def admin_panel_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("Нет доступа.", ephemeral=True)
        set_value(interaction.guild.id, "admin_panel_channel_id", channel.id)
        await interaction.response.send_message(f"Канал панелей установлен: {channel.mention}.", ephemeral=True)

    @app_commands.command(name="admin-panel-send", description="Опубликовать панели управления и голосовых инструментов")
    async def admin_panel_send(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("Нет доступа.", ephemeral=True)
        config = get_config(interaction.guild.id)
        channel_id = config.get("admin_panel_channel_id")
        channel = interaction.guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message("Сначала выполните /admin-panel-channel и выберите текстовый канал.", ephemeral=True)
        admin_cog = self.bot.get_cog("AdminPanel")
        if admin_cog:
            await channel.send(embed=admin_cog.main_embed(interaction.guild), view=__import__("cogs.admin_panel", fromlist=["AdminPanelView"]).AdminPanelView(admin_cog))
        await channel.send(
            embed=discord.Embed(
                title="🛠️ АДМИН ПАНЕЛЬ",
                description=(
                    "**Всех ко мне** — переместить участников из других голосовых каналов в ваш текущий канал.\n"
                    "**Спящих в AFK** — переместить оглушённых/самооглушённых участников в AFK-канал.\n"
                    "**Размутить** — выбрать одного участника и ограниченно напоминать включить звук перемещениями.\n"
                    "**Размутить всех** — то же самое для всех подходящих участников, максимум 8 циклов на человека.\n"
                    "**Рассылка в ЛС** — отправить текст всем участникам с ролями семейной иерархии."
                ),
                color=discord.Color.dark_teal(),
            ),
            view=VoiceToolsView(self),
        )
        await interaction.response.send_message(f"Панели опубликованы в {channel.mention}.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(AdminTools(bot))
