"""
Music cog — riproduzione di musica da URL o ricerca testuale (YouTube & co.).

Porting in Python del vecchio DiscordMusicBot (Java / JDA / LavaPlayer):
l'audio viene risolto con yt-dlp e riprodotto in streaming con FFmpeg.

Comandi slash: /play, /pause, /resume, /stop, /setvolume.
Il comando /skip è definito in ai_cover_cog.py, che delega a questo cog
tramite `Music.skip_if_active()` quando c'è musica in riproduzione.
"""

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)

MAX_VOLUME = 100          # come nella versione Java
IDLE_TIMEOUT = 120        # secondi di inattività prima di lasciare la vocale
STREAM_URL_TTL = 600      # gli URL di streaming scadono: li risolviamo di nuovo se più vecchi

YDL_OPTS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "playlist_items": "1",     # come in Java: di una playlist si accoda solo la prima traccia
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
}

FFMPEG_OPTS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class NoMatches(Exception):
    """Nessun risultato per l'URL o la ricerca richiesta."""


def is_url(text: str) -> bool:
    """True se `text` è un URL http(s). I percorsi locali (file://) sono rifiutati di proposito."""
    parsed = urlparse(text.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@dataclass
class Track:
    title: str
    author: str
    webpage_url: str
    stream_url: str
    resolved_at: float = field(default_factory=time.monotonic)

    def is_stale(self) -> bool:
        return time.monotonic() - self.resolved_at > STREAM_URL_TTL


def extract_track(query: str) -> Track:
    """Risolve un URL o una ricerca testuale in una Track. Bloccante: eseguire in un thread."""
    target = query.strip() if is_url(query) else f"ytsearch1:{query.strip()}"
    with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
        info = ydl.extract_info(target, download=False)

    if info and info.get("entries") is not None:
        entries = [entry for entry in info["entries"] if entry]
        if not entries:
            raise NoMatches(query)
        info = entries[0]
    if not info or not info.get("url"):
        raise NoMatches(query)

    return Track(
        title=info.get("title") or "Sconosciuto",
        author=info.get("uploader") or info.get("channel") or "Sconosciuto",
        webpage_url=info.get("webpage_url") or info.get("original_url") or target,
        stream_url=info["url"],
    )


class GuildPlayer:
    """Stato della riproduzione di un singolo server."""

    def __init__(self) -> None:
        self.queue: deque[Track] = deque()
        self.current: Optional[Track] = None
        self.volume: int = MAX_VOLUME
        self.source: Optional[discord.PCMVolumeTransformer] = None
        self.lock = asyncio.Lock()
        self.idle_task: Optional[asyncio.Task] = None


class Music(commands.Cog):
    """
    Riproduce musica da URL o nome, con coda per server.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.players: dict[int, GuildPlayer] = {}

    # ------------------------------------------------------------------ utilità

    def _get_player(self, guild_id: int) -> GuildPlayer:
        return self.players.setdefault(guild_id, GuildPlayer())

    def _drop_player(self, guild_id: int) -> None:
        player = self.players.pop(guild_id, None)
        if player and player.idle_task:
            player.idle_task.cancel()

    @staticmethod
    def _music_active(vc: Optional[discord.VoiceClient], player: GuildPlayer) -> bool:
        """
        True se il voice client sta davvero suonando (o è in pausa su) una traccia di questo cog.
        Altri cog (AI cover, TTS, soundboard) possono prendere il voice client a metà coda:
        in quel caso `player.current` resta valorizzato ma `vc.source` non è più il nostro.
        """
        return vc is not None and player.current is not None and vc.source is player.source

    def _cancel_idle(self, player: GuildPlayer) -> None:
        if player.idle_task:
            player.idle_task.cancel()
            player.idle_task = None

    def _schedule_idle(self, guild: discord.Guild, player: GuildPlayer) -> None:
        self._cancel_idle(player)
        player.idle_task = self.bot.loop.create_task(self._idle_disconnect(guild, player))

    async def _idle_disconnect(self, guild: discord.Guild, player: GuildPlayer) -> None:
        try:
            await asyncio.sleep(IDLE_TIMEOUT)
        except asyncio.CancelledError:
            return
        vc = guild.voice_client
        if self.players.get(guild.id) is player and player.current is None and not player.queue:
            self._drop_player(guild.id)
            if vc and vc.is_connected() and not vc.is_playing():
                await vc.disconnect()

    async def _active_vc(self, interaction: discord.Interaction) -> Optional[discord.VoiceClient]:
        """Restituisce il voice client se c'è musica attiva e l'utente è nel canale giusto."""
        vc = interaction.guild.voice_client
        if vc is None or interaction.guild.id not in self.players:
            await interaction.response.send_message(
                "❌ Non sto riproducendo musica.", ephemeral=True
            )
            return None
        user_voice = interaction.user.voice
        if user_voice is None or user_voice.channel != vc.channel:
            await interaction.response.send_message(
                "❌ Devi essere nel mio stesso canale vocale!", ephemeral=True
            )
            return None
        return vc

    # --------------------------------------------------------------- riproduzione

    def _after(self, guild: discord.Guild, error: Optional[Exception]) -> None:
        """Callback di discord.py: gira nel thread audio, rientra nel loop per passare alla prossima."""
        if error:
            log.error("Errore di riproduzione: %s", error)
        asyncio.run_coroutine_threadsafe(self._play_next(guild), self.bot.loop)

    async def _play_next(self, guild: discord.Guild) -> None:
        player = self.players.get(guild.id)
        if player is None:
            return  # /stop o disconnessione: stato già ripulito

        async with player.lock:
            vc = guild.voice_client
            if vc is None or not vc.is_connected():
                self._drop_player(guild.id)
                return
            if vc.is_playing() or vc.is_paused():
                return  # qualcun altro ha già avviato la prossima traccia

            while player.queue:
                track = player.queue.popleft()
                try:
                    if track.is_stale():
                        fresh = await asyncio.to_thread(extract_track, track.webpage_url)
                        track.stream_url, track.resolved_at = fresh.stream_url, fresh.resolved_at
                    source = discord.PCMVolumeTransformer(
                        discord.FFmpegPCMAudio(track.stream_url, **FFMPEG_OPTS),
                        volume=player.volume / 100,
                    )
                    vc.play(source, after=lambda err, g=guild: self._after(g, err))
                except Exception:
                    log.exception("Impossibile riprodurre %r, passo alla prossima", track.title)
                    continue
                player.current, player.source = track, source
                return

            player.current = player.source = None
            self._schedule_idle(guild, player)

    # ------------------------------------------------------------------- comandi

    @app_commands.command(name="play", description="Riproduce una canzone da URL o nome")
    @app_commands.describe(url="L'URL o il nome della canzone")
    @app_commands.guild_only()
    async def play(self, interaction: discord.Interaction, url: str) -> None:
        user_voice = interaction.user.voice
        if user_voice is None or user_voice.channel is None:
            return await interaction.response.send_message(
                "❌ Devi essere in un canale vocale!", ephemeral=True
            )

        guild = interaction.guild
        player = self._get_player(guild.id)
        vc = guild.voice_client

        if vc is not None:
            music_active = self._music_active(vc, player)
            if not music_active and (vc.is_playing() or vc.is_paused()):
                return await interaction.response.send_message(
                    "❌ Sto già riproducendo altro audio (TTS, soundboard o AI cover).",
                    ephemeral=True,
                )
            if music_active and vc.channel != user_voice.channel:
                return await interaction.response.send_message(
                    "❌ Sto già suonando in un altro canale vocale.", ephemeral=True
                )

        await interaction.response.defer()
        try:
            track = await asyncio.to_thread(extract_track, url)
        except NoMatches:
            return await interaction.followup.send("Nessun risultato per questo link/nome.")
        except Exception:
            log.exception("Caricamento fallito per %r", url)
            return await interaction.followup.send("❌ Caricamento fallito.")

        try:
            vc = guild.voice_client
            if vc is None:
                vc = await user_voice.channel.connect()
            elif vc.channel != user_voice.channel:
                await vc.move_to(user_voice.channel)
        except Exception:
            log.exception("Connessione vocale fallita")
            if player.current is None and not player.queue:
                self._drop_player(guild.id)
            return await interaction.followup.send("❌ Non riesco a connettermi al canale vocale.")

        self._cancel_idle(player)
        starting = not self._music_active(vc, player)
        player.queue.append(track)
        await self._play_next(guild)

        if starting:
            await interaction.followup.send(
                f"🎵 Track caricata: **{track.title}** di **{track.author}**"
            )
        else:
            await interaction.followup.send(
                f"➕ Aggiunta in coda (posizione {len(player.queue)}): "
                f"**{track.title}** di **{track.author}**"
            )

    @app_commands.command(name="pause", description="Mette in pausa la traccia")
    @app_commands.guild_only()
    async def pause(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ Traccia in pausa")
        else:
            await interaction.response.send_message(
                "❌ Nessuna traccia in riproduzione.", ephemeral=True
            )

    @app_commands.command(name="resume", description="Riprende la riproduzione")
    @app_commands.guild_only()
    async def resume(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Traccia in riproduzione")
        else:
            await interaction.response.send_message(
                "❌ La traccia non è in pausa.", ephemeral=True
            )

    @app_commands.command(name="stop", description="Ferma la riproduzione e svuota la coda")
    @app_commands.guild_only()
    async def stop(self, interaction: discord.Interaction) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        self._drop_player(interaction.guild.id)  # prima, così la callback `after` non riparte
        vc.stop()
        await vc.disconnect()
        await interaction.response.send_message("⏹️ Traccia stoppata")

    @app_commands.command(name="setvolume", description="Imposta il volume del bot")
    @app_commands.describe(volume=f"Il valore del volume (0-{MAX_VOLUME})")
    @app_commands.guild_only()
    async def setvolume(
        self,
        interaction: discord.Interaction,
        volume: app_commands.Range[int, 0, MAX_VOLUME],
    ) -> None:
        vc = await self._active_vc(interaction)
        if vc is None:
            return
        player = self.players[interaction.guild.id]
        player.volume = volume
        if player.source is not None:
            player.source.volume = volume / 100
        await interaction.response.send_message(f"🔊 Volume impostato al valore: {volume}")

    async def skip_if_active(self, interaction: discord.Interaction) -> bool:
        """
        Usato da /skip (ai_cover_cog.py). Se c'è musica in riproduzione salta la traccia,
        risponde all'interazione e restituisce True; altrimenti restituisce False
        senza toccare l'interazione.
        """
        player = self.players.get(interaction.guild.id)
        if player is None or not self._music_active(interaction.guild.voice_client, player):
            return False

        vc = await self._active_vc(interaction)
        if vc is None:
            return True  # risposta di errore già inviata

        if not player.queue:
            await interaction.response.send_message(
                "Non ci sono altre canzoni in coda.", ephemeral=True
            )
            return True

        upcoming = player.queue[0]
        vc.stop()  # la callback `after` avvia la prossima traccia
        await interaction.response.send_message(
            f"⏭️ Ora in riproduzione: **{upcoming.title}** di **{upcoming.author}**"
        )
        return True

    # ------------------------------------------------------------------ eventi

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        # Il bot è stato disconnesso (es. /leave del TTS o kick manuale): pulisci lo stato.
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            self._drop_player(member.guild.id)

    async def cog_unload(self) -> None:
        for guild_id in list(self.players):
            self._drop_player(guild_id)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        print("Music Ready!")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
