import logging

import discord
from discord import app_commands
from discord.ext import commands

import storage

log = logging.getLogger(__name__)


class Soundboards(commands.Cog) :
    '''
    Docstring for Soundboards

    Questo Cog è responsabile di riprodurre dei suoni dalla soundboard del server
    (più quelle globali). L'elenco sta nel database SQLite (`bot.db`) e si gestisce dalla dashboard.
    '''
    def __init__(self, bot : commands.Bot) :
        self.bot = bot

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
            sounds = await storage.list_sounds_for_guild(self.bot.db, interaction.guild_id)
        except Exception as e:
            log.warning("Autocomplete soundboard fallito: %s", e)
            return []

        # Il valore è l'id nel database (non il nome del file): non si può usare per uscire dalla cartella.
        # I suoni globali, validi in tutti i server, hanno un 🌐 davanti.
        return [app_commands.Choice(name=("🌐 " + row["name"] if row["guild_id"] == storage.GLOBAL else row["name"])[:100],
                                    value=str(row["id"]))
            for row in sounds
            if current.lower() in row["name"].lower()][:25]


    @app_commands.command(name="soundboard", description="Riproduce un suono dalla lista dei suoni del server")
    @app_commands.describe(soundfile="Il suono da riprodurre")
    @app_commands.autocomplete(soundfile=sound_autocomplete)
    async def soundboard(self, interaction : discord.Interaction, soundfile : str) :
        if not interaction.user.voice or interaction.user.voice.channel is None :
            return await interaction.response.send_message(
                "❌ Devi essere in un canale vocale!", ephemeral=True
            )

        # `soundfile` arriva dall'utente: deve essere l'id di un suono di QUESTO server (o globale)
        # il cui file sta davvero nella cartella dei suoni. Si controlla PRIMA del defer: dopo un defer()
        # pubblico Discord ignora `ephemeral`, mentre così l'errore resta visibile solo a chi ha lanciato il comando.
        resolved = await storage.resolve_sound(self.bot.db, interaction.guild_id, soundfile)
        if resolved is None :
            return await interaction.response.send_message("❌ Suono non trovato.", ephemeral=True)
        _, sound_path = resolved

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
