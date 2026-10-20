import sqlite3
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.config_db import get_connection, get_config
from utils.permissions import (
    can_start_contract,
    can_join_contract,
    is_admin,
)


DURATION_MINUTES = 10


# ============================================================
# ВРЕМЯ
# ============================================================

def now():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def from_iso(value):
    return datetime.fromisoformat(value)


# ============================================================
# DATABASE
# ============================================================

def ensure_contracts_table():
    """
    Создаёт таблицу контрактов, если её ещё нет.
    """
    conn = get_connection()

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS contracts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            starter_id INTEGER NOT NULL,
            started_at TEXT NOT NULL,
            ends_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            participants TEXT NOT NULL DEFAULT ''
        )
        """
    )

    conn.commit()
    conn.close()


def csv_ids(value):
    """
    Преобразует строку:
        123,456,789
    в:
        [123, 456, 789]
    """
    if not value:
        return []

    result = []

    for item in str(value).split(","):
        item = item.strip()

        if item.isdigit():
            result.append(int(item))

    return result


def save_participants(contract_id, user_ids):
    conn = get_connection()

    conn.execute(
        """
        UPDATE contracts
        SET participants=?
        WHERE id=?
        """,
        (
            ",".join(str(user_id) for user_id in user_ids),
            contract_id,
        ),
    )

    conn.commit()
    conn.close()


def create_contract(guild_id, starter_id, ends_at):
    conn = get_connection()

    cursor = conn.execute(
        """
        INSERT INTO contracts (
            guild_id,
            starter_id,
            started_at,
            ends_at,
            active,
            participants
        )
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (
            guild_id,
            starter_id,
            iso(now()),
            iso(ends_at),
            # ИНИЦИАТОР СРАЗУ СТАНОВИТСЯ УЧАСТНИКОМ
            str(starter_id),
        ),
    )

    contract_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return contract_id


def get_contract(contract_id):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM contracts
        WHERE id=?
        """,
        (contract_id,),
    ).fetchone()

    conn.close()

    if not row:
        return None

    return dict(row)


def get_active_contract(guild_id):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT *
        FROM contracts
        WHERE guild_id=?
          AND active=1
        ORDER BY id DESC
        LIMIT 1
        """,
        (guild_id,),
    ).fetchone()

    conn.close()

    if not row:
        return None

    return dict(row)


def close_contract(contract_id):
    conn = get_connection()

    conn.execute(
        """
        UPDATE contracts
        SET active=0
        WHERE id=?
        """,
        (contract_id,),
    )

    conn.commit()
    conn.close()


# ============================================================
# КНОПКИ АКТИВНОГО КОНТРАКТА
# ============================================================

class ContractView(discord.ui.View):

    def __init__(self, cog, contract_id):
        super().__init__(timeout=None)

        self.cog = cog
        self.contract_id = contract_id

        # Делаем custom_id уникальными для каждого контракта.
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.label == "🚀 Записаться":
                    item.custom_id = f"contract:join:{contract_id}"

                elif item.label == "❌ Выписаться":
                    item.custom_id = f"contract:leave:{contract_id}"

                elif item.label == "🛑 Отменить контракт":
                    item.custom_id = f"contract:cancel:{contract_id}"

    @discord.ui.button(
        label="🚀 Записаться",
        style=discord.ButtonStyle.success,
        custom_id="contract_join",
    )
    async def join_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.join_contract(
            interaction,
            self.contract_id,
        )

    @discord.ui.button(
        label="❌ Выписаться",
        style=discord.ButtonStyle.danger,
        custom_id="contract_leave",
    )
    async def leave_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.leave_contract(
            interaction,
            self.contract_id,
        )

    @discord.ui.button(
        label="🛑 Отменить контракт",
        style=discord.ButtonStyle.secondary,
        custom_id="contract_cancel",
    )
    async def cancel_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.cancel_contract(
            interaction,
            self.contract_id,
        )


# ============================================================
# ПАНЕЛЬ КОНТРАКТОВ
# ============================================================

class ContractPanelView(discord.ui.View):

    def __init__(self, cog):
        super().__init__(timeout=None)

        self.cog = cog

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.custom_id = "contract:start"

    @discord.ui.button(
        label="🚀 Запустить контракт",
        style=discord.ButtonStyle.primary,
        custom_id="contract_start",
    )
    async def start_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await self.cog.start_contract(interaction)


# ============================================================
# CONTRACTS COG
# ============================================================

