import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from cogs import get_guild_dir, get_guild_json
import discord
import torchaudio as ta
from discord import app_commands
from discord.ext import commands
import json

# -- Variabili Costanti --
CURRDIR = Path(__file__).parent.absolute()


class Soundboards(commands.Cog) :
    '''
    Docstring for Soundboards

    Questo Cog è responsabile di riprodurre dei suoni
    da una lista di souoni (json) contenete il souno : file
    '''
    def __init__(self, bot : commands.Bot) :
        self.bot = bot

    async def oepn_sound_index(self, interaction : discord.Interaction) :
        sound_index = await get_guild_json(interaction.guild_id, "soundboard")
        with open(sound_index, "r", encoding="utf-8") as f :
            return json.load(f)

    async def vc_connect(self, interaction : discord.Interaction) :
        if not interaction.user.voice:
            await interaction.response.send_message(
                "❌ You must be in a voice channel!",
                ephemeral=True,
            )
            return -1

        target_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        try:
            if vc is None:
                vc = await target_channel.connect()
                print(f"Connected to: {target_channel.name}")
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
                print("CONNECTION ERROR")
                return vc
        except Exception as e:
            print(f"Voice connection error: {e}")
            await interaction.followup.send(
                "❌ Cannot connect to voice channel."
            )
            return -1

    async def sound_autocomplete(self,
                                 interaction : discord.Interaction,
                                 current : str) -> list[app_commands.Choice[str]]:
        sounds = await self.oepn_sound_index(interaction)

        return [app_commands.Choice(name=name, value=filename)
            for name, filename in sounds.items()
            if current.lower() in name.lower()][:25]


    @app_commands.command(name="soundboard", description="Riproduci un suono da una lista di suoni")
    @app_commands.describe(soundfile="Il souno che desideri venga riprodotto")
    @app_commands.autocomplete(soundfile=sound_autocomplete)
    async def connect(self,interaction : discord.Interaction,soundfile : str) :
        sound_dir = await get_guild_dir(interaction.guild_id, "soundboards")
        soundfile = sound_dir / soundfile

        # Connettiti Alla vocale
        await self.vc_connect(interaction)
        vc = interaction.guild.voice_client
            # Riproduci il suono..
        if vc != -1 :
            try :
                if vc.is_playing() :
                    vc.stop()
            except Exception as e :
                pass

            try :
                source = discord.FFmpegPCMAudio(soundfile)
                vc.play(source)
                await interaction.response.send_message(f"🔊|Suono Riprodotto")
            except Exception as e :
                print(f"Eccezzione : {e}")




async def setup(bot: commands.Bot) -> None:
    """Setup function to load the cog."""
    await bot.add_cog(Soundboards(bot))

