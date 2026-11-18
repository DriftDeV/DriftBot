"""
Voce robotica — sintesi vocale NON AI per chi non può parlare in quel momento.

`/parla testo:<cosa dire>` fa leggere il testo dal bot nel canale vocale dell'utente, con la classica
voce robotica di eSpeak NG (sintetizzatore a formanti: nessun modello, nessuna GPU, risposta in pochi
millisecondi). Pensato per chi è in un posto dove non può parlare, ha il microfono rotto, o non può
proprio parlare: scrive e il bot parla al suo posto.

Comportamento:
  - il testo viene mostrato anche nel canale (chi ascolta e chi scrive vedono la stessa cosa);
  - coda per server: se più persone scrivono, il bot parla a turno senza interrompere nessuno;
  - limiti: una richiesta ogni pochi secondi per utente, massimo 3 in coda per utente e 10 per server;
  - il bot esce dalla vocale dopo un minuto di silenzio;
  - se sta già riproducendo altro audio (musica, AI cover...) lo dice invece di interromperlo.

Requisiti: il programma `espeak-ng` (o il vecchio `espeak`) nel PATH.
  Linux: sudo apt install espeak-ng  |  sudo dnf install espeak-ng
  macOS: brew install espeak-ng      |  Windows: winget install eSpeak-NG.eSpeak-NG
  Se si trova altrove: ESPEAK_PATH=/percorso/di/espeak-ng nel file .env.

Il testo arriva a eSpeak da stdin, mai nella riga di comando: così un testo che inizia con "-" non
può essere scambiato per un'opzione e non c'è nessun passaggio dalla shell.
"""

import asyncio
import logging
import os
import re
import shutil
import tempfile
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
COOLDOWN_SECONDS = 3        # un /parla ogni tot secondi per utente
IDLE_TIMEOUT = 60           # secondi di silenzio prima di lasciare la vocale
SYNTH_TIMEOUT = 20          # secondi massimi per la sintesi
MAX_PLAY_SECONDS = 120      # un singolo messaggio non può parlare più di così
MIN_WAV_BYTES = 1000        # sotto questa dimensione il WAV è solo silenzio (intestazione di 352 byte per testo vuoto)

# codice lingua mostrato all'utente -> voce di eSpeak
LANGUAGES = {"it": "it", "en": "en", "es": "es", "fr": "fr", "de": "de", "pt": "pt-br"}
LANGUAGE_NAMES = {"it": "Italiano", "en": "English", "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português"}
DEFAULT_LANGUAGE = "it"

# voce -> (variante eSpeak, tono 0-99)
VOICES = {
    "robot": ("", 50),
    "grave": ("+m3", 25),
    "acuta": ("+f3", 70),
    "sussurro": ("+whisper", 50),
}
VOICE_NAMES = {"robot": "Robot", "grave": "Robot grave", "acuta": "Robot acuta", "sussurro": "Sussurro"}
DEFAULT_VOICE = "robot"

# velocità -> parole al minuto
SPEEDS = {"lenta": 120, "normale": 160, "veloce": 210}
DEFAULT_SPEED = "normale"


class SpeechError(Exception):
    """Errore atteso nella sintesi, con un messaggio adatto a essere mostrato all'utente."""


# ------------------------------------------------------------------------------ testo

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


# ---------------------------------------------------------------------------- motore

def find_engine() -> Optional[str]:
    """Percorso di eSpeak NG (o del vecchio eSpeak), oppure None se non è installato."""
    override = os.getenv("ESPEAK_PATH", "").strip()
    if override:
        return shutil.which(override)
    return shutil.which("espeak-ng") or shutil.which("espeak")


def build_command(engine: str, out_path: str, language: str, voice: str, speed: str) -> list[str]:
    """Riga di comando di eSpeak. Il testo NON ne fa parte: va passato da stdin."""
    variant, pitch = VOICES.get(voice, VOICES[DEFAULT_VOICE])
    espeak_voice = LANGUAGES.get(language, LANGUAGES[DEFAULT_LANGUAGE])
    return [
        engine,
        "-v", f"{espeak_voice}{variant}",
        "-s", str(SPEEDS.get(speed, SPEEDS[DEFAULT_SPEED])),
        "-p", str(pitch),
        "-a", "150",              # ampiezza: più alta del default (100) per sentirsi bene in vocale
        "-w", out_path,
        "--stdin",
    ]


