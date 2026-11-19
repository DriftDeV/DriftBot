"""
TTS con la voce «Giorgio» installata sul PC — per chi non può parlare in quel momento.

`/tts testo:<cosa dire>` fa leggere il testo dal bot nel canale vocale dell'utente con la voce italiana
Giorgio, sintetizzata in locale con pyttsx3 (nessun servizio esterno, nessun costo, il testo non lascia il PC).
Pensato per chi è in un posto dove non può parlare, ha il microfono rotto, o non può proprio parlare: scrive e
il bot parla al suo posto. (Il TTS ad AI con le voci clonate è `/tts-ai`.)

Comportamento:
  - il testo viene mostrato anche nel canale (chi ascolta e chi scrive vedono la stessa cosa);
  - coda per server: se più persone scrivono, il bot parla a turno senza interrompere nessuno;
  - limiti: una richiesta ogni pochi secondi per utente, massimo 3 in coda per utente e 10 per server;
  - il bot esce dalla vocale dopo un minuto di silenzio;
  - se sta già riproducendo altro audio (musica, AI cover...) lo dice invece di interromperlo.

La voce si cerca per nome («Giorgio») tra quelle installate nel sistema operativo. Se non c'è, /tts lo dice e
nel log compare l'elenco delle voci disponibili. `pyttsx3` è importato solo quando serve: senza la libreria il
bot parte lo stesso e /tts spiega cosa manca.
"""

import asyncio
import logging
import os
import re
import importlib.util
import tempfile
import threading
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs import escape_md

log = logging.getLogger(__name__)

MAX_CHARS = 300             # lunghezza massima di un messaggio
MAX_QUEUE = 10              # messaggi in coda per server
MAX_PER_USER = 3            # messaggi in coda per utente
COOLDOWN_SECONDS = 3        # un /tts ogni tot secondi per utente
IDLE_TIMEOUT = 60           # secondi di silenzio prima di lasciare la vocale
MAX_PLAY_SECONDS = 120      # un singolo messaggio non può parlare più di così

VOICE_NAME = "Giorgio"
RATE = 175                  # parole al minuto (pyttsx3: default ~200)


class SpeechError(Exception):
    """Errore atteso nella sintesi, con un messaggio adatto a essere mostrato all'utente."""


# --------------------------------------------------------------------------------------- testo

_USER_MENTION = re.compile(r"<@!?(\d+)>")
_ROLE_MENTION = re.compile(r"<@&(\d+)>")
_CHANNEL_MENTION = re.compile(r"<#(\d+)>")
_CUSTOM_EMOJI = re.compile(r"<a?:(\w+):\d+>")
_URL = re.compile(r"https?://\S+")


def clean_text(text: str, guild=None) -> str:
    """
    Prepara il testo per essere letto: menzioni -> nomi, link -> "link", emoji personalizzate -> nome,
    niente markdown né caratteri di controllo, spazi ripuliti. Può restituire una stringa vuota.
    """
    def user(match):
        member = guild.get_member(int(match.group(1))) if guild is not None and hasattr(guild, "get_member") else None
        return member.display_name if member is not None else "qualcuno"

    def role(match):
        found = guild.get_role(int(match.group(1))) if guild is not None and hasattr(guild, "get_role") else None
        return found.name if found is not None else "un ruolo"

    def channel(match):
        found = guild.get_channel(int(match.group(1))) if guild is not None and hasattr(guild, "get_channel") else None
        return found.name if found is not None else "un canale"

    text = _USER_MENTION.sub(user, text)
    text = _ROLE_MENTION.sub(role, text)
    text = _CHANNEL_MENTION.sub(channel, text)
    text = _CUSTOM_EMOJI.sub(lambda m: m.group(1), text)
    text = _URL.sub(" link ", text)
    text = text.translate({ord(c): None for c in "*~`|"})   # markdown: sparisce
    text = text.replace("_", " ")
    # citazioni ("> ") e titoli ("# ") a inizio riga: vanno tolti prima di appiattire i ritorni a capo
    text = "\n".join(re.sub(r"^[>#\s]+", "", line) for line in text.splitlines())
    # caratteri di controllo e di formattazione invisibili -> spazio (restano lettere, cifre, punteggiatura)
    text = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in text)
    return re.sub(r"\s+", " ", text).strip()


