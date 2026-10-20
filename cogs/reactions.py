import re
from datetime import datetime, timedelta

import discord
from discord.ext import commands
from discord import app_commands

from utils.config_db import (
    get_connection,
    get_config,
    user_priority,
)
from utils.permissions import (
    can_start_reaction,
    is_admin,
    is_recruiter,
)


# =========================================================
# HELPERS
# =========================================================

def csv_ids(value):
    result = []
    for part in str(value or "").split(","):
        part = part.strip()
        if part.isdigit():
            value = int(part)
            if value not in result:
                result.append(value)
    return result


def ids_csv(ids):
    return ",".join(str(int(x)) for x in dict.fromkeys(ids))


def parse_time(value):
    value = str(value or "").strip()
    if not re.fullmatch(r"\d{1,2}:\d{2}", value):
        return None

    try:
        hour, minute = map(int, value.split(":"))
    except ValueError:
        return None

    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    return hour * 60 + minute


def normalize_time(value):
    minutes = parse_time(value)
    if minutes is None:
        return None

    hour = minutes // 60
    minute = minutes % 60
    return f"{hour:02d}:{minute:02d}"


def start_time(value, reaction_type="default"):
    minutes = parse_time(value)
    if minutes is None:
        return "—"

    # Для VZP начало через 20 минут, для обычных реакций — через 30.
    delay = 20 if str(reaction_type or "default").lower() == "vzp" else 30
    minutes = (minutes + delay) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def result_color(event):
    result = str(event.get("result") or "").lower()
    if result == "win":
        return discord.Color.green()
    if result == "lose":
        return discord.Color.red()
    if event.get("list_message_id"):
        return discord.Color.yellow()
    return discord.Color.from_rgb(0, 0, 0)


def ensure_reaction_database():
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reaction_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL DEFAULT 0,
                creator_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                event_time TEXT NOT NULL,
                slots INTEGER NOT NULL DEFAULT 0,
                participants TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                reserve TEXT NOT NULL DEFAULT '',
                reaction_type TEXT NOT NULL DEFAULT 'default',
                list_message_id INTEGER NOT NULL DEFAULT 0,
                result TEXT NOT NULL DEFAULT ''
            )
            """
        )

        columns = conn.execute(
            "PRAGMA table_info(reaction_events)"
        ).fetchall()

        names = set()
        for row in columns:
            try:
                names.add(row["name"])
            except (TypeError, KeyError):
                names.add(row[1])

        required = {
            "guild_id": "INTEGER NOT NULL DEFAULT 0",
            "channel_id": "INTEGER NOT NULL DEFAULT 0",
            "message_id": "INTEGER NOT NULL DEFAULT 0",
            "creator_id": "INTEGER NOT NULL DEFAULT 0",
            "title": "TEXT NOT NULL DEFAULT ''",
            "event_time": "TEXT NOT NULL DEFAULT ''",
            "slots": "INTEGER NOT NULL DEFAULT 0",
            "participants": "TEXT NOT NULL DEFAULT ''",
            "active": "INTEGER NOT NULL DEFAULT 1",
            "reserve": "TEXT NOT NULL DEFAULT ''",
            "reaction_type": "TEXT NOT NULL DEFAULT 'default'",
            "list_message_id": "INTEGER NOT NULL DEFAULT 0",
            "result": "TEXT NOT NULL DEFAULT ''",
        }

        for column, definition in required.items():
            if column not in names:
                conn.execute(
                    f"ALTER TABLE reaction_events ADD COLUMN {column} {definition}"
                )

        conn.commit()
    finally:
        conn.close()


def get_event(event_id):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM reaction_events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_event(
    guild_id,
    channel_id,
    creator_id,
    title,
    event_time,
    slots,
    reaction_type="default",
):
    ensure_reaction_database()
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO reaction_events (
                guild_id,
                channel_id,
                message_id,
                creator_id,
                title,
                event_time,
                slots,
                participants,
                active,
                reserve,
                reaction_type,
                list_message_id,
                result
            )
            VALUES (?, ?, 0, ?, ?, ?, ?, '', 1, '', ?, 0, '')
            """,
            (
                guild_id,
                channel_id,
                creator_id,
                title,
                event_time,
                slots,
                reaction_type,
            ),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def set_message_id(event_id, message_id):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE reaction_events SET message_id=? WHERE id=?",
            (message_id, event_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_participants(event_id, ids):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE reaction_events SET participants=? WHERE id=?",
            (ids_csv(ids), event_id),
        )
        conn.commit()
    finally:
        conn.close()


