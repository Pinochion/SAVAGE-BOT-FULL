"""Voice and family utilities exposed through an administrator panel."""
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.config_db import get_config
from utils.permissions import is_admin

log = logging.getLogger(__name__)
UNMUTE_TIMEOUT = 45
UNMUTE_INTERVAL = 3


def configured_family_role_ids(guild):
    cfg = get_config(guild.id)
    values = []
    for key in (
        "group_family_role_ids", "family_role_ids", "tier1_role_ids",
        "tier2_role_ids", "tier3_role_ids",
    ):
        raw = str(cfg.get(key) or "")
        for part in raw.replace(";", ",").split(","):
            if part.strip().isdigit():
                values.append(int(part.strip()))
    for key in ("family_role_id", "main_role_id", "default_role_id", "academy_role_id"):
        try:
            if cfg.get(key):
                values.append(int(cfg[key]))
        except (TypeError, ValueError):
            pass
    return set(values)


class MemberToUnmuteSelect(discord.ui.UserSelect):
    def __init__(self, cog):
        self.cog = cog
        super().__init__(placeholder="Выбери участника с выключенным звуком", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        member = self.values[0]
        if not isinstance(member, discord.Member):
            member = interaction.guild.get_member(member.id)
        if not member or not member.voice or not member.voice.channel:
            return await interaction.response.send_message("Участник не находится в голосовом канале.", ephemeral=True)
        if not member.voice.self_deaf:
            return await interaction.response.send_message("У участника не выключен звук в Discord.", ephemeral=True)
        await interaction.response.send_message(
            f"Запускаю напоминание для {member.mention} на срок до {UNMUTE_TIMEOUT} секунд.",
            ephemeral=True,
        )
        asyncio.create_task(self.cog.nudge_until_undeafened(member))


class VoiceAdminView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_admin(self, interaction):
        if not interaction.guild:
            await interaction.response.send_message("❌ Только на сервере.", ephemeral=True)
            return False
        if not is_admin(interaction.user):
            await interaction.response.send_message("❌ Нет доступа к панели.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📢 Всех ко мне", style=discord.ButtonStyle.primary, custom_id="voiceadmin:move_all", row=0)
    async def move_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_admin(interaction):
            return
        member = interaction.user
        if not isinstance(member, discord.Member) or not member.voice or not member.voice.channel:
            return await interaction.response.send_message("Сначала зайди в голосовой канал.", ephemeral=True)
        destination = member.voice.channel
        await interaction.response.defer(ephemeral=True, thinking=True)
        moved, failed = 0, 0
        for voice_channel in interaction.guild.voice_channels:
            for target in list(voice_channel.members):
                if target.id == member.id or target.bot or target.voice is None:
                    continue
                try:
                    await target.move_to(destination, reason=f"Voice admin: move all requested by {member}")
                    moved += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
        await interaction.followup.send(f"Готово: перемещено {moved}, не удалось переместить {failed}.", ephemeral=True)

    @discord.ui.button(label="😴 Спящих в AFK", style=discord.ButtonStyle.secondary, custom_id="voiceadmin:afk", row=0)
    async def move_sleepers(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_admin(interaction):
            return
        afk = interaction.guild.afk_channel
        if not afk:
            return await interaction.response.send_message("AFK-канал не настроен в параметрах сервера Discord.", ephemeral=True)
        await interaction.response.defer(ephemeral=True, thinking=True)
        moved, failed = 0, 0
        for channel in interaction.guild.voice_channels:
            for member in list(channel.members):
                if member.bot or not member.voice or not member.voice.self_deaf:
                    continue
                if channel.id == afk.id:
                    continue
                try:
                    await member.move_to(afk, reason="Voice admin: move self-deafened members to AFK")
                    moved += 1
                except (discord.Forbidden, discord.HTTPException):
                    failed += 1
        await interaction.followup.send(f"В AFK перемещено: {moved}. Ошибок: {failed}.", ephemeral=True)

    @discord.ui.button(label="🔊 Размутить участника", style=discord.ButtonStyle.success, custom_id="voiceadmin:unmute_one", row=1)
    async def unmute_one(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_admin(interaction):
            return
        view = discord.ui.View(timeout=60)
        view.add_item(MemberToUnmuteSelect(self.cog))
        await interaction.response.send_message("Выбери участника. Бот будет напоминать перемещением между каналами, пока он не включит звук (максимум 45 секунд).", view=view, ephemeral=True)

    @discord.ui.button(label="🔊 Размутить всех", style=discord.ButtonStyle.success, custom_id="voiceadmin:unmute_all", row=1)
    async def unmute_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_admin(interaction):
            return
        targets = [m for c in interaction.guild.voice_channels for m in c.members if not m.bot and m.voice and m.voice.self_deaf]
        await interaction.response.send_message(f"Запускаю напоминание для {len(targets)} участников (не более {UNMUTE_TIMEOUT} секунд).", ephemeral=True)
        for target in targets:
            asyncio.create_task(self.cog.nudge_until_undeafened(target))

    @discord.ui.button(label="✉️ Рассылка в ЛС", style=discord.ButtonStyle.primary, custom_id="voiceadmin:dm", row=2)
    async def broadcast(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.interaction_admin(interaction):
            return
        await interaction.response.send_modal(BroadcastModal(self.cog))


class BroadcastModal(discord.ui.Modal, title="Рассылка семье"):
    message = discord.ui.TextInput(label="Текст сообщения", style=discord.TextStyle.paragraph, min_length=1, max_length=1800, required=True)

    def __init__(self, cog):
        super().__init__(timeout=180)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа.", ephemeral=True)
        role_ids = configured_family_role_ids(interaction.guild)
        targets = {
            member.id: member
            for role in interaction.guild.roles if role.id in role_ids
            for member in role.members
            if not member.bot
        }
        await interaction.response.send_message(f"Рассылка запущена для {len(targets)} участников. Итог пришлю отдельным сообщением.", ephemeral=True)
        sent, failed = 0, 0
        for member in targets.values():
            try:
                await member.send(self.message.value)
                sent += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1
            await asyncio.sleep(0.15)
        try:
            await interaction.followup.send(f"Рассылка завершена. Отправлено: {sent}; не доставлено: {failed}.", ephemeral=True)
        except discord.HTTPException:
            pass


class VoiceAdmin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def nudge_until_undeafened(self, member: discord.Member):
        """Move a self-deafened member between their original and another voice channel, with a hard time limit."""
        guild = member.guild
        original_channel_id = member.voice.channel.id if member.voice and member.voice.channel else None
        if not original_channel_id:
            return
        started = asyncio.get_running_loop().time()
        alternate = next((c for c in guild.voice_channels if c.id != original_channel_id), None)
        if not alternate:
            try:
                await member.send("Пожалуйста, включи звук в Discord, чтобы продолжить участие в голосовом канале.")
            except discord.HTTPException:
                pass
            return
        current_target = alternate
        while asyncio.get_running_loop().time() - started < UNMUTE_TIMEOUT:
            member = guild.get_member(member.id)
            if not member or not member.voice or not member.voice.channel or not member.voice.self_deaf:
                return
            try:
                await member.move_to(current_target, reason="Voice admin: request to enable Discord audio")
            except (discord.Forbidden, discord.HTTPException):
                return
            await asyncio.sleep(UNMUTE_INTERVAL)
            current_target = guild.get_channel(original_channel_id) if current_target.id != original_channel_id else alternate
            if current_target is None:
                return
        try:
            await member.send("Напоминание закончено. Включи звук в Discord вручную, если хочешь участвовать в голосовом канале.")
        except discord.HTTPException:
            pass

    @app_commands.command(name="voice-admin-panel", description="Открыть панель управления голосовыми каналами")
    async def voice_admin_panel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Только на сервере.", ephemeral=True)
        if not is_admin(interaction.user):
            return await interaction.response.send_message("❌ Нет доступа к панели.", ephemeral=True)
        embed = discord.Embed(
            title="🎙️ Админ-панель голосовых каналов",
            description=(
                "**📢 Всех ко мне** — переместить участников в твой текущий голосовой канал.\n"
                "**😴 Спящих в AFK** — переместить заглушивших себя участников в AFK-канал сервера.\n"
                "**🔊 Размутить участника / всех** — напомнить включить звук перемещениями между каналами, до 45 секунд.\n"
                "**✉️ Рассылка в ЛС** — отправить сообщение участникам с Family/Tier/основными ролями."
            ),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, view=VoiceAdminView(self))

    async def cog_load(self):
        self.bot.add_view(VoiceAdminView(self))


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceAdmin(bot))
