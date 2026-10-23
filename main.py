import os, traceback
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from utils.database import init_database
from utils.config_db import init_config_database

load_dotenv()
TOKEN=os.getenv('DISCORD_TOKEN')
if not TOKEN: raise RuntimeError('DISCORD_TOKEN не найден в .env')
GUILD_ID=int(os.getenv('GUILD_ID','0'))
GUILD=discord.Object(id=GUILD_ID) if GUILD_ID else None
intents=discord.Intents.default(); intents.guilds=True; intents.members=True; intents.message_content=True

class SavageBot(commands.Bot):
    def __init__(self): super().__init__(command_prefix='!',intents=intents,help_command=None)
    async def setup_hook(self):
        init_database(); init_config_database()
        extensions=['cogs.general','cogs.tickets','cogs.warns','cogs.admin_panel','cogs.contracts','cogs.reactions']
        for ext in extensions:
            try:
                await self.load_extension(ext); print(f'✅ {ext} загружен')
            except Exception as e:
                print(f'❌ Ошибка {ext}: {type(e).__name__}: {e}'); traceback.print_exc()
        if GUILD:
            try:
                # Copy current commands to this server and sync them first.
                self.tree.copy_global_to(guild=GUILD)
                synced=await self.tree.sync(guild=GUILD)
                print(f'✅ Синхронизировано команд сервера: {len(synced)}')

                # Remove stale globally registered commands (including old /reaction commands).
                self.tree.clear_commands(guild=None)
                await self.tree.sync()
                print('✅ Устаревшие глобальные команды очищены')
            except Exception as e:
                print(f'❌ Ошибка синхронизации: {e}')
        else:
            # Without GUILD_ID, sync globally so removed commands disappear there too.
            try:
                synced=await self.tree.sync()
                print(f'✅ Глобально синхронизировано команд: {len(synced)}')
            except Exception as e:
                print(f'❌ Ошибка глобальной синхронизации: {e}')
    async def on_ready(self):
        print(f'🤖 S A V A G E online: {self.user} ({self.user.id})')
        for name in ('contracts','reactions'):
            cog=self.get_cog(name.capitalize())
            if cog and hasattr(cog,'restore_views'):
                await cog.restore_views()

bot=SavageBot()

@bot.tree.error
async def on_app_command_error(interaction,error):
    print(f'[SLASH ERROR] {type(error).__name__}: {error}')
    try:
        msg='❌ Произошла ошибка при выполнении команды.'
        if isinstance(error,app_commands.CommandOnCooldown): msg=f'⏳ Подождите {error.retry_after:.1f} сек.'
        if interaction.response.is_done(): await interaction.followup.send(msg,ephemeral=True)
        else: await interaction.response.send_message(msg,ephemeral=True)
    except Exception: pass

bot.run(TOKEN)