def save_reserve(event_id, ids):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE reaction_events SET reserve=? WHERE id=?",
            (ids_csv(ids), event_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_event(event_id, **fields):
    allowed = {
        "event_time",
        "participants",
        "reserve",
        "list_message_id",
        "result",
        "active",
    }
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return

    conn = get_connection()
    try:
        query = ", ".join(f"{key}=?" for key in fields)
        conn.execute(
            f"UPDATE reaction_events SET {query} WHERE id=?",
            (*fields.values(), event_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_role_id(cfg, *keys):
    for key in keys:
        value = cfg.get(key)
        if value is None:
            continue

        if isinstance(value, int):
            return value

        value = str(value).strip()
        if value.isdigit():
            return int(value)

        ids = csv_ids(value)
        if ids:
            return ids[0]

    return None


def get_reaction_roles(guild):
    cfg = get_config(guild.id)
    roles = []

    for role_id in (
        get_role_id(cfg, "main_role_id", "main_role_ids"),
        get_role_id(cfg, "default_role_id", "default_role_ids"),
        get_role_id(cfg, "academy_role_id", "academy_role_ids"),
    ):
        if not role_id:
            continue

        role = guild.get_role(role_id)
        if role and role not in roles:
            roles.append(role)

    return roles


def get_reaction_mentions(guild):
    return " ".join(role.mention for role in get_reaction_roles(guild))


VZP_TAG_ROLE_ID = 1403086533929599059


def get_vzp_tag_mention(guild):
    role = guild.get_role(VZP_TAG_ROLE_ID)
    return role.mention if role else ""


def role_allowed_mentions():
    return discord.AllowedMentions(
        roles=True,
        users=False,
        everyone=False,
    )


def get_type_settings(guild, reaction_type):
    cfg = get_config(guild.id)

    if reaction_type == "vzp":
        return (
            cfg.get("reaction_vzp_channel_id"),
            csv_ids(cfg.get("reaction_vzp_start_role_ids")),
        )

    return (
        cfg.get("reaction_channel_id"),
        csv_ids(cfg.get("reaction_start_role_ids")),
    )


def can_start_vzp(member):
    if not isinstance(member, discord.Member):
        return False

    if is_admin(member):
        return True

    cfg = get_config(member.guild.id)
    allowed = set(csv_ids(cfg.get("reaction_vzp_start_role_ids")))
    return bool(allowed.intersection(role.id for role in member.roles))


def can_manage_event(member, event):
    return is_admin(member) or is_recruiter(member)


# =========================================================
# EMBEDS
# =========================================================

def build_embed(guild, event):
    participants = csv_ids(event.get("participants"))
    reserve = csv_ids(event.get("reserve"))
    slots = int(event.get("slots") or 0)

    lines = []
    for number, user_id in enumerate(participants, start=1):
        member = guild.get_member(user_id)
        mention = member.mention if member else f"<@{user_id}>"
        lines.append(f"**{number}.** {mention}")

    if not lines:
        lines.append("Пока никто не записался.")

    collected = f"{len(participants)}/∞" if slots <= 0 else f"{len(participants)}/{slots}"

    description = f"**Время забива:** {event['event_time']}\n"
    if str(event.get("reaction_type", "default")).lower() == "vzp":
        description += f"**Начало:** {start_time(event['event_time'], 'vzp')}\n"
    description += f"**Собрано:** {collected}\n\n" + "\n".join(lines)

    if slots > 0 and reserve:
        reserve_lines = []
        for number, user_id in enumerate(reserve, start=1):
            member = guild.get_member(user_id)
            mention = member.mention if member else f"<@{user_id}>"
            reserve_lines.append(f"**{number}.** {mention}")

        description += "\n\n**Запас:**\n" + "\n".join(reserve_lines)

    return discord.Embed(
        title=f"⚔️ {event['title']}",
        description=description,
        color=discord.Color.from_rgb(0, 0, 0),
    )


def build_list_embed(guild, event):
    participants = csv_ids(event.get("participants"))
    reserve = csv_ids(event.get("reserve"))

    main_lines = []
    for number, user_id in enumerate(participants, start=1):
        member = guild.get_member(user_id)
        mention = member.mention if member else f"<@{user_id}>"
        main_lines.append(f"**{number}.** {mention}")

    if not main_lines:
        main_lines.append("Никого нет.")

    description = f"**Время забива:** {event['event_time']}\n"
    if str(event.get("reaction_type", "default")).lower() == "vzp":
        description += f"**Начало:** {start_time(event['event_time'], 'vzp')}\n"
    description += "\n**Основной состав:**\n" + "\n".join(main_lines)

    if reserve:
        reserve_lines = []
        for number, user_id in enumerate(reserve, start=1):
            member = guild.get_member(user_id)
            mention = member.mention if member else f"<@{user_id}>"
            reserve_lines.append(f"**{number}.** {mention}")

        description += "\n\n**Запас:**\n" + "\n".join(reserve_lines)

    result = str(event.get("result") or "").lower()
    if result == "win":
        footer = "Результат: WIN"
    elif result == "lose":
        footer = "Результат: LOSE"
    else:
        footer = "Список опубликован"

    embed = discord.Embed(
        title=f"📋 {event['title']}",
        description=description,
        color=result_color(event),
    )
    embed.set_footer(text=footer)
    return embed


# =========================================================
# MODALS
# =========================================================

class ReactionModal(discord.ui.Modal, title="Набор на контент"):
    name = discord.ui.TextInput(
        label="Название",
        placeholder="Например: Мафия",
        max_length=100,
        required=True,
    )

    time = discord.ui.TextInput(
        label="Время забива",
        placeholder="21:00",
        max_length=5,
        min_length=4,
        required=True,
    )

    slots = discord.ui.TextInput(
        label="Количество человек",
        placeholder="Оставьте пустым для ∞",
        max_length=3,
        required=False,
    )

    def __init__(self, cog, reaction_type="default"):
        super().__init__()
        self.cog = cog
        self.reaction_type = reaction_type

    async def on_submit(self, interaction):
        try:
            if not interaction.guild:
                return await interaction.response.send_message(
                    "❌ Команда работает только на сервере.",
                    ephemeral=True,
                )

            raw_slots = (self.slots.value or "").strip()
            if raw_slots:
                try:
                    slots = int(raw_slots)
                except ValueError:
                    return await interaction.response.send_message(
                        "❌ Количество человек должно быть числом.",
                        ephemeral=True,
                    )

                if slots < 1 or slots > 100:
                    return await interaction.response.send_message(
                        "❌ Количество мест должно быть от 1 до 100.",
                        ephemeral=True,
                    )
            else:
                slots = 0

            event_time = normalize_time(self.time.value)
            if not event_time:
                return await interaction.response.send_message(
                    "❌ Время укажите в формате HH:MM, например 21:00.",
                    ephemeral=True,
                )

            channel_id, _ = get_type_settings(
                interaction.guild,
                self.reaction_type,
            )

            channel = None
            if channel_id:
                try:
                    channel = interaction.guild.get_channel(int(channel_id))
                except (TypeError, ValueError):
                    channel = None

            if not isinstance(channel, discord.TextChannel):
                label = "VZP" if self.reaction_type == "vzp" else "реакций"
                return await interaction.response.send_message(
                    f"❌ Канал {label} не настроен в админ-панели.",
                    ephemeral=True,
                )

            if interaction.channel.id != channel.id:
                command_name = "/reaction-vzp" if self.reaction_type == "vzp" else "/reaction"
                return await interaction.response.send_message(
                    f"❌ Использовать {command_name} можно только в {channel.mention}.",
                    ephemeral=True,
                )

            title = self.name.value.strip()
            if not title:
                return await interaction.response.send_message(
                    "❌ Название не может быть пустым.",
                    ephemeral=True,
                )

            event_id = create_event(
                guild_id=interaction.guild.id,
                channel_id=channel.id,
                creator_id=interaction.user.id,
                title=title,
                event_time=event_time,
                slots=slots,
                reaction_type=self.reaction_type,
            )

            event = get_event(event_id)
            embed = build_embed(interaction.guild, event)

            if self.reaction_type == "vzp":
                role_mentions = get_vzp_tag_mention(interaction.guild)
                if not role_mentions:
                    return await interaction.response.send_message(
                        f"❌ Роль VZP `{VZP_TAG_ROLE_ID}` не найдена на сервере.",
                        ephemeral=True,
                    )
            else:
                role_mentions = get_reaction_mentions(interaction.guild)
                if not role_mentions:
                    return await interaction.response.send_message(
                        "❌ Роли MAIN / DEFAULT / ACADEMY не настроены.",
                        ephemeral=True,
                    )

            await interaction.response.send_message(
                content=role_mentions or None,
                embed=embed,
                view=ReactionView(self.cog, event_id),
                allowed_mentions=role_allowed_mentions(),
            )

            message = await interaction.original_response()
            set_message_id(event_id, message.id)

        except Exception as error:
            print(
                "[SAVAGE][REACTIONS] Ошибка создания: "
                f"{type(error).__name__}: {error}"
            )
            import traceback
            traceback.print_exc()

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Не удалось создать набор. Проверь консоль.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Не удалось создать набор. Проверь консоль.",
                        ephemeral=True,
                    )
            except Exception:
                pass


class TimeModal(discord.ui.Modal, title="Изменить время"):
    time = discord.ui.TextInput(
        label="Новое время забива",
        placeholder="21:00",
        max_length=5,
        min_length=4,
        required=True,
    )

    def __init__(self, cog, event_id):
        super().__init__()
        self.cog = cog
        self.event_id = event_id

    async def on_submit(self, interaction):
        event = get_event(self.event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if not can_manage_event(interaction.user, event):
            return await interaction.response.send_message(
                "❌ Только рекрутеры и администраторы могут менять время.",
                ephemeral=True,
            )

        new_time = normalize_time(self.time.value)
        if not new_time:
            return await interaction.response.send_message(
                "❌ Время укажите в формате HH:MM, например 21:00.",
                ephemeral=True,
            )

        update_event(self.event_id, event_time=new_time)
        event = get_event(self.event_id)

        await interaction.response.edit_message(
            embed=build_embed(interaction.guild, event),
            view=ReactionView(self.cog, self.event_id),
        )


class UserEditModal(discord.ui.Modal):
    user_input = discord.ui.TextInput(
        label="ID пользователя или @упоминание",
        placeholder="123456789012345678",
        max_length=40,
        required=True,
    )

    def __init__(self, cog, event_id, action):
        super().__init__(title="Добавить участника" if action == "add" else "Убрать участника")
        self.cog = cog
        self.event_id = event_id
        self.action = action

    async def on_submit(self, interaction):
        event = get_event(self.event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if not can_manage_event(interaction.user, event):
            return await interaction.response.send_message(
                "❌ Только рекрутеры и администраторы могут редактировать список.",
                ephemeral=True,
            )

        raw = self.user_input.value.strip()
        match = re.search(r"\d{15,25}", raw)

        if not match:
            return await interaction.response.send_message(
                "❌ Укажи корректный Discord ID пользователя или его упоминание.",
                ephemeral=True,
            )

        user_id = int(match.group(0))
        participants = csv_ids(event.get("participants"))
        reserve = csv_ids(event.get("reserve"))

        if self.action == "remove":
            if user_id in participants:
                participants.remove(user_id)
            elif user_id in reserve:
                reserve.remove(user_id)
            else:
                return await interaction.response.send_message(
                    "❌ Пользователь не найден в списке.",
                    ephemeral=True,
                )

            slots = int(event.get("slots") or 0)
            promoted = None

            if slots > 0 and len(participants) < slots and reserve:
                promoted = reserve.pop(0)
                participants.append(promoted)

            save_participants(self.event_id, participants)
            save_reserve(self.event_id, reserve)

            text = "✅ Пользователь удалён из списка."
            if promoted:
                text += f"\n↗️ На освободившееся место добавлен <@{promoted}>."

        else:
            if user_id in participants or user_id in reserve:
                return await interaction.response.send_message(
                    "ℹ️ Пользователь уже есть в списке.",
                    ephemeral=True,
                )

            slots = int(event.get("slots") or 0)
            if slots <= 0 or len(participants) < slots:
                participants.append(user_id)
                text = "✅ Пользователь добавлен в основной состав."
            else:
                reserve.append(user_id)
                text = "✅ Основной состав заполнен. Пользователь добавлен в запас."

            save_participants(self.event_id, participants)
            save_reserve(self.event_id, reserve)

        await self.cog.refresh_collection_message(interaction, self.event_id)
        await self.cog.refresh_list_message(self.event_id)

        await interaction.response.send_message(
            text,
            ephemeral=True,
        )


# =========================================================
# COLLECTION VIEW
# =========================================================

class ReactionView(discord.ui.View):
    def __init__(self, cog, event_id):
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id

        self.join_button.custom_id = f"reaction:join:{event_id}"
        self.leave_button.custom_id = f"reaction:leave:{event_id}"
        self.time_button.custom_id = f"reaction:time:{event_id}"
        self.tag_button.custom_id = f"reaction:tag:{event_id}"
        self.remind_button.custom_id = f"reaction:remind:{event_id}"
        self.publish_button.custom_id = f"reaction:publish:{event_id}"

        event = get_event(event_id)
        if event and str(event.get("reaction_type") or "default").lower() != "vzp":
            self.remove_item(self.publish_button)

    @discord.ui.button(
        label="🎬 Поставить реакцию",
        style=discord.ButtonStyle.success,
        custom_id="reaction:join",
        row=0,
    )
    async def join_button(self, interaction, button):
        await self.cog.join(interaction, self.event_id)

    @discord.ui.button(
        label="❌ Убрать реакцию",
        style=discord.ButtonStyle.danger,
        custom_id="reaction:leave",
        row=0,
    )
    async def leave_button(self, interaction, button):
        await self.cog.leave(interaction, self.event_id)

    @discord.ui.button(
        label="🕒 Изменить время",
        style=discord.ButtonStyle.secondary,
        custom_id="reaction:time",
        row=0,
    )
    async def time_button(self, interaction, button):
        await self.cog.change_time(interaction, self.event_id)

    @discord.ui.button(
        label="🏷️ Тегнуть",
        style=discord.ButtonStyle.primary,
        custom_id="reaction:tag",
        row=1,
    )
    async def tag_button(self, interaction, button):
        await self.cog.tag_roles(interaction, self.event_id)

    @discord.ui.button(
        label="🔔 Напомнить о МП",
        style=discord.ButtonStyle.secondary,
        custom_id="reaction:remind",
        row=1,
    )
    async def remind_button(self, interaction, button):
        await self.cog.remind_members(interaction, self.event_id)

    @discord.ui.button(
        label="📋 Опубликовать список",
        style=discord.ButtonStyle.primary,
        custom_id="reaction:publish",
        row=2,
    )
    async def publish_button(self, interaction, button):
        await self.cog.publish_list(interaction, self.event_id)


# =========================================================
# PUBLISHED LIST VIEW
# =========================================================

class PublishedListView(discord.ui.View):
    def __init__(self, cog, event_id, result=False):
        super().__init__(timeout=None)
        self.cog = cog
        self.event_id = event_id

        if result:
            for item in list(self.children):
                if item is not self.cancel_result_button:
                    self.remove_item(item)

            self.cancel_result_button.custom_id = f"reaction:result_cancel:{event_id}"
            return

        self.remove_item(self.cancel_result_button)

        self.add_button.custom_id = f"reaction:list_add:{event_id}"
        self.remove_button.custom_id = f"reaction:list_remove:{event_id}"
        self.win_button.custom_id = f"reaction:win:{event_id}"
        self.lose_button.custom_id = f"reaction:lose:{event_id}"

    @discord.ui.button(
        label="➕ Добавить",
        style=discord.ButtonStyle.success,
        custom_id="reaction:list_add",
        row=0,
    )
    async def add_button(self, interaction, button):
        await self.cog.open_list_editor(interaction, self.event_id, "add")

    @discord.ui.button(
        label="➖ Убрать",
        style=discord.ButtonStyle.danger,
        custom_id="reaction:list_remove",
        row=0,
    )
    async def remove_button(self, interaction, button):
        await self.cog.open_list_editor(interaction, self.event_id, "remove")

    @discord.ui.button(
        label="WIN",
        style=discord.ButtonStyle.success,
        custom_id="reaction:win",
        row=0,
    )
    async def win_button(self, interaction, button):
        await self.cog.set_result(interaction, self.event_id, "win")

    @discord.ui.button(
        label="LOSE",
        style=discord.ButtonStyle.danger,
        custom_id="reaction:lose",
        row=0,
    )
    async def lose_button(self, interaction, button):
        await self.cog.set_result(interaction, self.event_id, "lose")

    @discord.ui.button(
        label="↩️ Отменить результат",
        style=discord.ButtonStyle.secondary,
        custom_id="reaction:result_cancel",
        row=1,
    )
    async def cancel_result_button(self, interaction, button):
        await self.cog.cancel_result(interaction, self.event_id)


# =========================================================
# COG
# =========================================================

class Reactions(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        ensure_reaction_database()
        print("✅ [SAVAGE][REACTIONS] База реакций готова")

    async def cog_load(self):
        pass

    async def restore_views(self):
        ensure_reaction_database()
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, list_message_id, result
                FROM reaction_events
                WHERE active=1
                """
            ).fetchall()
        finally:
            conn.close()

        restored = 0
        for row in rows:
            event_id = row["id"]
            try:
                self.bot.add_view(ReactionView(self, event_id))

                if row["list_message_id"]:
                    result = bool(str(row["result"] or "").strip())
                    self.bot.add_view(
                        PublishedListView(
                            self,
                            event_id,
                            result=result,
                        )
                    )

                restored += 1
            except Exception as error:
                print(
                    "[SAVAGE][REACTIONS] Ошибка восстановления "
                    f"event {event_id}: {type(error).__name__}: {error}"
                )

        print(
            "✅ [SAVAGE][REACTIONS] "
            f"Восстановлено наборов: {restored}"
        )

    # =====================================================
    # REFRESH
    # =====================================================

    async def refresh_collection_message(self, interaction, event_id):
        event = get_event(event_id)
        if not event or not event.get("message_id"):
            return

        channel = interaction.guild.get_channel(int(event["channel_id"]))
        if not channel:
            return

        try:
            message = await channel.fetch_message(int(event["message_id"]))
            await message.edit(
                embed=build_embed(interaction.guild, event),
                view=ReactionView(self, event_id),
            )
        except Exception as error:
            print(
                f"[SAVAGE][REACTIONS] Ошибка обновления набора: {error}"
            )

    async def refresh_list_message(self, event_id):
        event = get_event(event_id)
        if not event or not event.get("list_message_id"):
            return

        guild = self.bot.get_guild(int(event["guild_id"]))
        if not guild:
            return

        channel = guild.get_channel(int(event["channel_id"]))
        if not channel:
            return

        try:
            message = await channel.fetch_message(int(event["list_message_id"]))
            result = bool(str(event.get("result") or "").strip())
            await message.edit(
                embed=build_list_embed(guild, event),
                view=PublishedListView(self, event_id, result=result),
            )
        except Exception as error:
            print(
                f"[SAVAGE][REACTIONS] Ошибка обновления списка: {error}"
            )

    async def refresh(self, interaction, event_id):
        await self.refresh_collection_message(interaction, event_id)

    # =====================================================
    # JOIN
    # =====================================================

    async def join(self, interaction, event_id):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if not event.get("active"):
            return await interaction.response.send_message(
                "❌ Набор уже закрыт.",
                ephemeral=True,
            )

        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message(
                "❌ Не удалось определить участника.",
                ephemeral=True,
            )

        cfg = get_config(interaction.guild.id)
        priority = user_priority(cfg, interaction.user)

        if priority <= 0:
            return await interaction.response.send_message(
                "❌ Для участия нужна роль MAIN, DEFAULT или ACADEMY.",
                ephemeral=True,
            )

        participants = csv_ids(event.get("participants"))
        reserve = csv_ids(event.get("reserve"))
        user_id = interaction.user.id

        if user_id in participants:
            return await interaction.response.send_message(
                "ℹ️ Вы уже записаны.",
                ephemeral=True,
            )

        if user_id in reserve:
            return await interaction.response.send_message(
                "ℹ️ Вы уже находитесь в запасе.",
                ephemeral=True,
            )

        slots = int(event.get("slots") or 0)

        if slots <= 0:
            participants.append(user_id)
            save_participants(event_id, participants)

            await interaction.response.send_message(
                "✅ Вы записаны.",
                ephemeral=True,
            )
            await self.refresh(interaction, event_id)
            await self.refresh_list_message(event_id)
            return

        if len(participants) < slots:
            participants.append(user_id)
            save_participants(event_id, participants)

            await interaction.response.send_message(
                "✅ Вы записаны.",
                ephemeral=True,
            )
            await self.refresh(interaction, event_id)
            await self.refresh_list_message(event_id)
            return

        member_priorities = {}
        for participant_id in participants:
            member = interaction.guild.get_member(participant_id)
            member_priorities[participant_id] = (
                user_priority(cfg, member) if member else 0
            )

        lower_priority = [
            participant_id
            for participant_id in participants
            if member_priorities.get(participant_id, 0) < priority
        ]

        if not lower_priority:
            reserve.append(user_id)
            save_reserve(event_id, reserve)

            await interaction.response.send_message(
                "❌ Все основные места заняты участниками "
                "с равным или более высоким приоритетом.\n\n"
                "Вы добавлены в **запас**.",
                ephemeral=True,
            )
            await self.refresh(interaction, event_id)
            await self.refresh_list_message(event_id)
            return

        victim = min(
            lower_priority,
            key=lambda uid: (
                member_priorities.get(uid, 0),
                participants.index(uid),
            ),
        )

        victim_index = participants.index(victim)
        participants[victim_index] = user_id
        reserve.append(victim)

        save_participants(event_id, participants)
        save_reserve(event_id, reserve)

        await interaction.response.send_message(
            f"✅ Вы заняли основное место.\n"
            f"Вытеснен: <@{victim}>.\n"
            f"Он добавлен в **запас**.",
            ephemeral=True,
        )

        await self.refresh(interaction, event_id)
        await self.refresh_list_message(event_id)

    # =====================================================
    # LEAVE
    # =====================================================

    async def leave(self, interaction, event_id):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        user_id = interaction.user.id
        participants = csv_ids(event.get("participants"))
        reserve = csv_ids(event.get("reserve"))

        if user_id in participants:
            participants.remove(user_id)
            slots = int(event.get("slots") or 0)

            if slots > 0 and reserve and len(participants) < slots:
                replacement = reserve.pop(0)
                participants.append(replacement)

                save_participants(event_id, participants)
                save_reserve(event_id, reserve)

                text = (
                    "✅ Вы убрали реакцию.\n"
                    f"На ваше место автоматически встал "
                    f"<@{replacement}> из запаса."
                )
            else:
                save_participants(event_id, participants)
                text = "✅ Реакция убрана."

            await interaction.response.send_message(text, ephemeral=True)
            await self.refresh(interaction, event_id)
            await self.refresh_list_message(event_id)
            return

        if user_id in reserve:
            reserve.remove(user_id)
            save_reserve(event_id, reserve)

            await interaction.response.send_message(
                "✅ Вы убраны из запаса.",
                ephemeral=True,
            )
            await self.refresh(interaction, event_id)
            await self.refresh_list_message(event_id)
            return

        await interaction.response.send_message(
            "ℹ️ Вы не записаны на этот набор.",
            ephemeral=True,
        )

    # =====================================================
    # CHANGE TIME
    # =====================================================

    async def change_time(self, interaction, event_id):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if not can_manage_event(interaction.user, event):
            return await interaction.response.send_message(
                "❌ Только рекрутеры и администраторы могут менять время.",
                ephemeral=True,
            )

        await interaction.response.send_modal(TimeModal(self, event_id))

    # =====================================================
    # TAG ROLES
    # =====================================================

    async def tag_roles(self, interaction, event_id):
        if not is_recruiter(interaction.user):
            return await interaction.response.send_message(
                "❌ Только рекрутеры могут тегать роли.",
                ephemeral=True,
            )

        event = get_event(event_id)
        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        reaction_type = str(event.get("reaction_type") or "default").lower()

        if reaction_type == "vzp":
            role_mentions = get_vzp_tag_mention(interaction.guild)
            if not role_mentions:
                return await interaction.response.send_message(
                    f"❌ Роль VZP `{VZP_TAG_ROLE_ID}` не найдена на сервере.",
                    ephemeral=True,
                )
        else:
            role_mentions = get_reaction_mentions(interaction.guild)
            if not role_mentions:
                return await interaction.response.send_message(
                    "❌ Роли MAIN / DEFAULT / ACADEMY не настроены.",
                    ephemeral=True,
                )

        await interaction.response.send_message(
            role_mentions,
            allowed_mentions=role_allowed_mentions(),
        )

    # =====================================================
    # REMINDER
    # =====================================================

    async def remind_members(self, interaction, event_id):
        if not is_recruiter(interaction.user):
            return await interaction.response.send_message(
                "❌ Только рекрутеры могут отправлять напоминания.",
                ephemeral=True,
            )

        event = get_event(event_id)
        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        member_ids = []
        for user_id in csv_ids(event.get("participants")) + csv_ids(event.get("reserve")):
            if user_id not in member_ids:
                member_ids.append(user_id)

        if not member_ids:
            return await interaction.response.send_message(
                "❌ Пока никто не откликнулся на МП.",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)

        success = 0
        failed = 0

        for user_id in member_ids:
            member = interaction.guild.get_member(user_id)

            if not member:
                try:
                    member = await interaction.guild.fetch_member(user_id)
                except Exception:
                    failed += 1
                    continue

            try:
                await member.send(
                    "# 🔔 Напоминание!\n\n"
                    f"В **{event['event_time']}** "
                    f"у вас контент **{event['title']}**.\n\n"
                    "Не забудьте быть вовремя."
                )
                success += 1
            except (discord.Forbidden, discord.HTTPException):
                failed += 1

        await interaction.followup.send(
            "🔔 **Напоминания отправлены.**\n\n"
            f"Получили сообщение: **{success}**\n"
            f"Не удалось отправить: **{failed}**",
            ephemeral=True,
        )

    # =====================================================
    # PUBLISH LIST
    # =====================================================

    async def publish_list(self, interaction, event_id):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if not can_manage_event(interaction.user, event):
            return await interaction.response.send_message(
                "❌ Только рекрутеры и администраторы могут публиковать список.",
                ephemeral=True,
            )

        channel = interaction.guild.get_channel(int(event["channel_id"]))
        if not channel:
            return await interaction.response.send_message(
                "❌ Канал мероприятия не найден.",
                ephemeral=True,
            )

        existing_id = int(event.get("list_message_id") or 0)

        if existing_id:
            try:
                message = await channel.fetch_message(existing_id)
                await message.edit(
                    embed=build_list_embed(interaction.guild, event),
                    view=PublishedListView(
                        self,
                        event_id,
                        result=bool(str(event.get("result") or "").strip()),
                    ),
                )
                return await interaction.response.send_message(
                    "✅ Опубликованный список обновлён.",
                    ephemeral=True,
                )
            except (discord.NotFound, discord.HTTPException):
                pass

        await interaction.response.send_message(
            "📋 Список опубликован.",
            ephemeral=True,
        )

        message = await channel.send(
            embed=build_list_embed(interaction.guild, event),
            view=PublishedListView(self, event_id),
        )

        update_event(event_id, list_message_id=message.id)

    # =====================================================
    # EDIT PUBLISHED LIST
    # =====================================================

    async def open_list_editor(self, interaction, event_id, action):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if str(event.get("result") or "").strip():
            return await interaction.response.send_message(
                "❌ Результат уже установлен. Сначала отмените результат.",
                ephemeral=True,
            )

        if not can_manage_event(interaction.user, event):
            return await interaction.response.send_message(
                "❌ Только рекрутеры и администраторы могут редактировать список.",
                ephemeral=True,
            )

        await interaction.response.send_modal(
            UserEditModal(self, event_id, action)
        )

    # =====================================================
    # RESULT
    # =====================================================

    async def set_result(self, interaction, event_id, result):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if str(event.get("reaction_type") or "default").lower() != "vzp":
            return await interaction.response.send_message(
                "❌ Для обычных реакций публикация списка недоступна.",
                ephemeral=True,
            )

        if not can_manage_event(interaction.user, event):
            return await interaction.response.send_message(
                "❌ Только рекрутеры и администраторы могут выставлять результат.",
                ephemeral=True,
            )

        if not event.get("list_message_id"):
            return await interaction.response.send_message(
                "❌ Сначала опубликуйте список.",
                ephemeral=True,
            )

        update_event(event_id, result=result)
        event = get_event(event_id)

        await self.refresh_list_message(event_id)

        await interaction.response.send_message(
            f"✅ Результат установлен: **{result.upper()}**.",
            ephemeral=True,
        )

    async def cancel_result(self, interaction, event_id):
        event = get_event(event_id)

        if not event:
            return await interaction.response.send_message(
                "❌ Мероприятие не найдено.",
                ephemeral=True,
            )

        if not is_admin(interaction.user):
            return await interaction.response.send_message(
                "❌ Только администратор может отменить результат.",
                ephemeral=True,
            )

        update_event(event_id, result="")
        await self.refresh_list_message(event_id)

        await interaction.response.send_message(
            "↩️ Результат отменён. Список восстановлен.",
            ephemeral=True,
        )

    # =====================================================
    # COMMANDS
    # =====================================================

    @app_commands.command(
        name="reaction",
        description="Запустить обычный набор на контент",
    )
    async def reaction(self, interaction):
        try:
            if not interaction.guild:
                return await interaction.response.send_message(
                    "❌ Эта команда работает только на сервере.",
                    ephemeral=True,
                )

            if not can_start_reaction(interaction.user):
                return await interaction.response.send_message(
                    "❌ У вас нет права запускать обычный набор.",
                    ephemeral=True,
                )

            await interaction.response.send_modal(
                ReactionModal(self, "default")
            )

        except Exception as error:
            print(
                "[SAVAGE][REACTIONS] /reaction: "
                f"{type(error).__name__}: {error}"
            )

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Не удалось открыть форму.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Не удалось открыть форму.",
                        ephemeral=True,
                    )
            except Exception:
                pass

    @app_commands.command(
        name="reaction-vzp",
        description="Запустить набор VZP",
    )
    async def reaction_vzp(self, interaction):
        try:
            if not interaction.guild:
                return await interaction.response.send_message(
                    "❌ Эта команда работает только на сервере.",
                    ephemeral=True,
                )

            if not can_start_vzp(interaction.user):
                return await interaction.response.send_message(
                    "❌ У вас нет права запускать VZP.",
                    ephemeral=True,
                )

            await interaction.response.send_modal(
                ReactionModal(self, "vzp")
            )

        except Exception as error:
            print(
                "[SAVAGE][REACTIONS] /reaction-vzp: "
                f"{type(error).__name__}: {error}"
            )

            try:
                if interaction.response.is_done():
                    await interaction.followup.send(
                        "❌ Не удалось открыть форму VZP.",
                        ephemeral=True,
                    )
                else:
                    await interaction.response.send_message(
                        "❌ Не удалось открыть форму VZP.",
                        ephemeral=True,
                    )
            except Exception:
                pass


# =========================================================
# SETUP
# =========================================================

async def setup(bot):
    await bot.add_cog(Reactions(bot))
    print("✅ reactions.py загружен")
