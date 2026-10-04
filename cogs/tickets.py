import discord
from discord.ext import commands
from discord import app_commands

import sqlite3
import os
import re
from datetime import datetime


# ============================================================
#                 S A V A G E • TICKETS
# ============================================================

DB_PATH = os.path.join("database", "savage.db")

MAX_QUESTIONS = 5


DEFAULT_QUESTIONS = {
    1: "Ваш никнейм",
    2: "Ваш OOC возраст",
    3: "Ваш часовой пояс",
    4: "Ваш LVL персонажа",
    5: "Ваша цель вступления",
}


# ============================================================
#                         DATABASE
# ============================================================

def get_connection():
    os.makedirs("database", exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    return conn


def init_database():
    conn = get_connection()
    cursor = conn.cursor()

    # --------------------------------------------------------
    # Настройки
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticket_settings (
            guild_id INTEGER PRIMARY KEY,
            staff_role_id TEXT,
            member_role_id INTEGER,
            open_category_id INTEGER,
            closed_category_id INTEGER,
            panel_channel_id INTEGER
        )
    """)

    # --------------------------------------------------------
    # Миграция старой БД
    # --------------------------------------------------------

    cursor.execute(
        "PRAGMA table_info(ticket_settings)"
    )

    columns = {
        row["name"]
        for row in cursor.fetchall()
    }

    if "staff_role_id" not in columns:
        cursor.execute("""
            ALTER TABLE ticket_settings
            ADD COLUMN staff_role_id TEXT
        """)

    if "panel_channel_id" not in columns:
        cursor.execute("""
            ALTER TABLE ticket_settings
            ADD COLUMN panel_channel_id INTEGER
        """)

    # Старое поле application_channel_id не удаляем,
    # чтобы старая БД не ломалась.

    # --------------------------------------------------------
    # Вопросы
    # --------------------------------------------------------

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ticket_questions (
            guild_id INTEGER,
            question_number INTEGER,
            question TEXT NOT NULL,
            PRIMARY KEY (guild_id, question_number)
        )
    """)

    conn.commit()
    conn.close()


def ensure_guild_settings(guild_id: int):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM ticket_settings
        WHERE guild_id = ?
    """, (guild_id,))

    if cursor.fetchone() is None:

        cursor.execute("""
            INSERT INTO ticket_settings (
                guild_id,
                staff_role_id,
                member_role_id,
                open_category_id,
                closed_category_id,
                panel_channel_id
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            guild_id,
            "",
            None,
            None,
            None,
            None
        ))

    # --------------------------------------------------------
    # Стандартные вопросы
    # --------------------------------------------------------

    for number, question in DEFAULT_QUESTIONS.items():

        cursor.execute("""
            SELECT question
            FROM ticket_questions
            WHERE guild_id = ?
            AND question_number = ?
        """, (
            guild_id,
            number
        ))

        if cursor.fetchone() is None:

            cursor.execute("""
                INSERT INTO ticket_questions (
                    guild_id,
                    question_number,
                    question
                )
                VALUES (?, ?, ?)
            """, (
                guild_id,
                number,
                question
            ))

    conn.commit()
    conn.close()


def get_settings(guild_id: int):
    ensure_guild_settings(guild_id)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM ticket_settings
        WHERE guild_id = ?
    """, (guild_id,))

    result = cursor.fetchone()

    conn.close()

    return result


def update_setting(
    guild_id: int,
    column: str,
    value
):
    allowed_columns = {
        "staff_role_id",
        "member_role_id",
        "open_category_id",
        "closed_category_id",
        "panel_channel_id",
    }

    if column not in allowed_columns:
        raise ValueError(
            "Недопустимая настройка."
        )

    ensure_guild_settings(guild_id)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"""
        UPDATE ticket_settings
        SET {column} = ?
        WHERE guild_id = ?
        """,
        (
            value,
            guild_id
        )
    )

    conn.commit()
    conn.close()


# ============================================================
#                       STAFF ROLES
# ============================================================

def get_staff_role_ids(guild_id: int):
    settings = get_settings(guild_id)

    raw = settings["staff_role_id"]

    if not raw:
        return []

    raw = str(raw).strip()

    if not raw:
        return []

    result = []

    for value in raw.split(","):

        value = value.strip()

        if not value:
            continue

        try:
            role_id = int(value)

            if role_id not in result:
                result.append(role_id)

        except ValueError:
            continue

    return result


def save_staff_role_ids(
    guild_id: int,
    role_ids: list[int]
):
    unique_ids = []

    for role_id in role_ids:

        if role_id not in unique_ids:
            unique_ids.append(role_id)

    value = ",".join(
        str(role_id)
        for role_id in unique_ids
    )

    update_setting(
        guild_id,
        "staff_role_id",
        value
    )


def add_staff_role(
    guild_id: int,
    role_id: int
):
    role_ids = get_staff_role_ids(guild_id)

    if role_id not in role_ids:
        role_ids.append(role_id)

    save_staff_role_ids(
        guild_id,
        role_ids
    )


def remove_staff_role(
    guild_id: int,
    role_id: int
):
    role_ids = get_staff_role_ids(guild_id)

    role_ids = [
        x for x in role_ids
        if x != role_id
    ]

    save_staff_role_ids(
        guild_id,
        role_ids
    )


# ============================================================
#                         QUESTIONS
# ============================================================

def get_questions(guild_id: int):
    ensure_guild_settings(guild_id)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT question_number, question
        FROM ticket_questions
        WHERE guild_id = ?
        ORDER BY question_number
    """, (
        guild_id,
    ))

    result = cursor.fetchall()

    conn.close()

    return result


