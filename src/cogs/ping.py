import discord
from discord.ext import commands
from discord import app_commands

class Ping(commands.Cog) :
    def __init__(self, bot ):
        self.bot = bot
    
    @commands.Cog.listener()
    async def on_ready(self) :
        print("Ping Ready!")
    
    @app_commands.command(name="ping")
    async def ping(self, interaction : discord.Interaction) :
        await interaction.response.send_message(f"pong", ephemeral=True)

async def setup(bot) :
    await bot.add_cog(Ping(bot))