def is_readable(text: str) -> bool:
    """True se c'è qualcosa da leggere: almeno una lettera, una cifra o un simbolo/emoji (non solo punteggiatura)."""
    return any(unicodedata.category(c)[0] in "LN" or unicodedata.category(c) == "So" for c in text)


# -------------------------------------------------------------------------------------- motore

class LocalEngine:
    """Sintesi con la voce Giorgio installata sul PC (pyttsx3: SAPI5 su Windows, espeak su Linux, NSSpeech su macOS)."""

    _lock = threading.Lock()                # pyttsx3 non è pensato per usi concorrenti

    async def problem(self) -> Optional[str]:
        """Perché /tts non può funzionare (libreria mancante), oppure None."""
        if importlib.util.find_spec("pyttsx3") is None:
            return "La libreria `pyttsx3` non è installata (`pip install pyttsx3`)."
        return None

    async def synthesize(self, text: str, path: str) -> None:
        """Scrive in `path` un WAV con la voce di Giorgio. Solleva SpeechError per ogni problema."""
        await asyncio.to_thread(self._synthesize_sync, text, path)

    @staticmethod
    def _synthesize_sync(text: str, path: str) -> None:
        try:
            import pyttsx3
        except ImportError as e:
            raise SpeechError("La libreria `pyttsx3` non è installata (`pip install pyttsx3`).") from e
        with LocalEngine._lock:
            try:
                engine = pyttsx3.init()
                voices = engine.getProperty("voices")
                voice = next((v for v in voices if VOICE_NAME.lower() in v.name.lower()), None)
                if voice is None:
                    log.warning("Voce %s non trovata. Voci disponibili: %s", VOICE_NAME, [v.name for v in voices])
                    raise SpeechError(f"La voce {VOICE_NAME} non è installata su questo PC.")
                engine.setProperty("voice", voice.id)
                engine.setProperty("rate", RATE)
                engine.setProperty("volume", 1.0)
                engine.save_to_file(text, path)
                engine.runAndWait()
            except SpeechError:
                raise
            except Exception as e:
                log.warning("Errore del motore vocale locale: %s", type(e).__name__)
                raise SpeechError("Il motore vocale locale ha avuto un errore.") from e
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            raise SpeechError("Il motore vocale locale non ha prodotto nessun audio.")



# --------------------------------------------------------------------------------- stato

@dataclass
class Utterance:
    interaction: discord.Interaction
    member: discord.Member
    text: str


@dataclass
class GuildSpeech:
    queue: deque = field(default_factory=deque)
    worker: Optional[asyncio.Task] = None
    busy: bool = False                                  # il worker sta leggendo un messaggio (già tolto dalla coda)
    source: Optional[discord.AudioSource] = None       # la sorgente che stiamo riproducendo ORA
    idle_task: Optional[asyncio.Task] = None

    @property
    def active(self) -> bool:
        return self.worker is not None and not self.worker.done()