async def synthesize(engine: str, text: str, out_path: str, language: str, voice: str, speed: str) -> None:
    """Scrive in `out_path` il WAV con la voce robotica. Solleva SpeechError per ogni problema."""
    cmd = build_command(engine, out_path, language, voice, speed)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as e:
        log.error("Impossibile avviare %s: %s", engine, e)
        raise SpeechError("Il motore vocale non si avvia: controlla che espeak-ng sia installato.") from e

    try:
        _, stderr = await asyncio.wait_for(proc.communicate(text.encode("utf-8") + b"\n"), SYNTH_TIMEOUT)
    except asyncio.TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise SpeechError("Il motore vocale ci ha messo troppo.") from e
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise

    if proc.returncode != 0:
        log.error("%s è uscito con codice %s: %s", engine, proc.returncode, stderr.decode("utf-8", "replace")[:200])
        raise SpeechError("Il motore vocale non è riuscito a leggere questo testo.")
    # Con un testo senza nulla da leggere eSpeak esce con 0 e non scrive il file, oppure ne scrive uno
    # di pochi byte (solo l'intestazione WAV: ~7 ms di silenzio)
    if not os.path.exists(out_path) or os.path.getsize(out_path) < MIN_WAV_BYTES:
        raise SpeechError("Non c'è niente da leggere in questo testo.")


# --------------------------------------------------------------------------------- stato

@dataclass
class Utterance:
    interaction: discord.Interaction
    member: discord.Member
    text: str
    language: str
    voice: str
    speed: str


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


VOICE_CHOICES = [app_commands.Choice(name=VOICE_NAMES[k], value=k) for k in VOICES]
SPEED_CHOICES = [app_commands.Choice(name=k.capitalize(), value=k) for k in SPEEDS]
LANGUAGE_CHOICES = [app_commands.Choice(name=LANGUAGE_NAMES[k], value=k) for k in LANGUAGES]


class RobotVoice(commands.Cog):
    """Fa parlare il bot con una voce robotica, a turno, per chi non può parlare."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
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
            log.exception("Errore imprevisto nella voce robotica")
        finally:
            state.worker = None
            if self.guilds.get(guild.id) is state:
                if state.queue:
                    # Un /parla è arrivato mentre questo worker veniva fermato da /parla-stop:
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

        engine = find_engine()
        if engine is None:
            return await self._private(item, "❌ Il motore vocale (espeak-ng) non è installato sul server.")

        path = os.path.join(tempfile.gettempdir(), f"robotvoice_{uuid.uuid4()}.wav")
        vc = None
        source = None
        try:
            await synthesize(engine, item.text, path, item.language, item.voice, item.speed)
            if self.guilds.get(guild.id) is not state:
                return                                   # il bot è stato disconnesso nel frattempo

            vc = await self._connect(guild, voice.channel)
            if vc.is_playing() or vc.is_paused():
                return await self._private(item, "⚠️ Sto riproducendo altro audio: il messaggio non è stato letto.")

            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after(error):
                if error:
                    log.error("Errore di riproduzione della voce robotica: %s", error)
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

    @app_commands.command(name="parla", description="Fa parlare il bot con una voce robotica (per chi non può parlare)")
    @app_commands.describe(
        testo="Cosa deve dire il bot",
        voce="Il tipo di voce robotica (default: Robot)",
        velocita="Quanto parla veloce (default: normale)",
        lingua="La lingua del testo (default: italiano)",
    )
    @app_commands.choices(voce=VOICE_CHOICES, velocita=SPEED_CHOICES, lingua=LANGUAGE_CHOICES)
    @app_commands.checks.cooldown(1, COOLDOWN_SECONDS, key=lambda i: (i.guild_id, i.user.id))
    async def parla(
        self,
        interaction: discord.Interaction,
        testo: app_commands.Range[str, 1, MAX_CHARS],
        voce: Optional[str] = None,
        velocita: Optional[str] = None,
        lingua: Optional[str] = None,
    ) -> None:
        # Tutti i controlli PRIMA di rispondere, così gli errori restano privati (ephemeral)
        if find_engine() is None:
            return await interaction.response.send_message(
                "❌ Il motore vocale (espeak-ng) non è installato sul server: chiedi a chi gestisce il bot di installarlo.",
                ephemeral=True,
            )

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
        shown = f"🤖 **{escape_md(interaction.user.display_name)}**: {escape_md(text)}"
        if ahead:
            shown += f"\n⏳ In coda (posizione {ahead + 1})"
        await interaction.response.send_message(shown[:2000], allowed_mentions=discord.AllowedMentions.none())

        if state.idle_task is not None:
            state.idle_task.cancel()
            state.idle_task = None
        state.queue.append(Utterance(
            interaction=interaction,
            member=interaction.user,
            text=text,
            language=lingua if lingua in LANGUAGES else DEFAULT_LANGUAGE,
            voice=voce if voce in VOICES else DEFAULT_VOICE,
            speed=velocita if velocita in SPEEDS else DEFAULT_SPEED,
        ))
        if not state.active:
            state.worker = asyncio.create_task(self._worker(guild, state))

    @app_commands.command(name="parla-stop", description="Interrompe la voce robotica e svuota la coda")
    async def parla_stop(self, interaction: discord.Interaction) -> None:
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
            "🔇 Voce robotica interrotta" + (f" ({cleared} messaggi in coda eliminati)." if cleared else ".")
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
    await bot.add_cog(RobotVoice(bot))
