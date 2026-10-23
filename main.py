"""SAVAGE BOT entry point — Python 3.11 / discord.py 2.x."""
import logging
import os
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from utils.config_db import init_config_database
from utils.database import init_database

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("savage")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не найден. Добавь его в переменные окружения Bothost или в .env.")

try:
    GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
except ValueError as exc:
    raise RuntimeError("GUILD_ID должен быть числом Discord-сервера.") from exc
TEST_GUILD = discord.Object(id=GUILD_ID) if GUILD_ID else None

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True
intents.voice_states = True

EXTENSIONS = (
    "cogs.general",
    "cogs.tickets",
    "cogs.warns",
    "cogs.admin_panel",
    "cogs.contracts",
    "cogs.reactions",
)

class SavageBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self._views_restored = False

    async def setup_hook(self):
        init_database()
        init_config_database()
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                log.info("Loaded extension %s", extension)
            except Exception:
                log.exception("Failed loading extension %s", extension)

        try:
            if TEST_GUILD:
                self.tree.copy_global_to(guild=TEST_GUILD)
                synced = await self.tree.sync(guild=TEST_GUILD)
                log.info("Synced %d guild slash commands to %s", len(synced), GUILD_ID)
            else:
                synced = await self.tree.sync()
                log.info("Synced %d global slash commands", len(synced))
        except Exception:
            log.exception("Slash-command sync failed")

    async def on_ready(self):
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "?")
        if self._views_restored:
            return
        self._views_restored = True
        for cog_name in ("Contracts", "Reactions", "Tickets"):
            cog = self.get_cog(cog_name)
            restore = getattr(cog, "restore_views", None) if cog else None
            if restore:
                try:
                    await restore()
                except Exception:
                    log.exception("Could not restore persistent views for %s", cog_name)

bot = SavageBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    log.error("Application command error: %s", original, exc_info=original)
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Подожди {error.retry_after:.1f} сек."
    elif isinstance(error, app_commands.MissingPermissions):
        message = "❌ Недостаточно прав для этой команды."
    else:
        message = "❌ Ошибка выполнения. Подробности записаны в лог."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass

bot.run(TOKEN)
