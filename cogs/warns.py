import discord
from discord.ext import commands, tasks
from discord import app_commands

import sqlite3
import os
from datetime import datetime, timedelta

from utils.config_db import get_config
from utils.permissions import is_recruiter, has_group_access


# ============================================================
#                 S A V A G E • WARNS
# ============================================================

DB_PATH = os.path.join("database", "savage.db")

WARN_EXPIRE_DAYS = 7
MAX_WARNS = 3


# ============================================================
#                         DATABASE
# ============================================================

def get_connection():
    os.makedirs("database", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def init_warn_database():

    conn = get_connection()
    cursor = conn.cursor()

    # --------------------------------------------------------
    # WARN STAFF
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warn_staff_roles (
            guild_id INTEGER,
            role_id INTEGER,
            PRIMARY KEY (guild_id, role_id)
        )
    """)

    # --------------------------------------------------------
    # WARNS
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            price INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    # --------------------------------------------------------
    # Миграция старой таблицы
    # --------------------------------------------------------
    # Если таблица warns уже существовала без price,
    # добавляем колонку автоматически.

    cursor.execute("""
        PRAGMA table_info(warns)
    """)

    columns = {
        row["name"]
        for row in cursor.fetchall()
    }

    if "price" not in columns:

        cursor.execute("""
            ALTER TABLE warns
            ADD COLUMN price INTEGER NOT NULL DEFAULT 0
        """)

    conn.commit()
    conn.close()


# ============================================================
#                    STAFF ROLES DATABASE
# ============================================================

def get_warn_staff_roles(
    guild_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT role_id
        FROM warn_staff_roles
        WHERE guild_id = ?
    """, (
        guild_id,
    ))

    rows = cursor.fetchall()

    conn.close()

    return [
        int(row["role_id"])
        for row in rows
    ]


def add_warn_staff_role(
    guild_id: int,
    role_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR IGNORE INTO warn_staff_roles (
            guild_id,
            role_id
        )
        VALUES (?, ?)
    """, (
        guild_id,
        role_id
    ))

    conn.commit()
    conn.close()


def remove_warn_staff_role(
    guild_id: int,
    role_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM warn_staff_roles
        WHERE guild_id = ?
        AND role_id = ?
    """, (
        guild_id,
        role_id
    ))

    conn.commit()
    conn.close()


# ============================================================
#                         WARN DATABASE
# ============================================================

def get_active_warns(
    guild_id: int,
    user_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM warns
        WHERE guild_id = ?
        AND user_id = ?
        ORDER BY id ASC
    """, (
        guild_id,
        user_id
    ))

    rows = cursor.fetchall()

    conn.close()

    return rows


def add_warn(
    guild_id: int,
    user_id: int,
    moderator_id: int,
    reason: str,
    price: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO warns (
            guild_id,
            user_id,
            moderator_id,
            reason,
            price,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        guild_id,
        user_id,
        moderator_id,
        reason,
        price,
        datetime.utcnow().isoformat()
    ))

    conn.commit()

    warn_id = cursor.lastrowid

    conn.close()

    return warn_id


def remove_latest_warn(
    guild_id: int,
    user_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id
        FROM warns
        WHERE guild_id = ?
        AND user_id = ?
        ORDER BY id DESC
        LIMIT 1
    """, (
        guild_id,
        user_id
    ))

    row = cursor.fetchone()

    if not row:
        conn.close()
        return False

    cursor.execute("""
        DELETE FROM warns
        WHERE id = ?
    """, (
        row["id"],
    ))

    conn.commit()
    conn.close()

    return True


