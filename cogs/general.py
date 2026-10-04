import discord
from discord import app_commands
from discord.ext import commands


class General(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Проверить, работает ли S A V A G E BOT"
    )
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            "🟢 **S A V A G E BOT работает!**",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(General(bot))
