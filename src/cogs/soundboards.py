import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs import get_guild_dir, get_guild_json, load_json, resolve_in_dir

log = logging.getLogger(__name__)

# Cartella (dentro data/<server-id>/) con index.json e i file audio, come descritto nel README.
SOUNDBOARD_FOLDER = "soundboard"


class Soundboards(commands.Cog) :
    '''
    Docstring for Soundboards

    Questo Cog è responsabile di riprodurre dei suoni
    da una lista di souoni (json) contenete il souno : file
    '''
    def __init__(self, bot : commands.Bot) :
        self.bot = bot

    async def open_sound_index(self, guild_id : int) -> dict :
        sound_index = await get_guild_json(guild_id, SOUNDBOARD_FOLDER)
        return load_json(sound_index)

    async def vc_connect(self, interaction : discord.Interaction) -> discord.VoiceClient | None :
        """
        Connette (o sposta) il bot nel canale vocale dell'utente.
        Restituisce il voice client oppure None se non è possibile (risponde già all'utente).
        L'interazione deve avere già fatto defer(): l'errore sostituisce il messaggio "sta pensando".
        """
        target_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        try:
            if vc is None:
                vc = await target_channel.connect()
                log.info("Connected to: %s", target_channel.name)
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
            return vc
        except Exception as e:
            log.error("Voice connection error: %s", e)
            # Dopo un defer() pubblico Discord ignora `ephemeral` sul primo messaggio: l'errore è pubblico
            await interaction.followup.send("❌ Non riesco a connettermi al canale vocale.")
            return None

    async def sound_autocomplete(self,
                                 interaction : discord.Interaction,
                                 current : str) -> list[app_commands.Choice[str]]:
        try:
            sounds = await self.open_sound_index(interaction.guild_id)
        except Exception as e:
            log.warning("Autocomplete soundboard fallito: %s", e)
            return []

        return [app_commands.Choice(name=name[:100], value=filename[:100])
            for name, filename in sounds.items()
            if current.lower() in name.lower()][:25]


    @app_commands.command(name="soundboard", description="Riproduce un suono dalla lista dei suoni del server")
    @app_commands.describe(soundfile="Il suono da riprodurre")
    @app_commands.autocomplete(soundfile=sound_autocomplete)
    async def soundboard(self, interaction : discord.Interaction, soundfile : str) :
        if not interaction.user.voice or interaction.user.voice.channel is None :
            return await interaction.response.send_message(
                "❌ Devi essere in un canale vocale!", ephemeral=True
            )

        # `soundfile` arriva dall'utente: deve restare dentro la cartella del soundboard.
        # Si controlla PRIMA del defer: dopo un defer() pubblico Discord ignora `ephemeral`,
        # mentre così l'errore resta visibile solo a chi ha lanciato il comando.
        sound_dir = await get_guild_dir(interaction.guild_id, SOUNDBOARD_FOLDER)
        sound_path = resolve_in_dir(sound_dir, soundfile)
        if sound_path is None or not sound_path.is_file() :
            return await interaction.response.send_message("❌ Suono non trovato.", ephemeral=True)

        # La connessione vocale può superare i 3 secondi concessi per rispondere
        await interaction.response.defer()

        vc = await self.vc_connect(interaction)
        if vc is None :
            return

        try :
            if vc.is_playing() :
                vc.stop()
            vc.play(discord.FFmpegPCMAudio(str(sound_path)))
        except Exception as e :
            log.error("Errore di riproduzione soundboard: %s", e)
            return await interaction.followup.send(
                "❌ Impossibile riprodurre il suono (FFmpeg installato?)."
            )

        await interaction.followup.send("🔊 Suono riprodotto")


async def setup(bot: commands.Bot) -> None:
    """Setup function to load the cog."""
    await bot.add_cog(Soundboards(bot))