class LocalTTS(commands.Cog):
    """Fa parlare il bot con la voce di Giorgio (locale), a turno, per chi non può parlare."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.engine = LocalEngine()
        self.guilds: dict[int, GuildSpeech] = {}

    # ------------------------------------------------------------------ utilità

    def _state(self, guild_id: int) -> GuildSpeech:
        return self.guilds.setdefault(guild_id, GuildSpeech())

    def _drop(self, guild_id: int) -> None:
        state = self.guilds.pop(guild_id, None)
        if state is None:
            return
        for task in (state.worker, state.idle_task):
            if task is not None and not task.done():
                task.cancel()

    async def cog_unload(self) -> None:
        for guild_id in list(self.guilds):
            self._drop(guild_id)

    @staticmethod
    async def _private(item: Utterance, text: str) -> None:
        """Avvisa (in privato) chi ha scritto il messaggio. Non solleva mai."""
        try:
            await item.interaction.followup.send(text, ephemeral=True)
        except discord.HTTPException as e:
            log.debug("Impossibile avvisare l'utente: %s", e)

    def _schedule_idle(self, guild: discord.Guild, state: GuildSpeech) -> None:
        if state.idle_task is not None:
            state.idle_task.cancel()
        state.idle_task = asyncio.create_task(self._idle_disconnect(guild, state))

    async def _idle_disconnect(self, guild: discord.Guild, state: GuildSpeech) -> None:
        try:
            await asyncio.sleep(IDLE_TIMEOUT)
        except asyncio.CancelledError:
            return
        vc = guild.voice_client
        # mai se sta parlando, ha altro in coda o è subentrato altro audio (musica...)
        if state.active or state.queue or vc is None or not vc.is_connected():
            return
        if vc.is_playing() or vc.is_paused():
            return
        try:
            await vc.disconnect()
        except Exception as e:
            log.warning("Disconnessione per inattività fallita: %s", e)

    # ------------------------------------------------------------------ riproduzione

    async def _worker(self, guild: discord.Guild, state: GuildSpeech) -> None:
        try:
            while state.queue:
                item = state.queue.popleft()
                state.busy = True
                try:
                    await self._speak(guild, state, item)
                finally:
                    state.busy = False
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Errore imprevisto nel TTS")
        finally:
            state.worker = None
            if self.guilds.get(guild.id) is state:
                if state.queue:
                    # Un /tts è arrivato mentre questo worker veniva fermato da /tts-stop:
                    # senza questa ripartenza il messaggio resterebbe in coda per sempre
                    state.worker = asyncio.create_task(self._worker(guild, state))
                else:
                    self._schedule_idle(guild, state)

    async def _connect(self, guild: discord.Guild, channel: discord.VoiceChannel) -> discord.VoiceClient:
        vc = guild.voice_client
        if vc is None:
            return await channel.connect()
        if vc.channel != channel:
            await vc.move_to(channel)
        return vc

    async def _speak(self, guild: discord.Guild, state: GuildSpeech, item: Utterance) -> None:
        # Chi ha scritto potrebbe aver lasciato la vocale mentre aspettava il suo turno
        voice = item.member.voice
        if voice is None or voice.channel is None:
            return await self._private(item, "⚠️ Non sei più in un canale vocale: il messaggio non è stato letto.")

        path = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4()}.wav")
        vc = None
        source = None
        try:
            await self.engine.synthesize(item.text, path)
            if self.guilds.get(guild.id) is not state:
                return                                   # il bot è stato disconnesso nel frattempo

            vc = await self._connect(guild, voice.channel)
            if vc.is_playing() or vc.is_paused():
                return await self._private(item, "⚠️ Sto riproducendo altro audio: il messaggio non è stato letto.")

            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after(error):
                if error:
                    log.error("Errore di riproduzione del TTS: %s", error)
                loop.call_soon_threadsafe(done.set)

            source = discord.FFmpegPCMAudio(path)
            state.source = source
            vc.play(source, after=after)
            try:
                await asyncio.wait_for(done.wait(), MAX_PLAY_SECONDS)
            except asyncio.TimeoutError:
                vc.stop()
        except SpeechError as e:
            await self._private(item, f"❌ {e}")
        except asyncio.CancelledError:
            if vc is not None and source is not None and vc.source is source:
                vc.stop()
            raise
        except Exception:
            log.exception("Impossibile riprodurre il messaggio")
            await self._private(item, "❌ Non riesco a riprodurre il messaggio (FFmpeg installato? permessi della vocale?).")
        finally:
            state.source = None
            try:
                os.remove(path)
            except OSError:
                pass

    # ------------------------------------------------------------------ comandi

    @app_commands.command(name="tts", description="Legge il testo con la voce di Giorgio (per chi non può parlare)")
    @app_commands.describe(testo="Cosa deve dire il bot")
    @app_commands.checks.cooldown(1, COOLDOWN_SECONDS, key=lambda i: (i.guild_id, i.user.id))
    async def tts(
        self,
        interaction: discord.Interaction,
        testo: app_commands.Range[str, 1, MAX_CHARS],
    ) -> None:
        # Tutti i controlli PRIMA di rispondere, così gli errori restano privati (ephemeral)
        problem = await self.engine.problem()
        if problem:
            return await interaction.response.send_message(f"❌ Il TTS non è configurato: {problem}", ephemeral=True)

        user_voice = interaction.user.voice
        if user_voice is None or user_voice.channel is None:
            return await interaction.response.send_message("❌ Devi essere in un canale vocale!", ephemeral=True)

        text = clean_text(testo, interaction.guild)
        if not is_readable(text):
            return await interaction.response.send_message("❌ Non c'è niente da leggere in questo testo.", ephemeral=True)

        guild = interaction.guild
        state = self._state(guild.id)
        vc = guild.voice_client
        if vc is not None:
            if not state.active and (vc.is_playing() or vc.is_paused()):
                return await interaction.response.send_message(
                    "❌ Sto riproducendo altro audio (musica, TTS...): riprova quando finisce.", ephemeral=True
                )
            if vc.channel != user_voice.channel and (state.active or vc.is_playing()):
                return await interaction.response.send_message(
                    "❌ Sto già parlando in un altro canale vocale.", ephemeral=True
                )

        if len(state.queue) >= MAX_QUEUE:
            return await interaction.response.send_message(
                "⏳ Ci sono troppi messaggi in coda, riprova tra poco.", ephemeral=True
            )
        mine = sum(1 for item in state.queue if item.member.id == interaction.user.id)
        if mine >= MAX_PER_USER:
            return await interaction.response.send_message(
                f"⏳ Hai già {MAX_PER_USER} messaggi in coda: aspetta che vengano letti.", ephemeral=True
            )

        ahead = len(state.queue) + (1 if state.busy else 0)
        shown = f"🗣️ **{escape_md(interaction.user.display_name)}**: {escape_md(text)}"
        if ahead:
            shown += f"\n⏳ In coda (posizione {ahead + 1})"
        await interaction.response.send_message(shown[:2000], allowed_mentions=discord.AllowedMentions.none())

        if state.idle_task is not None:
            state.idle_task.cancel()
            state.idle_task = None
        state.queue.append(Utterance(interaction=interaction, member=interaction.user, text=text))
        if not state.active:
            state.worker = asyncio.create_task(self._worker(guild, state))

    @app_commands.command(name="tts-stop", description="Interrompe la lettura del TTS e svuota la coda")
    async def tts_stop(self, interaction: discord.Interaction) -> None:
        guild = interaction.guild
        state = self.guilds.get(guild.id)
        if state is None or not (state.active or state.queue):
            return await interaction.response.send_message("❌ Il bot non sta parlando.", ephemeral=True)

        vc = guild.voice_client
        user_voice = interaction.user.voice
        if vc is not None and (user_voice is None or user_voice.channel != vc.channel):
            return await interaction.response.send_message(
                "❌ Devi essere nel mio stesso canale vocale!", ephemeral=True
            )

        cleared = len(state.queue)
        state.queue.clear()
        if state.worker is not None and not state.worker.done():
            state.worker.cancel()            # interrompe anche la riproduzione in corso (vedi _speak)
        if vc is not None and state.source is not None and vc.source is state.source:
            vc.stop()
        await interaction.response.send_message(
            "🔇 Lettura interrotta" + (f" ({cleared} messaggi in coda eliminati)." if cleared else ".")
        )

    # ------------------------------------------------------------------ eventi

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        # Il bot è stato disconnesso (/leave, kick...): niente più coda né riproduzione
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            self._drop(member.guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LocalTTS(bot))
