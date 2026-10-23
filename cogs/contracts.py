"""Контракты: панель, запись участников и автоматическое завершение через 15 минут."""
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.config_db import get_connection, get_config, parse_ids

DURATION_MINUTES = 15

def utcnow():
    return datetime.now(timezone.utc)

def parse_time(value):
    return datetime.fromisoformat(value)

def csv_ids(value):
    return parse_ids(value)

def fetch_contract(contract_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM contracts WHERE id=?", (int(contract_id),)).fetchone()
        return dict(row) if row else None

def active_contract(guild_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM contracts WHERE guild_id=? AND active=1 ORDER BY id DESC LIMIT 1",
            (int(guild_id),),
        ).fetchone()
        return dict(row) if row else None

def set_participants(contract_id, ids):
    ids = list(dict.fromkeys(int(x) for x in ids))
    with get_connection() as conn:
        conn.execute("UPDATE contracts SET participants=? WHERE id=?", (",".join(map(str, ids)), int(contract_id)))

def family_mentions(guild, config):
    ids = parse_ids(config.get("family_role_ids", ""))
    if not ids:
        ids = parse_ids(config.get("group_family_role_ids", ""))
    if not ids and config.get("family_role_id"):
        ids = parse_ids(str(config["family_role_id"]))
    roles = [guild.get_role(role_id) for role_id in ids]
    return " ".join(role.mention for role in roles if role)

def contract_embed(contract, closed=False):
    ids = csv_ids(contract.get("participants", ""))
    ending = parse_time(contract["ends_at"])
    title = "📄 Набор закончен" if closed else "📄 Набор в контракт открыт"
    description = (
        f"**Инициатор:** <@{contract['starter_id']}>\n"
        f"**Окончание:** <t:{int(ending.timestamp())}:R>\n"
        f"**Участников:** {len(ids)}\n\n"
        "**Список участников:**\n" + ("\n".join(f"• <@{uid}>" for uid in ids) if ids else "Пока никто не записался.")
    )
    return discord.Embed(title=title, description=description, color=discord.Color.red() if closed else discord.Color.green())

class ContractPanel(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🚀 Запустить контракт", style=discord.ButtonStyle.primary, custom_id="contract:panel:start")
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.start_contract(interaction)

class ActiveContractView(discord.ui.View):
    def __init__(self, cog, contract_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.contract_id = int(contract_id)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                action = "join" if item.label.startswith("🟢") else "leave"
                item.custom_id = f"contract:{action}:{self.contract_id}"

    @discord.ui.button(label="🟢 Записаться", style=discord.ButtonStyle.success, custom_id="contract:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.change_participation(interaction, self.contract_id, True)

    @discord.ui.button(label="🔴 Выписаться", style=discord.ButtonStyle.secondary, custom_id="contract:leave")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.change_participation(interaction, self.contract_id, False)

class Contracts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.expire_task.start()

    async def cog_load(self):
        self.bot.add_view(ContractPanel(self))

    def cog_unload(self):
        self.expire_task.cancel()

    async def restore_views(self):
        for guild in self.bot.guilds:
            contract = active_contract(guild.id)
            if contract:
                self.bot.add_view(ActiveContractView(self, contract["id"]))

    async def publish_panel(self, guild):
        config = get_config(guild.id)
        channel_id = config.get("contract_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return False
        embed = discord.Embed(
            title="📄 Контракты",
            description="Чтобы начать набор, нажмите **«Запустить контракт»**. Набор длится **15 минут**. Запускать и присоединяться могут все участники сервера.",
            color=discord.Color.blurple(),
        )
        await channel.send(embed=embed, view=ContractPanel(self))
        return True

    async def start_contract(self, interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Эта кнопка работает только на сервере.", ephemeral=True)
        config = get_config(interaction.guild.id)
        configured = config.get("contract_channel_id")
        if not configured or int(configured) != interaction.channel_id:
            return await interaction.response.send_message("Сначала настройте канал контрактов в админ-панели и запускайте набор там.", ephemeral=True)
        if active_contract(interaction.guild.id):
            return await interaction.response.send_message("Уже идёт набор в контракт. Дождитесь его завершения.", ephemeral=True)
        end = utcnow() + timedelta(minutes=DURATION_MINUTES)
        with get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO contracts(guild_id,starter_id,started_at,ends_at,active,participants,channel_id) VALUES(?,?,?,?,1,?,?)",
                (interaction.guild.id, interaction.user.id, utcnow().isoformat(), end.isoformat(), str(interaction.user.id), interaction.channel_id),
            )
            contract_id = cursor.lastrowid
        contract = fetch_contract(contract_id)
        mentions = family_mentions(interaction.guild, config)
        await interaction.response.send_message(
            content=mentions or None,
            embed=contract_embed(contract),
            view=ActiveContractView(self, contract_id),
            allowed_mentions=discord.AllowedMentions(roles=True, users=True),
        )

    async def change_participation(self, interaction, contract_id, join):
        if not interaction.guild:
            return await interaction.response.send_message("Кнопка работает только на сервере.", ephemeral=True)
        contract = fetch_contract(contract_id)
        if not contract or not contract["active"]:
            return await interaction.response.send_message("Этот набор уже завершён.", ephemeral=True)
        if parse_time(contract["ends_at"]) <= utcnow():
            await self.finish_contract(interaction.guild, contract)
            return await interaction.response.send_message("Время набора уже закончилось.", ephemeral=True)
        ids = csv_ids(contract.get("participants", ""))
        if join and interaction.user.id not in ids:
            ids.append(interaction.user.id)
        elif not join and interaction.user.id in ids:
            ids.remove(interaction.user.id)
        else:
            msg = "Вы уже записаны." if join else "Вы не записаны в этот набор."
            return await interaction.response.send_message(msg, ephemeral=True)
        set_participants(contract_id, ids)
        contract = fetch_contract(contract_id)
        await interaction.response.send_message("Вы записались в контракт." if join else "Вы выписались из контракта.", ephemeral=True)
        try:
            await interaction.message.edit(embed=contract_embed(contract), view=ActiveContractView(self, contract_id))
        except discord.HTTPException:
            pass

    async def finish_contract(self, guild, contract):
        # Обновляем запись до отправки, чтобы повторный проход фоновой задачи не дублировал итог.
        with get_connection() as conn:
            result = conn.execute("UPDATE contracts SET active=0 WHERE id=? AND active=1", (contract["id"],))
            if result.rowcount == 0:
                return
        config = get_config(guild.id)
        channel_id = contract.get("channel_id") or config.get("contract_channel_id")
        channel = guild.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        ids = csv_ids(contract.get("participants", ""))
        await channel.send(
            content="Набор закончен. " + (" ".join(f"<@{uid}>" for uid in ids) if ids else "Никто не записался."),
            embed=contract_embed(contract, closed=True),
            allowed_mentions=discord.AllowedMentions(users=True, roles=False),
        )

    @tasks.loop(seconds=10)
    async def expire_task(self):
        for guild in self.bot.guilds:
            contract = active_contract(guild.id)
            if contract and parse_time(contract["ends_at"]) <= utcnow():
                try:
                    await self.finish_contract(guild, contract)
                except Exception as exc:
                    print(f"[CONTRACT ERROR] id={contract['id']}: {type(exc).__name__}: {exc}")

    @expire_task.before_loop
    async def before_expire_task(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="contracts-panel", description="Опубликовать панель контрактов")
    async def contracts_panel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Команда работает только на сервере.", ephemeral=True)
        if not getattr(interaction.user.guild_permissions, "administrator", False):
            return await interaction.response.send_message("Для публикации панели нужны права администратора.", ephemeral=True)
        if await self.publish_panel(interaction.guild):
            await interaction.response.send_message("Панель контрактов опубликована.", ephemeral=True)
        else:
            await interaction.response.send_message("Укажите канал контрактов в админ-панели.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Contracts(bot))
