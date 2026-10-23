"""Точка запуска SAVAGE BOT. Совместимо с Python 3.11 и discord.py 2.x."""
import os
import traceback

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from utils.config_db import init_config_database
from utils.database import init_database

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
if not TOKEN or TOKEN == "PUT_YOUR_BOT_TOKEN_HERE":
    raise RuntimeError("DISCORD_TOKEN не задан. Добавьте токен в переменные окружения Bothost или локальный .env.")

try:
    GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
except ValueError:
    GUILD_ID = 0
GUILD = discord.Object(id=GUILD_ID) if GUILD_ID else None

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

class SavageBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        init_database()
        init_config_database()
        extensions = (
            "cogs.general",
            "cogs.tickets",
            "cogs.warns",
            "cogs.admin_panel",
            "cogs.contracts",
            "cogs.reactions",
        )
        for extension in extensions:
            try:
                await self.load_extension(extension)
                print(f"[COG OK] {extension}")
            except Exception:
                print(f"[COG ERROR] {extension}")
                traceback.print_exc()

        try:
            if GUILD:
                # Синхронизация в конкретный сервер — команды появляются быстрее.
                self.tree.copy_global_to(guild=GUILD)
                synced = await self.tree.sync(guild=GUILD)
                print(f"[COMMANDS] Синхронизировано для сервера {GUILD_ID}: {len(synced)}")
            else:
                synced = await self.tree.sync()
                print(f"[COMMANDS] Глобально синхронизировано: {len(synced)}")
        except Exception:
            print("[COMMAND SYNC ERROR]")
            traceback.print_exc()

    async def on_ready(self):
        print(f"[READY] SAVAGE BOT online as {self.user} ({self.user.id})")
        for cog_name in ("Contracts", "Reactions"):
            cog = self.get_cog(cog_name)
            restore = getattr(cog, "restore_views", None) if cog else None
            if restore:
                try:
                    await restore()
                except Exception:
                    print(f"[RESTORE ERROR] {cog_name}")
                    traceback.print_exc()

bot = SavageBot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = getattr(error, "original", error)
    print(f"[SLASH ERROR] {type(original).__name__}: {original}")
    message = "❌ Ошибка при выполнении команды. Подробности сохранены в логах бота."
    if isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Подождите {error.retry_after:.1f} сек."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass

bot.run(TOKEN)