class Contracts(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        ensure_contracts_table()

        self.expire_task.start()

    # --------------------------------------------------------
    # LOAD
    # --------------------------------------------------------

    async def cog_load(self):
        self.bot.add_view(
            ContractPanelView(self)
        )

    # --------------------------------------------------------
    # RESTORE
    # --------------------------------------------------------

    async def restore_views(self):

        for guild in self.bot.guilds:

            contract = get_active_contract(guild.id)

            if not contract:
                continue

            self.bot.add_view(
                ContractView(
                    self,
                    contract["id"],
                )
            )

    # --------------------------------------------------------
    # UNLOAD
    # --------------------------------------------------------

    def cog_unload(self):
        self.expire_task.cancel()

    # ========================================================
    # ПУБЛИКАЦИЯ ПАНЕЛИ
    # ========================================================

    async def publish_panel(self, guild):

        config = get_config(guild.id)

        channel_id = config.get(
            "contract_channel_id"
        )

        if not channel_id:
            return False

        try:
            channel = guild.get_channel(
                int(channel_id)
            )
        except (TypeError, ValueError):
            return False

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return False

        embed = discord.Embed(
            title="📄 Контракты",
            description=(
                "Если вы желаете запуститься "
                "в контракт, нажмите кнопку ниже.\n\n"
                "После запуска начнётся набор "
                "продолжительностью **10 минут**."
            ),
            color=discord.Color.blurple(),
        )

        await channel.send(
            embed=embed,
            view=ContractPanelView(self),
        )

        return True

    # ========================================================
    # ЗАПУСК КОНТРАКТА
    # ========================================================

    async def start_contract(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Эта кнопка работает только на сервере.",
                ephemeral=True,
            )

        # Проверяем право запуска
        if not can_start_contract(
            interaction.user
        ):
            return await interaction.response.send_message(
                "❌ У вас нет роли для запуска контракта.",
                ephemeral=True,
            )

        config = get_config(
            interaction.guild.id
        )

        channel_id = config.get(
            "contract_channel_id"
        )

        if not channel_id:
            return await interaction.response.send_message(
                "❌ Канал контрактов ещё не настроен.",
                ephemeral=True,
            )

        try:
            configured_channel_id = int(channel_id)
        except (TypeError, ValueError):
            return await interaction.response.send_message(
                "❌ В настройках указан некорректный канал контрактов.",
                ephemeral=True,
            )

        if interaction.channel_id != configured_channel_id:
            return await interaction.response.send_message(
                "❌ Запускать контракт можно "
                "только в настроенном канале контрактов.",
                ephemeral=True,
            )

        # Проверяем активный контракт
        active = get_active_contract(
            interaction.guild.id
        )

        if active:
            return await interaction.response.send_message(
                "❌ Сейчас уже идёт набор в контракт.",
                ephemeral=True,
            )

        # Создаём контракт
        end_time = (
            now()
            + timedelta(
                minutes=DURATION_MINUTES
            )
        )

        contract_id = create_contract(
            interaction.guild.id,
            interaction.user.id,
            end_time,
        )

        # Основная роль семьи
        family_role = None

        family_role_id = config.get(
            "family_role_id"
        )

        if family_role_id:

            try:
                family_role = (
                    interaction.guild.get_role(
                        int(family_role_id)
                    )
                )
            except (
                TypeError,
                ValueError,
            ):
                family_role = None

        # Инициатор уже автоматически участник
        embed = discord.Embed(
            title="📄 Набор в контракт открыт",
            description=(
                f"**Инициатор:** "
                f"{interaction.user.mention}\n\n"
                f"**Время набора:** "
                f"{DURATION_MINUTES} минут\n\n"
                f"**Окончание:** "
                f"<t:{int(end_time.timestamp())}:R>\n\n"
                f"**Участников:** 1\n\n"
                f"**Список:**\n"
                f"{interaction.user.mention}\n\n"
                "Нажмите **«Записаться»**, "
                "чтобы попасть в контракт."
            ),
            color=discord.Color.green(),
        )

        content = (
            family_role.mention
            if family_role
            else None
        )

        allowed_mentions = discord.AllowedMentions(
            roles=True,
            users=True,
        )

        await interaction.response.send_message(
            content=content,
            embed=embed,
            view=ContractView(
                self,
                contract_id,
            ),
            allowed_mentions=allowed_mentions,
        )

    # ========================================================
    # ОБНОВЛЕНИЕ СООБЩЕНИЯ
    # ========================================================

    async def refresh_contract_message(
        self,
        interaction: discord.Interaction,
        contract,
    ):

        user_ids = csv_ids(
            contract["participants"]
        )

        if user_ids:

            mentions = ", ".join(
                f"<@{user_id}>"
                for user_id in user_ids
            )

        else:

            mentions = "Нет участников."

        end_time = from_iso(
            contract["ends_at"]
        )

        embed = discord.Embed(
            title="📄 Набор в контракт открыт",
            description=(
                f"**Инициатор:** "
                f"<@{contract['starter_id']}>\n\n"
                f"**Окончание:** "
                f"<t:{int(end_time.timestamp())}:R>\n\n"
                f"**Участников:** "
                f"{len(user_ids)}\n\n"
                f"**Список:**\n"
                f"{mentions}"
            ),
            color=discord.Color.green(),
        )

        try:

            await interaction.message.edit(
                embed=embed,
                view=ContractView(
                    self,
                    contract["id"],
                ),
            )

        except discord.HTTPException:
            pass

    # ========================================================
    # ЗАПИСАТЬСЯ
    # ========================================================

    async def join_contract(
        self,
        interaction: discord.Interaction,
        contract_id,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Эта кнопка работает только на сервере.",
                ephemeral=True,
            )

        # Проверяем роль
        if not can_join_contract(
            interaction.user
        ):
            return await interaction.response.send_message(
                "❌ У вас нет роли для участия в контракте.",
                ephemeral=True,
            )

        contract = get_contract(
            contract_id
        )

        if not contract:
            return await interaction.response.send_message(
                "❌ Контракт не найден.",
                ephemeral=True,
            )

        if not contract["active"]:
            return await interaction.response.send_message(
                "❌ Этот набор уже завершён.",
                ephemeral=True,
            )

        # Проверяем время
        end_time = from_iso(
            contract["ends_at"]
        )

        if end_time <= now():

            close_contract(
                contract_id
            )

            return await interaction.response.send_message(
                "❌ Время набора уже закончилось.",
                ephemeral=True,
            )

        user_ids = csv_ids(
            contract["participants"]
        )

        # Уже записан
        if interaction.user.id in user_ids:
            return await interaction.response.send_message(
                "ℹ️ Вы уже записаны в этот контракт.",
                ephemeral=True,
            )

        # Добавляем
        user_ids.append(
            interaction.user.id
        )

        save_participants(
            contract_id,
            user_ids,
        )

        contract = get_contract(
            contract_id
        )

        await interaction.response.send_message(
            "✅ Вы записаны в контракт.",
            ephemeral=True,
        )

        await self.refresh_contract_message(
            interaction,
            contract,
        )

    # ========================================================
    # ВЫПИСАТЬСЯ
    # ========================================================

    async def leave_contract(
        self,
        interaction: discord.Interaction,
        contract_id,
    ):

        contract = get_contract(
            contract_id
        )

        if not contract:
            return await interaction.response.send_message(
                "❌ Контракт не найден.",
                ephemeral=True,
            )

        if not contract["active"]:
            return await interaction.response.send_message(
                "❌ Этот набор уже завершён.",
                ephemeral=True,
            )

        user_ids = csv_ids(
            contract["participants"]
        )

        if interaction.user.id not in user_ids:
            return await interaction.response.send_message(
                "ℹ️ Вы не были записаны в этот контракт.",
                ephemeral=True,
            )

        user_ids.remove(
            interaction.user.id
        )

        save_participants(
            contract_id,
            user_ids,
        )

        contract = get_contract(
            contract_id
        )

        await interaction.response.send_message(
            "✅ Вы выписались из контракта.",
            ephemeral=True,
        )

        await self.refresh_contract_message(
            interaction,
            contract,
        )

    # ========================================================
    # ОТМЕНА КОНТРАКТА
    # ========================================================

    async def cancel_contract(
        self,
        interaction: discord.Interaction,
        contract_id,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Эта кнопка работает только на сервере.",
                ephemeral=True,
            )

        contract = get_contract(
            contract_id
        )

        if not contract:
            return await interaction.response.send_message(
                "❌ Контракт не найден.",
                ephemeral=True,
            )

        if not contract["active"]:
            return await interaction.response.send_message(
                "❌ Этот контракт уже завершён или отменён.",
                ephemeral=True,
            )

        # Отменить может:
        # 1. Администратор
        # 2. Инициатор контракта
        allowed = (
            is_admin(interaction.user)
            or interaction.user.id
            == int(contract["starter_id"])
        )

        if not allowed:
            return await interaction.response.send_message(
                "❌ Отменить контракт может только "
                "администратор или его инициатор.",
                ephemeral=True,
            )

        # Закрываем контракт
        close_contract(
            contract_id
        )

        user_ids = csv_ids(
            contract["participants"]
        )

        mentions = (
            ", ".join(
                f"<@{user_id}>"
                for user_id in user_ids
            )
            if user_ids
            else "Нет участников."
        )

        embed = discord.Embed(
            title="🛑 Контракт отменён",
            description=(
                f"**Инициатор:** "
                f"<@{contract['starter_id']}>\n\n"
                f"**Отменил:** "
                f"{interaction.user.mention}\n\n"
                f"**Участников было:** "
                f"{len(user_ids)}\n\n"
                f"**Участники:**\n"
                f"{mentions}"
            ),
            color=discord.Color.orange(),
        )

        try:

            await interaction.message.edit(
                embed=embed,
                view=None,
            )

        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            "🛑 Контракт отменён.",
            ephemeral=True,
        )

    # ========================================================
    # ЗАВЕРШЕНИЕ КОНТРАКТА
    # ========================================================

    async def finish_contract(
        self,
        guild,
        contract,
    ):

        contract_id = contract["id"]

        close_contract(
            contract_id
        )

        config = get_config(
            guild.id
        )

        channel_id = config.get(
            "contract_channel_id"
        )

        channel = None

        if channel_id:

            try:
                channel = guild.get_channel(
                    int(channel_id)
                )
            except (
                TypeError,
                ValueError,
            ):
                channel = None

        if not isinstance(
            channel,
            discord.TextChannel,
        ):
            return

        user_ids = csv_ids(
            contract["participants"]
        )

        if user_ids:

            mentions = ", ".join(
                f"<@{user_id}>"
                for user_id in user_ids
            )

        else:

            mentions = "Никто не записался."

        # Получаем роль контракта
        contract_role = None

        contract_role_id = config.get(
            "contract_role_id"
        )

        if contract_role_id:

            try:
                contract_role = guild.get_role(
                    int(contract_role_id)
                )
            except (
                TypeError,
                ValueError,
            ):
                contract_role = None

        # Уведомление о завершении
        embed = discord.Embed(
            title="📄 Набор закончен",
            description=(
                "15 минут набора закончились.\n\n"
                f"**Инициатор:** "
                f"<@{contract['starter_id']}>\n\n"
                f"**Участников:** "
                f"{len(user_ids)}\n\n"
                f"**Участники:**\n"
                f"{mentions}"
            ),
            color=discord.Color.red(),
        )

        # Тегаем именно роль контракта
        role_content = (
            contract_role.mention
            if contract_role
            else None
        )

        allowed_mentions = discord.AllowedMentions(
            roles=True,
            users=True,
        )

        await channel.send(
            content=role_content,
            embed=embed,
            allowed_mentions=allowed_mentions,
        )

        # Если роль не настроена
        if not contract_role:

            print(
                f"⚠️ Роль контракта не найдена "
                f"для сервера {guild.id}."
            )

            return

        # Выдаём роль всем участникам
        for user_id in user_ids:

            member = guild.get_member(
                user_id
            )

            if not member:
                continue

            try:

                if contract_role not in member.roles:

                    await member.add_roles(
                        contract_role,
                        reason="Участник контракта",
                    )

            except discord.Forbidden:

                print(
                    f"❌ Не удалось выдать роль "
                    f"контракта пользователю "
                    f"{member}."
                )

            except discord.HTTPException:

                print(
                    f"❌ Discord API error "
                    f"при выдаче роли пользователю "
                    f"{member}."
                )

    # ========================================================
    # ПРОВЕРКА ОКОНЧАНИЯ КАЖДЫЕ 15 СЕКУНД
    # ========================================================

    @tasks.loop(seconds=15)
    async def expire_task(self):

        for guild in self.bot.guilds:

            contract = get_active_contract(
                guild.id
            )

            if not contract:
                continue

            try:

                end_time = from_iso(
                    contract["ends_at"]
                )

            except Exception:

                print(
                    f"❌ Некорректная дата "
                    f"контракта {contract['id']}"
                )

                continue

            if end_time > now():
                continue

            try:

                await self.finish_contract(
                    guild,
                    contract,
                )

            except Exception as e:

                print(
                    f"❌ Ошибка завершения "
                    f"контракта {contract['id']}: "
                    f"{type(e).__name__}: {e}"
                )

    @expire_task.before_loop
    async def before_expire_task(self):

        await self.bot.wait_until_ready()

    # ========================================================
    # SLASH COMMAND
    # ========================================================

    @app_commands.command(
        name="contracts-panel",
        description="Опубликовать панель контрактов",
    )
    async def contracts_panel(
        self,
        interaction: discord.Interaction,
    ):

        if not interaction.guild:
            return await interaction.response.send_message(
                "❌ Команда работает только на сервере.",
                ephemeral=True,
            )

        if not can_start_contract(
            interaction.user
        ):
            return await interaction.response.send_message(
                "❌ У вас нет доступа.",
                ephemeral=True,
            )

        success = await self.publish_panel(
            interaction.guild
        )

        if success:

            await interaction.response.send_message(
                "✅ Панель контрактов опубликована.",
                ephemeral=True,
            )

        else:

            await interaction.response.send_message(
                "❌ Сначала настройте канал контрактов.",
                ephemeral=True,
            )


# ============================================================
# SETUP
# ============================================================

async def setup(bot):
    await bot.add_cog(
        Contracts(bot)
    )