def get_question(
    guild_id: int,
    number: int
):
    ensure_guild_settings(guild_id)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT question
        FROM ticket_questions
        WHERE guild_id = ?
        AND question_number = ?
    """, (
        guild_id,
        number
    ))

    result = cursor.fetchone()

    conn.close()

    if result:
        return result["question"]

    return None


def add_question(
    guild_id: int,
    number: int,
    question: str
):
    ensure_guild_settings(guild_id)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT OR REPLACE INTO ticket_questions (
            guild_id,
            question_number,
            question
        )
        VALUES (?, ?, ?)
    """, (
        guild_id,
        number,
        question.strip()
    ))

    conn.commit()
    conn.close()


def delete_question(
    guild_id: int,
    number: int
):
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        DELETE FROM ticket_questions
        WHERE guild_id = ?
        AND question_number = ?
    """, (
        guild_id,
        number
    ))

    conn.commit()
    conn.close()


# ============================================================
#                     TICKET USER ID
# ============================================================

def get_user_id_from_ticket(
    channel: discord.TextChannel
):

    # --------------------------------------------------------
    # Основной способ — topic
    # --------------------------------------------------------

    if channel.topic:

        match = re.search(
            r"SAVAGE_TICKET_USER:(\d+)",
            channel.topic
        )

        if match:
            return int(match.group(1))

    # --------------------------------------------------------
    # Запасной вариант
    # --------------------------------------------------------

    match = re.search(
        r"заявка-(\d+)",
        channel.name
    )

    if match:
        return int(match.group(1))

    # --------------------------------------------------------
    # Ищем Discord ID в topic
    # --------------------------------------------------------

    if channel.topic:

        match = re.search(
            r"(\d{15,25})",
            channel.topic
        )

        if match:
            return int(match.group(1))

    return None


# ============================================================
#                    CHANNEL NAME
# ============================================================

def clean_channel_name(
    member: discord.Member
):
    name = member.display_name.lower()

    name = re.sub(
        r"[^a-zA-Zа-яА-Я0-9_-]+",
        "",
        name
    )

    if not name:
        name = str(member.id)

    return f"заявка-{name}"[:90]


# ============================================================
#                    FIND MEMBER
# ============================================================

async def find_member(
    guild: discord.Guild,
    user_id: int
):
    member = guild.get_member(user_id)

    if member:
        return member

    try:
        return await guild.fetch_member(
            user_id
        )

    except discord.NotFound:
        return None

    except discord.HTTPException:
        return None


# ============================================================
#                    STAFF CHECK
# ============================================================

def is_staff(
    member: discord.Member,
    staff_role_ids
):

    if member.guild_permissions.administrator:
        return True

    if not staff_role_ids:
        return False

    member_role_ids = {
        role.id
        for role in member.roles
    }

    return bool(
        member_role_ids.intersection(
            set(staff_role_ids)
        )
    )


# ============================================================
#                    CLOSE TICKET
# ============================================================

async def close_ticket(
    channel: discord.TextChannel,
    applicant: discord.Member | None,
    closed_category: discord.CategoryChannel | None
):

    if applicant:

        try:

            await channel.set_permissions(
                applicant,
                view_channel=False,
                send_messages=False,
                read_message_history=False,
                connect=False
            )

        except discord.HTTPException:
            pass

    if closed_category:

        try:

            await channel.edit(
                category=closed_category
            )

        except discord.HTTPException:
            pass


# ============================================================
#                  UPDATE APPLICATION MESSAGE
# ============================================================

async def update_application_message(
    message: discord.Message,
    status: str,
    color: discord.Color,
    result_text: str
):
    """
    Меняет главное сообщение заявки:

    🟡 На рассмотрении
    🟢 Принят
    🔴 Отклонён

    После принятия/отклонения кнопки убираются.
    """

    if not message.embeds:
        return

    old_embed = message.embeds[0]

    embed = discord.Embed(
        title=old_embed.title or "📋 Заявка в S A V A G E",
        description=old_embed.description or "",
        color=color,
        timestamp=old_embed.timestamp
    )

    # --------------------------------------------------------
    # Thumbnail
    # --------------------------------------------------------

    if old_embed.thumbnail.url:
        embed.set_thumbnail(
            url=old_embed.thumbnail.url
        )

    # --------------------------------------------------------
    # Переносим существующие поля
    # --------------------------------------------------------

    for field in old_embed.fields:

        # Старый статус заменяем новым
        if field.name == "Статус":
            continue

        # Старый результат тоже заменяем
        if field.name == "Результат":
            continue

        embed.add_field(
            name=field.name,
            value=field.value,
            inline=field.inline
        )

    # --------------------------------------------------------
    # Новый статус
    # --------------------------------------------------------

    embed.add_field(
        name="Статус",
        value=status,
        inline=False
    )

    # --------------------------------------------------------
    # Результат
    # --------------------------------------------------------

    embed.add_field(
        name="Результат",
        value=result_text,
        inline=False
    )

    # --------------------------------------------------------
    # Footer
    # --------------------------------------------------------

    if old_embed.footer.text:
        embed.set_footer(
            text=old_embed.footer.text
        )
    else:
        embed.set_footer(
            text="S A V A G E • Система заявок"
        )

    await message.edit(
        embed=embed,
        view=None
    )


# ============================================================
#                         MODAL
# ============================================================

class ApplicationModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        guild_id: int,
        questions
    ):

        super().__init__(
            title="Заявка в S A V A G E"
        )

        self.cog = cog
        self.guild_id = guild_id
        self.questions = questions

        self.inputs = []

        for row in questions[:MAX_QUESTIONS]:

            number = int(
                row["question_number"]
            )

            question = str(
                row["question"]
            ).strip()

            text_input = discord.ui.TextInput(
                label=(
                    f"{number}. {question}"
                )[:45],

                placeholder=(
                    "Введите ваш ответ..."
                ),

                required=True,

                max_length=1000,

                style=discord.TextStyle.paragraph
            )

            self.inputs.append(
                text_input
            )

            self.add_item(
                text_input
            )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        try:

            await self.cog.create_ticket(
                interaction,
                self.questions,
                self.inputs
            )

        except Exception as error:

            await self.cog.safe_error(
                interaction,
                error,
                "отправка анкеты"
            )


# ============================================================
#                  REJECT MODAL
# ============================================================

class RejectModal(discord.ui.Modal):

    def __init__(
        self,
        cog,
        channel,
        application_message
    ):

        super().__init__(
            title="Отклонение заявки"
        )

        self.cog = cog
        self.channel = channel
        self.application_message = application_message

        self.reason = discord.ui.TextInput(
            label="Причина отказа",

            placeholder=(
                "Введите причину отказа..."
            ),

            required=True,

            max_length=1000,

            style=discord.TextStyle.paragraph
        )

        self.add_item(
            self.reason
        )

    async def on_submit(
        self,
        interaction: discord.Interaction
    ):

        try:

            await self.cog.reject_ticket(
                interaction,
                self.channel,
                str(self.reason.value),
                self.application_message
            )

        except Exception as error:

            await self.cog.safe_error(
                interaction,
                error,
                "отклонение заявки"
            )


# ============================================================
#                    VOICE SELECT
# ============================================================

class VoiceChannelSelect(
    discord.ui.Select
):

    def __init__(
        self,
        cog,
        ticket_channel
    ):

        self.cog = cog
        self.ticket_channel = ticket_channel

        guild = ticket_channel.guild

        me = guild.me

        channels = [
            channel
            for channel in guild.voice_channels
            if me
            and channel.permissions_for(me).connect
        ]

        options = []

        for channel in channels[:25]:

            options.append(
                discord.SelectOption(
                    label=channel.name[:100],
                    value=str(channel.id),
                    emoji="🔊"
                )
            )

        if not options:

            options.append(
                discord.SelectOption(
                    label="Нет доступных голосовых каналов",
                    value="none"
                )
            )

        super().__init__(
            placeholder="Выберите голосовой канал ожидания...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(
        self,
        interaction: discord.Interaction
    ):

        if self.values[0] == "none":

            await interaction.response.send_message(
                "❌ Нет доступных голосовых каналов.",
                ephemeral=True
            )

            return

        try:

            channel_id = int(
                self.values[0]
            )

        except ValueError:

            await interaction.response.send_message(
                "❌ Некорректный голосовой канал.",
                ephemeral=True
            )

            return

        voice_channel = interaction.guild.get_channel(
            channel_id
        )

        if not isinstance(
            voice_channel,
            discord.VoiceChannel
        ):

            await interaction.response.send_message(
                "❌ Голосовой канал не найден.",
                ephemeral=True
            )

            return

        try:

            await self.cog.call_to_voice(
                interaction,
                self.ticket_channel,
                voice_channel
            )

        except Exception as error:

            await self.cog.safe_error(
                interaction,
                error,
                "обзвон"
            )


class VoiceChannelView(discord.ui.View):

    def __init__(
        self,
        cog,
        ticket_channel
    ):

        super().__init__(
            timeout=120
        )

        self.add_item(
            VoiceChannelSelect(
                cog,
                ticket_channel
            )
        )


# ============================================================
#                    PANEL VIEW
# ============================================================

class TicketPanelView(
    discord.ui.View
):

    def __init__(
        self,
        cog
    ):

        super().__init__(
            timeout=None
        )

        self.cog = cog

    @discord.ui.button(
        label="Подать заявку",
        emoji="📋",
        style=discord.ButtonStyle.primary,
        custom_id="savage_ticket_create"
    )
    async def create_ticket_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        try:

            await self.cog.open_application(
                interaction
            )

        except Exception as error:

            await self.cog.safe_error(
                interaction,
                error,
                "кнопка подачи заявки"
            )


# ============================================================
#                    ACTIONS VIEW
# ============================================================

class TicketActionsView(
    discord.ui.View
):

    def __init__(
        self,
        cog
    ):

        super().__init__(
            timeout=None
        )

        self.cog = cog

    @discord.ui.button(
        label="Отклонить",
        emoji="❌",
        style=discord.ButtonStyle.danger,
        custom_id="savage_ticket_reject"
    )
    async def reject_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cog.start_reject(
            interaction
        )

    @discord.ui.button(
        label="Принять",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="savage_ticket_accept"
    )
    async def accept_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cog.accept_ticket(
            interaction
        )

    @discord.ui.button(
        label="Обзвон",
        emoji="📞",
        style=discord.ButtonStyle.primary,
        custom_id="savage_ticket_call"
    )
    async def call_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button
    ):

        await self.cog.start_call(
            interaction
        )


# ============================================================
#                     TICKET COG
# ============================================================

class Tickets(commands.Cog):

    def __init__(
        self,
        bot
    ):

        self.bot = bot

        init_database()

    async def cog_load(self):

        self.bot.add_view(
            TicketPanelView(
                self
            )
        )

        self.bot.add_view(
            TicketActionsView(
                self
            )
        )

        print(
            "✅ Persistent-кнопки tickets загружены"
        )

    # ========================================================
    #                    SAFE ERROR
    # ========================================================

    async def safe_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        where: str
    ):

        print(
            f"[SAVAGE][TICKETS] "
            f"{where}: "
            f"{type(error).__name__}: "
            f"{error}"
        )

        message = (
            "❌ Произошла ошибка системы заявок.\n"
            f"Место: `{where}`\n"
            f"Ошибка: `{type(error).__name__}`"
        )

        try:

            if interaction.response.is_done():

                await interaction.followup.send(
                    message,
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )

        except Exception as send_error:

            print(
                "[SAVAGE][TICKETS] "
                f"Не удалось отправить ошибку: "
                f"{send_error}"
            )

    # ========================================================
    #                    STAFF CHECK
    # ========================================================

    async def check_staff(
        self,
        interaction: discord.Interaction
    ):

        if not interaction.guild:

            if not interaction.response.is_done():

                await interaction.response.send_message(
                    "❌ Эта команда работает только на сервере.",
                    ephemeral=True
                )

            return False

        get_settings(
            interaction.guild.id
        )

        staff_roles = get_staff_role_ids(
            interaction.guild.id
        )

        if not is_staff(
            interaction.user,
            staff_roles
        ):

            if interaction.response.is_done():

                await interaction.followup.send(
                    "❌ У вас нет прав для управления заявками.",
                    ephemeral=True
                )

            else:

                await interaction.response.send_message(
                    "❌ У вас нет прав для управления заявками.",
                    ephemeral=True
                )

            return False

        return True

    # ========================================================
    #                  OPEN APPLICATION
    # ========================================================

    async def open_application(
        self,
        interaction: discord.Interaction
    ):

        guild = interaction.guild

        if not guild:

            await interaction.response.send_message(
                "❌ Команда работает только на сервере.",
                ephemeral=True
            )

            return

        settings = get_settings(
            guild.id
        )

        # ----------------------------------------------------
        # Проверяем канал панели
        # ----------------------------------------------------

        panel_channel_id = settings[
            "panel_channel_id"
        ]

        if panel_channel_id:

            if interaction.channel_id != panel_channel_id:

                await interaction.response.send_message(
                    "❌ Подать заявку можно только "
                    "в назначенном канале.",
                    ephemeral=True
                )

                return

        # ----------------------------------------------------
        # Проверяем категорию
        # ----------------------------------------------------

        open_category_id = settings[
            "open_category_id"
        ]

        if not open_category_id:

            await interaction.response.send_message(
                "❌ Не назначена категория новых заявок.\n\n"
                "Используйте:\n"
                "`/ticket set-open-category`",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Вопросы
        # ----------------------------------------------------

        questions = get_questions(
            guild.id
        )

        if not questions:

            await interaction.response.send_message(
                "❌ Вопросы заявки не настроены.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Уже есть заявка?
        # ----------------------------------------------------

        category = guild.get_channel(
            open_category_id
        )

        if isinstance(
            category,
            discord.CategoryChannel
        ):

            for channel in category.text_channels:

                user_id = get_user_id_from_ticket(
                    channel
                )

                if user_id == interaction.user.id:

                    await interaction.response.send_message(
                        "❌ У вас уже есть открытая заявка.",
                        ephemeral=True
                    )

                    return

        # ----------------------------------------------------
        # Показываем Modal
        # ----------------------------------------------------

        modal = ApplicationModal(
            self,
            guild.id,
            questions
        )

        await interaction.response.send_modal(
            modal
        )

    # ========================================================
    #                   CREATE TICKET
    # ========================================================

    async def create_ticket(
        self,
        interaction: discord.Interaction,
        questions,
        inputs
    ):

        guild = interaction.guild
        member = interaction.user

        if not guild:

            await interaction.response.send_message(
                "❌ Ошибка сервера.",
                ephemeral=True
            )

            return

        settings = get_settings(
            guild.id
        )

        open_category_id = settings[
            "open_category_id"
        ]

        if not open_category_id:

            await interaction.response.send_message(
                "❌ Не назначена категория новых заявок.\n"
                "Используйте `/ticket set-open-category`.",
                ephemeral=True
            )

            return

        category = guild.get_channel(
            open_category_id
        )

        if not isinstance(
            category,
            discord.CategoryChannel
        ):

            await interaction.response.send_message(
                "❌ Категория новых заявок не найдена.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Проверка существующей заявки
        # ----------------------------------------------------

        for channel in category.text_channels:

            user_id = get_user_id_from_ticket(
                channel
            )

            if user_id == member.id:

                await interaction.response.send_message(
                    "❌ У вас уже есть открытая заявка.",
                    ephemeral=True
                )

                return

        # ----------------------------------------------------
        # Permissions
        # ----------------------------------------------------

        overwrites = {

            guild.default_role:
                discord.PermissionOverwrite(
                    view_channel=False
                ),

            member:
                discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    attach_files=True,
                    embed_links=True
                )
        }

        staff_role_ids = get_staff_role_ids(
            guild.id
        )

        for role_id in staff_role_ids:

            role = guild.get_role(
                role_id
            )

            if role:

                overwrites[role] = (
                    discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        manage_messages=True,
                        attach_files=True,
                        embed_links=True
                    )
                )

        # ----------------------------------------------------
        # Создание
        # ----------------------------------------------------

        channel_name = clean_channel_name(
            member
        )

        topic = (
            f"SAVAGE_TICKET_USER:{member.id} | "
            f"Создано: "
            f"{datetime.now().strftime('%d.%m.%Y %H:%M')}"
        )

        try:

            channel = await guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=topic,
                reason=f"Создание заявки {member}"
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Бот не может создать канал.\n"
                "Проверьте право **Управление каналами**.",
                ephemeral=True
            )

            return

        except discord.HTTPException as error:

            await interaction.response.send_message(
                f"❌ Discord не смог создать заявку.\n"
                f"`{error}`",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Ответ пользователю
        # ----------------------------------------------------

        await interaction.response.send_message(
            f"✅ Заявка создана: {channel.mention}",
            ephemeral=True
        )

        # ----------------------------------------------------
        # Embed
        # ----------------------------------------------------

        embed = discord.Embed(
            title="📋 Заявка в S A V A G E",

            description=(
                f"**Заявитель:** {member.mention}\n"
                f"**Тег:** `{member}`\n"
                f"**Discord ID:** `{member.id}`"
            ),

            color=discord.Color.yellow(),

            timestamp=datetime.now()
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        # ----------------------------------------------------
        # Ответы
        # ----------------------------------------------------

        for question, text_input in zip(
            questions,
            inputs
        ):

            answer = str(
                text_input.value
            ).strip()

            if not answer:
                answer = "Не указано"

            embed.add_field(
                name=(
                    f"{question['question_number']}. "
                    f"{question['question']}"
                )[:256],

                value=answer[:1024],

                inline=False
            )

        # ----------------------------------------------------
        # Статус
        # ----------------------------------------------------

        embed.add_field(
            name="Статус",
            value="🟡 На рассмотрении",
            inline=False
        )

        embed.set_footer(
            text="S A V A G E • Система заявок"
        )

        # ----------------------------------------------------
        # Mention staff
        # ----------------------------------------------------

        mentions = [
            member.mention
        ]

        for role_id in staff_role_ids:

            role = guild.get_role(
                role_id
            )

            if role:

                mentions.append(
                    role.mention
                )

        await channel.send(
            content=" ".join(mentions),
            embed=embed,
            view=TicketActionsView(self)
        )

    # ========================================================
    #                       REJECT
    # ========================================================

    async def start_reject(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        if not isinstance(
            interaction.channel,
            discord.TextChannel
        ):
            return

        application_message = interaction.message

        await interaction.response.send_modal(
            RejectModal(
                self,
                interaction.channel,
                application_message
            )
        )

    async def reject_ticket(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        reason: str,
        application_message: discord.Message
    ):

        guild = interaction.guild

        if not guild:
            return

        user_id = get_user_id_from_ticket(
            channel
        )

        if not user_id:

            await interaction.response.send_message(
                "❌ Не удалось определить заявителя.",
                ephemeral=True
            )

            return

        applicant = await find_member(
            guild,
            user_id
        )

        settings = get_settings(
            guild.id
        )

        closed_category = None

        if settings["closed_category_id"]:

            closed_category = guild.get_channel(
                settings["closed_category_id"]
            )

        # ----------------------------------------------------
        # DM
        # ----------------------------------------------------

        if applicant:

            try:

                embed = discord.Embed(
                    title="S A V A G E • Заявка отклонена",

                    description=(
                        "К сожалению, ваша заявка была "
                        "отклонена.\n\n"
                        f"**Причина:** {reason}"
                    ),

                    color=discord.Color.red()
                )

                await applicant.send(
                    embed=embed
                )

            except discord.Forbidden:
                pass

        # ----------------------------------------------------
        # Обновляем главное сообщение заявки
        # ----------------------------------------------------

        await update_application_message(
            application_message,
            "🔴 Отклонена",
            discord.Color.red(),
            f"Отклонено по причине: {reason}"
        )

        # ----------------------------------------------------
        # Закрываем заявку
        # ----------------------------------------------------

        await close_ticket(
            channel,
            applicant,
            closed_category
        )

        # ----------------------------------------------------
        # Ответ в тикете
        # ----------------------------------------------------

        result_embed = discord.Embed(
            title="❌ Заявка отклонена",

            description=(
                f"**Рекрутер:** "
                f"{interaction.user.mention}\n"
                f"**Причина:** {reason}"
            ),

            color=discord.Color.red()
        )

        await channel.send(
            embed=result_embed
        )

        await interaction.response.send_message(
            "✅ Заявка отклонена.",
            ephemeral=True
        )

    # ========================================================
    #                       ACCEPT
    # ========================================================

    async def accept_ticket(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return

        guild = interaction.guild

        if not guild:
            return

        user_id = get_user_id_from_ticket(
            channel
        )

        if not user_id:

            await interaction.response.send_message(
                "❌ Не удалось определить заявителя.",
                ephemeral=True
            )

            return

        applicant = await find_member(
            guild,
            user_id
        )

        if not applicant:

            await interaction.response.send_message(
                "❌ Заявитель больше не находится "
                "на сервере.",
                ephemeral=True
            )

            return

        settings = get_settings(
            guild.id
        )

        member_role_id = settings[
            "member_role_id"
        ]

        if not member_role_id:

            await interaction.response.send_message(
                "❌ Не назначена роль принятого игрока.\n"
                "Используйте `/ticket set-member-role`.",
                ephemeral=True
            )

            return

        member_role = guild.get_role(
            member_role_id
        )

        if not member_role:

            await interaction.response.send_message(
                "❌ Роль принятого игрока не найдена.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Выдача роли
        # ----------------------------------------------------

        try:

            await applicant.add_roles(
                member_role,
                reason=(
                    f"Принят в S A V A G E. "
                    f"Рекрутер: {interaction.user}"
                )
            )

        except discord.Forbidden:

            await interaction.response.send_message(
                "❌ Бот не может выдать эту роль.\n"
                "Проверьте иерархию ролей Discord.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # DM
        # ----------------------------------------------------

        try:

            embed = discord.Embed(
                title="S A V A G E • Вы приняты!",

                description=(
                    "🎉 Поздравляем!\n\n"
                    "Ваша заявка была одобрена.\n"
                    "Добро пожаловать в семью "
                    "**S A V A G E**!"
                ),

                color=discord.Color.green()
            )

            await applicant.send(
                embed=embed
            )

        except discord.Forbidden:
            pass

        # ----------------------------------------------------
        # Обновляем главное сообщение заявки
        # ----------------------------------------------------

        await update_application_message(
            interaction.message,
            "🟢 Принята",
            discord.Color.green(),
            "Принят"
        )

        # ----------------------------------------------------
        # Закрытие
        # ----------------------------------------------------

        closed_category = None

        if settings["closed_category_id"]:

            closed_category = guild.get_channel(
                settings["closed_category_id"]
            )

        await close_ticket(
            channel,
            applicant,
            closed_category
        )

        # ----------------------------------------------------
        # Финальное сообщение
        # ----------------------------------------------------

        embed = discord.Embed(
            title="✅ Заявка одобрена",

            description=(
                f"**Заявитель:** {applicant.mention}\n"
                f"**Рекрутер:** {interaction.user.mention}\n"
                f"**Роль:** {member_role.mention}"
            ),

            color=discord.Color.green()
        )

        await channel.send(
            embed=embed
        )

        await interaction.response.send_message(
            "✅ Заявитель принят, роль выдана.",
            ephemeral=True
        )

    # ========================================================
    #                       CALL
    # ========================================================

    async def start_call(
        self,
        interaction: discord.Interaction
    ):

        if not await self.check_staff(
            interaction
        ):
            return

        channel = interaction.channel

        if not isinstance(
            channel,
            discord.TextChannel
        ):
            return

        user_id = get_user_id_from_ticket(
            channel
        )

        if not user_id:

            await interaction.response.send_message(
                "❌ Не удалось определить заявителя.",
                ephemeral=True
            )

            return

        applicant = await find_member(
            interaction.guild,
            user_id
        )

        if not applicant:

            await interaction.response.send_message(
                "❌ Заявитель не найден.",
                ephemeral=True
            )

            return

        guild = interaction.guild
        me = guild.me

        voice_channels = [
            vc
            for vc in guild.voice_channels
            if me
            and vc.permissions_for(me).view_channel
        ]

        if not voice_channels:

            await interaction.response.send_message(
                "❌ Нет доступных голосовых каналов.",
                ephemeral=True
            )

            return

        await interaction.response.send_message(
            "🎙️ Выберите голосовой канал ожидания, "
            "куда заявитель должен зайти:",

            view=VoiceChannelView(
                self,
                channel
            ),

            ephemeral=True
        )

    async def call_to_voice(
        self,
        interaction: discord.Interaction,
        ticket_channel: discord.TextChannel,
        voice_channel: discord.VoiceChannel
    ):

        user_id = get_user_id_from_ticket(
            ticket_channel
        )

        if not user_id:

            await interaction.response.send_message(
                "❌ Не удалось определить заявителя.",
                ephemeral=True
            )

            return

        applicant = await find_member(
            interaction.guild,
            user_id
        )

        if not applicant:

            await interaction.response.send_message(
                "❌ Заявитель не найден.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # НИКУДА НЕ ПЕРЕМЕЩАЕМ ПОЛЬЗОВАТЕЛЯ
        # ----------------------------------------------------
        #
        # Бот только отправляет уведомление в заявку.
        # Заявитель самостоятельно заходит в выбранный
        # голосовой канал и ждёт рекрутера.
        # ----------------------------------------------------

        embed = discord.Embed(
            title="📞 Вызов на обзвон",

            description=(
                f"{applicant.mention}, вас готовы "
                f"принять на обзвон!\n\n"
                f"🎙️ **Зайдите в голосовой канал:** "
                f"{voice_channel.mention}\n\n"
                f"После подключения ожидайте рекрутера.\n"
                f"**Рекрутер:** "
                f"{interaction.user.mention}"
            ),

            color=discord.Color.blurple()
        )

        embed.set_footer(
            text="S A V A G E • Обзвон"
        )

        # ----------------------------------------------------
        # Отправляем уведомление в заявку
        # ----------------------------------------------------

        await ticket_channel.send(
            content=applicant.mention,
            embed=embed
        )

        # ----------------------------------------------------
        # Ответ рекрутеру
        # ----------------------------------------------------

        await interaction.response.edit_message(
            content=(
                f"✅ Уведомление отправлено "
                f"{applicant.mention}.\n\n"
                f"🎙️ Канал ожидания: "
                f"{voice_channel.mention}\n\n"
                f"Пользователь **не был перемещён**. "
                f"Он должен самостоятельно зайти в канал."
            ),
            view=None
        )

    # ========================================================
    #                    COMMAND GROUP
    # ========================================================

    ticket = app_commands.Group(
        name="ticket",
        description="Управление системой заявок S A V A G E"
    )

    # ========================================================
    #                    STAFF ADD
    # ========================================================

    @ticket.command(
        name="add-staff-role",
        description="Добавить роль рекрутов"
    )
    @app_commands.describe(
        role="Роль, которая сможет управлять заявками"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def add_staff_role_command(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            role_ids = get_staff_role_ids(
                interaction.guild.id
            )

            if role.id in role_ids:

                await interaction.followup.send(
                    f"ℹ️ Роль {role.mention} уже является "
                    "ролью рекрутов.",
                    ephemeral=True
                )

                return

            add_staff_role(
                interaction.guild.id,
                role.id
            )

            await interaction.followup.send(
                f"✅ Роль {role.mention} добавлена "
                "в роли рекрутов.",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "add-staff-role"
            )

    # ========================================================
    #                    STAFF REMOVE
    # ========================================================

    @ticket.command(
        name="remove-staff-role",
        description="Удалить роль рекрутов"
    )
    @app_commands.describe(
        role="Роль, которую нужно удалить"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def remove_staff_role_command(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            role_ids = get_staff_role_ids(
                interaction.guild.id
            )

            if role.id not in role_ids:

                await interaction.followup.send(
                    f"ℹ️ Роль {role.mention} "
                    "не является ролью рекрутов.",
                    ephemeral=True
                )

                return

            remove_staff_role(
                interaction.guild.id,
                role.id
            )

            await interaction.followup.send(
                f"✅ Роль {role.mention} удалена "
                "из ролей рекрутов.",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "remove-staff-role"
            )

    # ========================================================
    #                    STAFF LIST
    # ========================================================

    @ticket.command(
        name="staff-roles",
        description="Показать роли рекрутов"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def staff_roles_command(
        self,
        interaction: discord.Interaction
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            role_ids = get_staff_role_ids(
                interaction.guild.id
            )

            if not role_ids:

                text = "❌ Роли рекрутов не установлены."

            else:

                lines = []

                for role_id in role_ids:

                    role = interaction.guild.get_role(
                        role_id
                    )

                    if role:
                        lines.append(
                            f"• {role.mention}"
                        )

                    else:
                        lines.append(
                            f"• `роль {role_id}` — не найдена"
                        )

                text = "\n".join(
                    lines
                )

            embed = discord.Embed(
                title="👮 Роли рекрутов",
                description=text,
                color=discord.Color.blurple()
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "staff-roles"
            )

    # ========================================================
    #                  MEMBER ROLE
    # ========================================================

    @ticket.command(
        name="set-member-role",
        description="Назначить роль принятого игрока"
    )
    @app_commands.describe(
        role="Роль, выдаваемая после принятия"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def set_member_role(
        self,
        interaction: discord.Interaction,
        role: discord.Role
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            update_setting(
                interaction.guild.id,
                "member_role_id",
                role.id
            )

            await interaction.followup.send(
                f"✅ Роль принятого игрока: "
                f"{role.mention}",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "set-member-role"
            )

    # ========================================================
    #                  OPEN CATEGORY
    # ========================================================

    @ticket.command(
        name="set-open-category",
        description="Назначить категорию новых заявок"
    )
    @app_commands.describe(
        category="Категория для новых заявок"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def set_open_category(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            update_setting(
                interaction.guild.id,
                "open_category_id",
                category.id
            )

            await interaction.followup.send(
                f"✅ Категория новых заявок: "
                f"{category.mention}",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "set-open-category"
            )

    # ========================================================
    #                  CLOSED CATEGORY
    # ========================================================

    @ticket.command(
        name="set-closed-category",
        description="Назначить категорию закрытых заявок"
    )
    @app_commands.describe(
        category="Категория закрытых заявок"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def set_closed_category(
        self,
        interaction: discord.Interaction,
        category: discord.CategoryChannel
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            update_setting(
                interaction.guild.id,
                "closed_category_id",
                category.id
            )

            await interaction.followup.send(
                f"✅ Категория закрытых заявок: "
                f"{category.mention}",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "set-closed-category"
            )

    # ========================================================
    #                    PANEL CHANNEL
    # ========================================================

    @ticket.command(
        name="set-panel-channel",
        description="Назначить единый канал для подачи заявок"
    )
    @app_commands.describe(
        channel="Канал, где будет находиться панель"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def set_panel_channel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            update_setting(
                interaction.guild.id,
                "panel_channel_id",
                channel.id
            )

            await interaction.followup.send(
                f"✅ Канал заявок установлен: "
                f"{channel.mention}\n\n"
                "Теперь кнопка подачи заявки будет "
                "работать только в этом канале.",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "set-panel-channel"
            )

    # ========================================================
    #                       SETTINGS
    # ========================================================

    @ticket.command(
        name="settings",
        description="Показать настройки системы заявок"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def ticket_settings(
        self,
        interaction: discord.Interaction
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            settings = get_settings(
                interaction.guild.id
            )

            # -------------------------------------------------
            # Роли
            # -------------------------------------------------

            staff_role_ids = get_staff_role_ids(
                interaction.guild.id
            )

            if staff_role_ids:

                staff_text = []

                for role_id in staff_role_ids:

                    role = interaction.guild.get_role(
                        role_id
                    )

                    if role:
                        staff_text.append(
                            role.mention
                        )
                    else:
                        staff_text.append(
                            f"`{role_id}` — не найдена"
                        )

                staff_value = "\n".join(
                    staff_text
                )

            else:

                staff_value = "❌ Не установлено"

            member_role_id = settings[
                "member_role_id"
            ]

            if member_role_id:

                role = interaction.guild.get_role(
                    member_role_id
                )

                member_value = (
                    role.mention
                    if role
                    else "❌ Роль не найдена"
                )

            else:

                member_value = "❌ Не установлено"

            # -------------------------------------------------
            # Каналы
            # -------------------------------------------------

            def channel_text(channel_id):

                if not channel_id:
                    return "❌ Не установлено"

                channel = interaction.guild.get_channel(
                    channel_id
                )

                if channel:
                    return channel.mention

                return "❌ Канал не найден"

            embed = discord.Embed(
                title="S A V A G E • НАСТРОЙКИ ЗАЯВОК",

                description=(
                    "Текущая конфигурация системы."
                ),

                color=discord.Color.blurple()
            )

            embed.add_field(
                name="👮 Роли рекрутов",
                value=staff_value,
                inline=False
            )

            embed.add_field(
                name="♟ Роль принятого игрока",
                value=member_value,
                inline=False
            )

            embed.add_field(
                name="📂 Новые заявки",
                value=channel_text(
                    settings["open_category_id"]
                ),
                inline=False
            )

            embed.add_field(
                name="🗄️ Закрытые заявки",
                value=channel_text(
                    settings["closed_category_id"]
                ),
                inline=False
            )

            embed.add_field(
                name="📋 Канал подачи заявки",
                value=channel_text(
                    settings["panel_channel_id"]
                ),
                inline=False
            )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "ticket settings"
            )

    # ========================================================
    #                  QUESTION ADD
    # ========================================================

    @ticket.command(
        name="question-add",
        description="Добавить или заменить вопрос"
    )
    @app_commands.describe(
        number="Номер вопроса от 1 до 5",
        question="Текст вопроса"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def question_add(
        self,
        interaction: discord.Interaction,
        number: app_commands.Range[int, 1, 5],
        question: str
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            question = question.strip()

            if not question:

                await interaction.followup.send(
                    "❌ Вопрос не может быть пустым.",
                    ephemeral=True
                )

                return

            if len(question) > 100:

                await interaction.followup.send(
                    "❌ Вопрос слишком длинный. "
                    "Максимум 100 символов.",
                    ephemeral=True
                )

                return

            add_question(
                interaction.guild.id,
                number,
                question
            )

            await interaction.followup.send(
                f"✅ Вопрос №{number} установлен:\n"
                f"**{question}**",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "question-add"
            )

    # ========================================================
    #                  QUESTION REMOVE
    # ========================================================

    @ticket.command(
        name="question-remove",
        description="Удалить вопрос"
    )
    @app_commands.describe(
        number="Номер вопроса"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def question_remove(
        self,
        interaction: discord.Interaction,
        number: app_commands.Range[int, 1, 5]
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            question = get_question(
                interaction.guild.id,
                number
            )

            if not question:

                await interaction.followup.send(
                    f"❌ Вопрос №{number} не найден.",
                    ephemeral=True
                )

                return

            delete_question(
                interaction.guild.id,
                number
            )

            await interaction.followup.send(
                f"✅ Вопрос №{number} удалён.",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "question-remove"
            )

    # ========================================================
    #                  QUESTION EDIT
    # ========================================================

    @ticket.command(
        name="question-edit",
        description="Изменить существующий вопрос"
    )
    @app_commands.describe(
        number="Номер вопроса",
        question="Новый текст вопроса"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def question_edit(
        self,
        interaction: discord.Interaction,
        number: app_commands.Range[int, 1, 5],
        question: str
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            old_question = get_question(
                interaction.guild.id,
                number
            )

            if not old_question:

                await interaction.followup.send(
                    f"❌ Вопрос №{number} "
                    "не существует.",
                    ephemeral=True
                )

                return

            question = question.strip()

            if not question:

                await interaction.followup.send(
                    "❌ Вопрос не может быть пустым.",
                    ephemeral=True
                )

                return

            add_question(
                interaction.guild.id,
                number,
                question
            )

            await interaction.followup.send(
                f"✅ Вопрос №{number} изменён.\n\n"
                f"**Было:** {old_question}\n"
                f"**Стало:** {question}",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "question-edit"
            )

    # ========================================================
    #                     QUESTIONS
    # ========================================================

    @ticket.command(
        name="questions",
        description="Показать вопросы заявки"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def questions(
        self,
        interaction: discord.Interaction
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            questions = get_questions(
                interaction.guild.id
            )

            embed = discord.Embed(
                title="S A V A G E • ВОПРОСЫ ЗАЯВКИ",
                color=discord.Color.blurple()
            )

            if not questions:

                embed.description = (
                    "❌ Вопросов нет."
                )

            else:

                for row in questions:

                    embed.add_field(
                        name=(
                            f"Вопрос №"
                            f"{row['question_number']}"
                        ),

                        value=row["question"],

                        inline=False
                    )

            await interaction.followup.send(
                embed=embed,
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "questions"
            )

    # ========================================================
    #                     SEND PANEL
    # ========================================================

    @ticket.command(
        name="send-panel",
        description="Опубликовать панель подачи заявки"
    )
    @app_commands.default_permissions(
        administrator=True
    )
    async def send_panel(
        self,
        interaction: discord.Interaction
    ):

        try:

            await interaction.response.defer(
                ephemeral=True
            )

            settings = get_settings(
                interaction.guild.id
            )

            panel_channel_id = settings[
                "panel_channel_id"
            ]

            if not panel_channel_id:

                await interaction.followup.send(
                    "❌ Сначала установите канал:\n"
                    "`/ticket set-panel-channel`",
                    ephemeral=True
                )

                return

            channel = interaction.guild.get_channel(
                panel_channel_id
            )

            if not isinstance(
                channel,
                discord.TextChannel
            ):

                await interaction.followup.send(
                    "❌ Канал панели не найден.",
                    ephemeral=True
                )

                return

            embed = discord.Embed(
                title="📋 Вступление в S A V A G E",

                description=(
                    "Хочешь вступить в нашу семью?\n\n"
                    "Нажми кнопку **«Подать заявку»** "
                    "ниже и заполни небольшую анкету.\n\n"
                    "После отправки с тобой свяжется "
                    "рекрутер."
                ),

                color=discord.Color.blurple()
            )

            embed.set_footer(
                text="S A V A G E • Система заявок"
            )

            await channel.send(
                embed=embed,
                view=TicketPanelView(self)
            )

            await interaction.followup.send(
                f"✅ Панель опубликована в "
                f"{channel.mention}.",
                ephemeral=True
            )

        except Exception as error:

            await self.safe_error(
                interaction,
                error,
                "send-panel"
            )


# ============================================================
#                         SETUP
# ============================================================

async def setup(bot):

    await bot.add_cog(
        Tickets(bot)
    )