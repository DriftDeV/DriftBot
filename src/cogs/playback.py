"""
Playback cog — controlli globali: /skip, /pause, /resume, /stop, /setvolume.

Agiscono sul voice client del server, quindi valgono per qualunque audio lungo:
/play (YouTube & co.), /ai-cover e /ace-step. Ogni cog che riproduce passa la sua
sorgente da `with_volume()`, così il volume è uno solo per server.
"""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

MAX_VOLUME = 100          # come nella versione Java


def _cog(bot, name: str):
    return getattr(bot, "get_cog", lambda _: None)(name)


def volume_of(bot, guild_id: int) -> int:
    playback = _cog(bot, "Playback")
    return playback.volumes.get(guild_id, MAX_VOLUME) if playback else MAX_VOLUME


def with_volume(bot, guild_id: int, source: discord.AudioSource) -> discord.PCMVolumeTransformer:
    """Avvolge la sorgente audio con il volume corrente del server (regolabile live da /setvolume)."""
    return discord.PCMVolumeTransformer(source, volume=volume_of(bot, guild_id) / 100)


class Playback(commands.Cog):
    """Comandi di riproduzione validi per tutti i cog che suonano nella vocale."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.volumes: dict[int, int] = {}

    async def _active_vc(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """Il voice client se sta suonando (o è in pausa) e l'utente è nel canale giusto."""
        vc = interaction.guild.voice_client
        if vc is None or not (vc.is_playing() or vc.is_paused()):
            await interaction.response.send_message("❌ Non sto riproducendo nulla.", ephemeral=True)
            return None
        user_voice = interaction.user.voice
        if user_voice is None or user_voice.channel != vc.channel:
            await interaction.response.send_message("❌ Devi essere nel mio stesso canale vocale!", ephemeral=True)
            return None
        return vc

    @app_commands.command(name="skip", description="Salta l'audio in riproduzione (musica, AI cover, ACE-Step)")
    @app_commands.guild_only()
    async def skip(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        music, cover = _cog(self.bot, "Music"), _cog(self.bot, "AICover")
        upcoming = music.upcoming(interaction.guild) if music else None
        more_covers = cover is not None and not cover.queue.empty()
        vc.stop()       # la callback `after` di chi stava suonando passa alla prossima richiesta, se c'è
        if upcoming is not None:
            text = f"⏭️ Ora in riproduzione: {upcoming}"
        elif more_covers:
            text = "⏭️ Saltata! Passo alla prossima richiesta..."
        else:
            text = "⏭️ Saltata. Non c'è altro in coda."
        await interaction.response.send_message(text)

    @app_commands.command(name="pause", description="Mette in pausa la riproduzione")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        if vc.is_paused():
            return await interaction.response.send_message("❌ È già in pausa.", ephemeral=True)
        vc.pause()
        await interaction.response.send_message("⏸️ In pausa")

    @app_commands.command(name="resume", description="Riprende la riproduzione")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        if not vc.is_paused():
            return await interaction.response.send_message("❌ Non è in pausa.", ephemeral=True)
        vc.resume()
        await interaction.response.send_message("▶️ Riprendo")

    @app_commands.command(name="stop", description="Ferma tutto, svuota le code ed esce dalla vocale")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        guild_id = interaction.guild.id
        music, cover = _cog(self.bot, "Music"), _cog(self.bot, "AICover")
        if music:
            music.clear(guild_id)           # prima, così la callback `after` non riparte
        if cover:
            cover.clear_queue(guild_id)
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Fermato")

    @app_commands.command(name="setvolume", description="Imposta il volume del bot")
    @app_commands.describe(volume=f"Il valore del volume (0-{MAX_VOLUME})")
    @app_commands.guild_only()
    async def setvolume(
        self, interaction: discord.Interaction, volume: app_commands.Range[int, 0, MAX_VOLUME]
    ) -> None:
        vc = interaction.guild.voice_client
        if vc is not None and (vc.is_playing() or vc.is_paused()):
            if await self._active_vc(interaction) is None:
                return
            if hasattr(vc.source, "volume"):
                vc.source.volume = volume / 100      # effetto immediato sulla traccia in corso
        self.volumes[interaction.guild.id] = volume   # e vale per le prossime (musica, cover, ACE-Step)
        await interaction.response.send_message(f"🔊 Volume impostato al valore: {volume}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Playback(bot))