def remove_expired_warns():

    expire_before = (
        datetime.utcnow()
        - timedelta(days=WARN_EXPIRE_DAYS)
    ).isoformat()

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM warns
        WHERE created_at < ?
    """, (
        expire_before,
    ))

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    return deleted


# ============================================================
#                         STAFF CHECK
# ============================================================

def is_warn_staff(
    member: discord.Member
):
    cfg = get_config(member.guild.id)
    group_keys = (
        "group_admin_role_ids",
        "group_moderator_role_ids",
        "group_checked_role_ids",
        "group_family_role_ids",
    )
    # Once groups are configured, WARN access follows the permission matrix.
    if any(cfg.get(key) for key in group_keys):
        return has_group_access(member, "warns")

    # Backwards compatibility for servers not yet configured for groups.
    if member.guild_permissions.administrator or is_recruiter(member):
        return True
    role_ids = get_warn_staff_roles(member.guild.id)
    member_role_ids = {role.id for role in member.roles}
    return bool(member_role_ids.intersection(set(role_ids)))


# ============================================================
#                       WARN COLOR
# ============================================================

def get_warn_color(
    count: int
):

    if count <= 1:
        return discord.Color.gold()

    if count == 2:
        return discord.Color.orange()

    return discord.Color.red()


# ============================================================
#                       WARN COG
# ============================================================

class Warns(commands.Cog):

    def __init__(
        self,
        bot
    ):

        self.bot = bot

        init_warn_database()

        self.remove_expired_task.start()

    def cog_unload(self):

        self.remove_expired_task.cancel()

    # ========================================================
    #                 AUTOMATIC EXPIRATION
    # ========================================================

    @tasks.loop(minutes=10)
    async def remove_expired_task(
        self
    ):

        try:

            deleted = remove_expired_warns()

            if deleted:

                print(
                    f"🧹 Автоматически снято WARN'ов: "
                    f"{deleted}"
                )

        except Exception as error:

            print(
                "[SAVAGE][WARNS] "
                f"Ошибка очистки WARN: "
                f"{type(error).__name__}: {error}"
            )

    @remove_expired_task.before_loop
    async def before_remove_expired_task(
        self
    ):

        await self.bot.wait_until_ready()

    # ========================================================
    #                    STAFF CHECK
    # ========================================================

    async def check_staff(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            await interaction.response.send_message(
                "❌ Эта команда работает только на сервере.",
                ephemeral=True
            )

            return False

        if not isinstance(
            interaction.user,
            discord.Member
        ):

            await interaction.response.send_message(
                "❌ Не удалось определить участника.",
                ephemeral=True
            )

            return False

        if not is_warn_staff(
            interaction.user
        ):

            await interaction.response.send_message(
                "❌ У вас нет прав для выдачи WARN.",
                ephemeral=True
            )

            return False

        return True

    # ========================================================
    #                         /WARN
    # ========================================================

    @app_commands.command(
        name="warn",
        description="Выдать WARN участнику"
    )
    @app_commands.describe(
        user="Пользователь, которому выдаётся WARN",
        reason="Причина WARN",
        price="Цена WARN"
    )
    async def warn_command(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str,
        price: int
    ):

        try:

            if not await self.check_staff(
                interaction
            ):
                return

            # ------------------------------------------------
            # Нельзя варнить бота
            # ------------------------------------------------

            if user.bot:

                await interaction.response.send_message(
                    "❌ Нельзя выдать WARN боту.",
                    ephemeral=True
                )

                return

            # ------------------------------------------------
            # Нельзя варнить себя
            # ------------------------------------------------

            if user.id == interaction.user.id:

                await interaction.response.send_message(
                    "❌ Нельзя выдать WARN самому себе.",
                    ephemeral=True
                )

                return

            # ------------------------------------------------
            # Проверяем цену
            # ------------------------------------------------

            if price < 0:

                await interaction.response.send_message(
                    "❌ Цена WARN не может быть отрицательной.",
                    ephemeral=True
                )

                return

            # ------------------------------------------------
            # Проверяем причину
            # ------------------------------------------------

            reason = reason.strip()

            if not reason:

                await interaction.response.send_message(
                    "❌ Причина WARN не может быть пустой.",
                    ephemeral=True
                )

                return

            # ------------------------------------------------
            # Получаем старые WARN
            # ------------------------------------------------

            old_warns = get_active_warns(
                interaction.guild.id,
                user.id
            )

            current_count = len(old_warns)

            if current_count >= MAX_WARNS:

                await interaction.response.send_message(
                    "❌ У пользователя уже 3/3 WARN.",
                    ephemeral=True
                )

                return

            # ------------------------------------------------
            # Выдаём новый WARN
            # ------------------------------------------------

            add_warn(
                interaction.guild.id,
                user.id,
                interaction.user.id,
                reason,
                price
            )

            # ------------------------------------------------
            # Получаем обновлённые WARN
            # ------------------------------------------------

            warns = get_active_warns(
                interaction.guild.id,
                user.id
            )

            count = len(warns)

            color = get_warn_color(
                count
            )

            # ------------------------------------------------
            # Основное сообщение
            # ------------------------------------------------

            description = (
                f"Семейнику {user.mention} был выдан WARN "
                f"по причине:\n\n"
                f"```text\n"
                f"{reason}\n"
                f"```\n"
                f"WARN был выдан: "
                f"{interaction.user.mention}\n"
                f"WARN'ов: **{count}/3**\n"
                f"💰 Цена WARN: **{price:,}$**"
            )

            if count >= 3:

                description += (
                    "\n\n"
                    "⚠️ **В связи с накоплением 3/3 WARN'ов "
                    "нам придётся попрощаться с ним. Удачи!**"
                )

            embed = discord.Embed(
                title="Варны",
                description=description,
                color=color,
                timestamp=datetime.now()
            )

            embed.set_thumbnail(
                url=user.display_avatar.url
            )

            embed.set_footer(
                text="S A V A G E • Система WARN"
            )

            # ------------------------------------------------
            # Отправляем WARN в настроенный канал
            # ------------------------------------------------

            cfg = get_config(
                interaction.guild.id
            )

            warn_channel = (
                interaction.guild.get_channel(
                    cfg.get("warn_channel_id")
                )
                if cfg.get("warn_channel_id")
                else None
            )

            if (
                isinstance(
                    warn_channel,
                    discord.TextChannel
                )
                and warn_channel.id != interaction.channel.id
            ):

                await warn_channel.send(
                    embed=embed
                )

                await interaction.response.send_message(
                    f"✅ WARN выдан и отправлен "
                    f"в {warn_channel.mention}.",
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    embed=embed
                )

            # ------------------------------------------------
            # DM только при 3/3
            # ------------------------------------------------

            if count >= 3:

                try:

                    dm_embed = discord.Embed(
                        title="Привет друг!",
                        description=(
                            f"Тебе был выдан **WARN** "
                            f"по причине:\n\n"
                            f"```text\n"
                            f"{reason}\n"
                            f"```\n"
                            f"WARN был выдан: "
                            f"{interaction.user.mention} "
                            f"| {interaction.user.display_name}\n"
                            f"WARN'ов: **{count}/3**\n"
                            f"💰 Цена WARN: **{price:,}$**\n\n"
                            f"В связи с накоплением 3/3 WARN'ов "
                            f"нам придётся попрощаться. "
                            f"Удачи!"
                        ),
                        color=discord.Color.red()
                    )

                    dm_embed.set_footer(
                        text="S A V A G E"
                    )

                    await user.send(
                        embed=dm_embed
                    )

                except discord.Forbidden:

                    print(
                        f"⚠️ Не удалось отправить DM "
                        f"{user} — личные сообщения закрыты."
                    )

                except discord.HTTPException as error:

                    print(
                        f"⚠️ Ошибка DM для {user}: "
                        f"{error}"
                    )

        except Exception as error:

            print(
                "[SAVAGE][WARNS] "
                f"/warn: "
                f"{type(error).__name__}: {error}"
            )

            try:

                if interaction.response.is_done():

                    await interaction.followup.send(
                        "❌ Произошла ошибка при выдаче WARN.",
                        ephemeral=True
                    )

                else:

                    await interaction.response.send_message(
                        "❌ Произошла ошибка при выдаче WARN.",
                        ephemeral=True
                    )

            except Exception:
                pass

    # ========================================================
    #                       /UNWARN
    # ========================================================

    @app_commands.command(
        name="unwarn",
        description="Снять последний WARN с участника"
    )
    @app_commands.describe(
        user="Пользователь, с которого снимается WARN"
    )
    async def unwarn_command(
        self,
        interaction: discord.Interaction,
        user: discord.Member
    ):

        try:

            if not await self.check_staff(
                interaction
            ):
                return

            warns = get_active_warns(
                interaction.guild.id,
                user.id
            )

            if not warns:

                await interaction.response.send_message(
                    f"❌ У {user.mention} нет активных WARN.",
                    ephemeral=True
                )

                return

            remove_latest_warn(
                interaction.guild.id,
                user.id
            )

            new_warns = get_active_warns(
                interaction.guild.id,
                user.id
            )

            count = len(new_warns)

            embed = discord.Embed(
                title="Варны",
                description=(
                    f"С пользователя {user.mention} "
                    f"был снят **1 WARN**.\n\n"
                    f"WARN'ов: **{count}/3**\n"
                    f"Снял: {interaction.user.mention}"
                ),
                color=get_warn_color(
                    count
                )
            )

            cfg = get_config(
                interaction.guild.id
            )

            warn_channel = (
                interaction.guild.get_channel(
                    cfg.get("warn_channel_id")
                )
                if cfg.get("warn_channel_id")
                else None
            )

            if (
                isinstance(
                    warn_channel,
                    discord.TextChannel
                )
                and warn_channel.id != interaction.channel.id
            ):

                await warn_channel.send(
                    embed=embed
                )

                await interaction.response.send_message(
                    f"✅ WARN снят. "
                    f"Лог отправлен в {warn_channel.mention}.",
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    embed=embed
                )

        except Exception as error:

            print(
                "[SAVAGE][WARNS] "
                f"/unwarn: "
                f"{type(error).__name__}: {error}"
            )

            try:

                if interaction.response.is_done():

                    await interaction.followup.send(
                        "❌ Произошла ошибка при снятии WARN.",
                        ephemeral=True
                    )

                else:

                    await interaction.response.send_message(
                        "❌ Произошла ошибка при снятии WARN.",
                        ephemeral=True
                    )

            except Exception:
                pass

    # ========================================================
    #                    /WARN-ADDSTAFF
    # ========================================================

    @app_commands.command(
        name="warn-addstaff",
        description="Добавить роль, которой разрешено выдавать WARN"
    )
    @app_commands.describe(
        role="Роль, которой будет разрешена выдача WARN"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def warn_addstaff(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):

        try:

            if not interaction.user.guild_permissions.administrator:

                await interaction.response.send_message(
                    "❌ Только администратор может "
                    "настраивать роли WARN.",
                    ephemeral=True
                )

                return

            roles = get_warn_staff_roles(
                interaction.guild.id
            )

            if role.id in roles:

                await interaction.response.send_message(
                    f"ℹ️ Роль {role.mention} уже имеет "
                    "право выдавать WARN.",
                    ephemeral=True
                )

                return

            add_warn_staff_role(
                interaction.guild.id,
                role.id
            )

            await interaction.response.send_message(
                f"✅ Роль {role.mention} теперь может "
                "выдавать WARN.",
                ephemeral=True
            )

        except Exception as error:

            print(
                "[SAVAGE][WARNS] "
                f"/warn-addstaff: {type(error).__name__}: {error}"
            )

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    "❌ Произошла ошибка.",
                    ephemeral=True
                )

    # ========================================================
    #                   /WARN-REMSTAFF
    # ========================================================

    @app_commands.command(
        name="warn-remstaff",
        description="Забрать у роли право выдавать WARN"
    )
    @app_commands.describe(
        role="Роль, у которой забирается право"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def warn_remstaff(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):

        try:

            if not interaction.user.guild_permissions.administrator:

                await interaction.response.send_message(
                    "❌ Только администратор может "
                    "настраивать роли WARN.",
                    ephemeral=True
                )

                return

            roles = get_warn_staff_roles(
                interaction.guild.id
            )

            if role.id not in roles:

                await interaction.response.send_message(
                    f"ℹ️ Роль {role.mention} "
                    "не имеет права выдавать WARN.",
                    ephemeral=True
                )

                return

            remove_warn_staff_role(
                interaction.guild.id,
                role.id
            )

            await interaction.response.send_message(
                f"✅ Роль {role.mention} больше не может "
                "выдавать WARN.",
                ephemeral=True
            )

        except Exception as error:

            print(
                "[SAVAGE][WARNS] "
                f"/warn-remstaff: {type(error).__name__}: {error}"
            )

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    "❌ Произошла ошибка.",
                    ephemeral=True
                )


# ============================================================
#                         SETUP
# ============================================================

async def setup(bot):

    await bot.add_cog(
        Warns(bot)
    )

    print(
        "✅ warns.py загружен"
    )
