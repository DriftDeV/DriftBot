"""
TTS con la voce «Giorgio» di Amazon Polly — per chi non può parlare in quel momento.

`/tts testo:<cosa dire>` fa leggere il testo dal bot nel canale vocale dell'utente con la voce italiana
Giorgio di Amazon Polly. Pensato per chi è in un posto dove non può parlare, ha il microfono rotto, o non
può proprio parlare: scrive e il bot parla al suo posto. (Il TTS ad AI con le voci clonate è `/tts-ai`.)

Comportamento:
  - il testo viene mostrato anche nel canale (chi ascolta e chi scrive vedono la stessa cosa);
  - coda per server: se più persone scrivono, il bot parla a turno senza interrompere nessuno;
  - limiti: una richiesta ogni pochi secondi per utente, massimo 3 in coda per utente e 10 per server;
  - il bot esce dalla vocale dopo un minuto di silenzio;
  - se sta già riproducendo altro audio (musica, AI cover...) lo dice invece di interromperlo.

Polly è un servizio a pagamento (a carattere) e il testo viene inviato ad AWS. Per contenere la spesa:
  - tetto giornaliero di caratteri (TTS_DAILY_CHARS, default 50000, 0 = illimitato; si azzera a mezzanotte UTC
    e al riavvio del bot);
  - cache delle frasi già sintetizzate ("sì", "no", "ciao"...): ripeterle non costa nulla ed è istantaneo;
  - il testo viene inviato come testo semplice, mai come SSML (nessuna iniezione di markup).

Configurazione (file .env):
  AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY    credenziali AWS con il permesso polly:SynthesizeSpeech
  AWS_REGION                                    default eu-central-1 (anche AWS_DEFAULT_REGION)
  POLLY_ENGINE                                  standard (default), neural, long-form o generative
  TTS_DAILY_CHARS                               tetto giornaliero di caratteri

`boto3` è importato solo quando serve: senza la libreria il bot parte lo stesso e /tts spiega cosa manca.
"""

import asyncio
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
CACHE_MAX_ITEMS = 64        # frasi tenute in cache
CACHE_MAX_BYTES = 8 * 1024 * 1024
CONFIG_CHECK_TTL = 30       # secondi in cui si ricorda l'esito del controllo delle credenziali

VOICE_ID = "Giorgio"
LANGUAGE_CODE = "it-IT"
ENGINES = ("standard", "neural", "long-form", "generative")
DEFAULT_REGION = "eu-central-1"
DEFAULT_DAILY_CHARS = 50000


class SpeechError(Exception):
    """Errore atteso nella sintesi, con un messaggio adatto a essere mostrato all'utente (mai chiavi o dettagli AWS)."""


# ----------------------------------------------------------------------------- configurazione

@dataclass
class PollyConfig:
    region: str = DEFAULT_REGION
    engine: str = "standard"
    daily_chars: int = DEFAULT_DAILY_CHARS     # 0 = illimitato
    timeout: float = 15
    max_attempts: int = 2                      # boto3 ripete da solo le richieste fallite per errori transitori
    endpoint_url: str = ""                     # facoltativo (test, proxy, endpoint VPC)

    @classmethod
    def from_env(cls) -> "PollyConfig":
        engine = os.getenv("POLLY_ENGINE", "").strip().lower() or cls.engine
        if engine not in ENGINES:
            log.warning("POLLY_ENGINE=%r non valido: uso %s", engine, cls.engine)
            engine = cls.engine
        try:
            daily = int(os.getenv("TTS_DAILY_CHARS", DEFAULT_DAILY_CHARS))
        except ValueError:
            log.warning("TTS_DAILY_CHARS non è un intero valido: uso %s", DEFAULT_DAILY_CHARS)
            daily = DEFAULT_DAILY_CHARS
        region = os.getenv("AWS_REGION", "").strip() or os.getenv("AWS_DEFAULT_REGION", "").strip() or cls.region
        return cls(region=region, engine=engine, daily_chars=max(0, daily))


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

# Codici di errore di Polly/AWS -> messaggio per l'utente
_AUTH_ERRORS = {
    "UnrecognizedClientException", "InvalidSignatureException", "InvalidClientTokenId", "SignatureDoesNotMatch",
    "AccessDeniedException", "AccessDenied", "ExpiredTokenException", "ExpiredToken", "IncompleteSignature",
    "MissingAuthenticationToken", "AuthFailure", "InvalidAccessKeyId",
}
_THROTTLE_ERRORS = {
    "ThrottlingException", "Throttling", "TooManyRequestsException", "RequestLimitExceeded", "LimitExceededException",
}
_SERVICE_ERRORS = {"ServiceFailureException", "ServiceUnavailable", "InternalFailure", "InternalServerError"}


class PollyEngine:
    """Sintesi con Amazon Polly (SDK ufficiale boto3, in un thread) con cache e tetto giornaliero di caratteri."""

    def __init__(self, config: PollyConfig):
        self.config = config
        self._client = None
        self._cache: "OrderedDict[str, bytes]" = OrderedDict()
        self._cache_bytes = 0
        self._day: Optional[str] = None
        self._spent = 0
        self._checked_at: Optional[float] = None
        self._problem: Optional[str] = None

    # ------------------------------------------------------------------ configurazione

    @staticmethod
    def _import_boto():
        try:
            import boto3
            import botocore.config
            import botocore.exceptions
        except ImportError as e:
            raise SpeechError("La libreria `boto3` non è installata (`pip install boto3`).") from e
        return boto3, botocore

    def _problem_sync(self) -> Optional[str]:
        try:
            boto3, _ = self._import_boto()
        except SpeechError as e:
            return str(e)
        # get_credentials() può leggere file e interrogare i metadati di EC2: va fatto fuori dall'event loop
        if boto3.session.Session().get_credentials() is None:
            return (
                "Mancano le credenziali AWS: imposta AWS_ACCESS_KEY_ID e AWS_SECRET_ACCESS_KEY nel file .env "
                "(vedi README)."
            )
        return None

    async def problem(self) -> Optional[str]:
        """Perché /tts non può funzionare (libreria o credenziali mancanti), oppure None. Il risultato si ricorda per poco."""
        # Si ricorda anche l'esito NEGATIVO: senza credenziali boto3 può interrogare i metadati di EC2
        # (secondi di attesa) e /tts deve rispondere entro 3 secondi.
        loop = asyncio.get_running_loop()
        if self._checked_at is None or loop.time() - self._checked_at > CONFIG_CHECK_TTL:
            self._problem = await asyncio.to_thread(self._problem_sync)
            self._checked_at = loop.time()
        return self._problem

    def _get_client(self):
        if self._client is None:
            boto3, botocore = self._import_boto()
            kwargs = {
                "region_name": self.config.region,
                "config": botocore.config.Config(
                    connect_timeout=5,
                    read_timeout=self.config.timeout,
                    retries={"max_attempts": self.config.max_attempts, "mode": "standard"},
                ),
            }
            if self.config.endpoint_url:
                kwargs["endpoint_url"] = self.config.endpoint_url
            # Sessione propria (non quella globale di boto3): le credenziali si risolvono per questo motore e
            # non restano in uno stato condiviso con altro codice
            self._client = boto3.session.Session().client("polly", **kwargs)
        return self._client

    # ------------------------------------------------------------------ tetto di spesa

    def _roll_day(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._day:
            self._day, self._spent = today, 0

    def remaining(self) -> Optional[int]:
        """Caratteri ancora disponibili oggi, oppure None se non c'è un tetto."""
        if self.config.daily_chars <= 0:
            return None
        self._roll_day()
        return max(0, self.config.daily_chars - self._spent)

    # ------------------------------------------------------------------ cache

    def _cache_get(self, text: str) -> Optional[bytes]:
        data = self._cache.get(text)
        if data is not None:
            self._cache.move_to_end(text)
        return data

    def _cache_put(self, text: str, data: bytes) -> None:
        if len(data) > CACHE_MAX_BYTES // 4:
            return                                                   # un singolo file enorme non si tiene
        if text in self._cache:
            self._cache_bytes -= len(self._cache.pop(text))
        self._cache[text] = data
        self._cache_bytes += len(data)
        while len(self._cache) > CACHE_MAX_ITEMS or self._cache_bytes > CACHE_MAX_BYTES:
            _, old = self._cache.popitem(last=False)
            self._cache_bytes -= len(old)

    # ------------------------------------------------------------------ sintesi

    async def synthesize(self, text: str) -> bytes:
        """MP3 con la voce di Giorgio. Solleva SpeechError per ogni problema."""
        cached = self._cache_get(text)
        if cached is not None:
            return cached                                            # già pagata: niente costo, istantanea

        remaining = self.remaining()
        if remaining is not None and len(text) > remaining:
            raise SpeechError("Il limite giornaliero di caratteri del TTS è stato raggiunto: riprova domani.")
        data = await asyncio.to_thread(self._synthesize_sync, text)
        self._spent += len(text)
        self._cache_put(text, data)
        return data

    def _synthesize_sync(self, text: str) -> bytes:
        _, botocore = self._import_boto()
        exceptions = botocore.exceptions
        client = self._get_client()
        try:
            response = client.synthesize_speech(
                Text=text,
                TextType="text",              # mai SSML: il testo dell'utente non deve poter inserire markup
                OutputFormat="mp3",
                VoiceId=VOICE_ID,
                LanguageCode=LANGUAGE_CODE,
                Engine=self.config.engine,
            )
            stream = response["AudioStream"]
            try:
                data = stream.read()
            finally:
                stream.close()
        except (exceptions.NoCredentialsError, exceptions.PartialCredentialsError) as e:
            raise SpeechError("Mancano le credenziali AWS (vedi README).") from e
        except exceptions.ClientError as e:
            raise self._map_client_error(e) from e
        except (exceptions.ConnectTimeoutError, exceptions.ReadTimeoutError) as e:
            raise SpeechError("Amazon Polly non ha risposto in tempo.") from e
        except exceptions.EndpointConnectionError as e:
            raise SpeechError("Amazon Polly non è raggiungibile (problema di rete?).") from e
        except exceptions.BotoCoreError as e:
            log.warning("Errore boto3 verso Polly: %s", type(e).__name__)
            raise SpeechError("Errore di comunicazione con Amazon Polly.") from e

        if not data:
            raise SpeechError("Amazon Polly non ha restituito nessun audio.")
        return data

    def _map_client_error(self, error) -> SpeechError:
        info = error.response.get("Error", {})
        code = info.get("Code", "")
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        # Si logga solo il codice: il messaggio di AWS può contenere ARN o dettagli dell'account
        log.warning("Polly ha risposto con l'errore %s (HTTP %s)", code, status)
        if code in _AUTH_ERRORS:
            return SpeechError("Le credenziali AWS non sono valide o non permettono di usare Polly (serve polly:SynthesizeSpeech).")
        if code in _THROTTLE_ERRORS:
            return SpeechError("Amazon Polly ha troppe richieste: riprova tra poco.")
        if code == "EngineNotSupportedException":
            return SpeechError(
                f"La voce {VOICE_ID} non supporta il motore `{self.config.engine}` in questa regione: "
                "imposta POLLY_ENGINE (standard, neural, long-form o generative)."
            )
        if code == "LanguageNotSupportedException":
            return SpeechError(f"La voce {VOICE_ID} non è disponibile in questa regione AWS: prova con un'altra AWS_REGION.")
        if code == "TextLengthExceededException":
            return SpeechError("Il testo è troppo lungo per Amazon Polly.")
        if code in _SERVICE_ERRORS or status >= 500:
            return SpeechError("Amazon Polly è momentaneamente non disponibile.")
        return SpeechError("Amazon Polly ha rifiutato la richiesta.")

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                await asyncio.to_thread(client.close)
            except Exception:
                log.debug("Chiusura del client Polly non riuscita", exc_info=True)


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


class PollyTTS(commands.Cog):
    """Fa parlare il bot con la voce di Giorgio (Amazon Polly), a turno, per chi non può parlare."""

    def __init__(self, bot: commands.Bot, config: Optional[PollyConfig] = None):
        self.bot = bot
        self.engine = PollyEngine(config or PollyConfig.from_env())
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
        await self.engine.close()

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

        path = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4()}.mp3")
        vc = None
        source = None
        try:
            audio = await self.engine.synthesize(item.text)
            if self.guilds.get(guild.id) is not state:
                return                                   # il bot è stato disconnesso nel frattempo
            with open(path, "wb") as f:
                f.write(audio)

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

        remaining = self.engine.remaining()
        if remaining is not None and remaining <= 0:
            return await interaction.response.send_message(
                "❌ Il limite giornaliero di caratteri del TTS è stato raggiunto: riprova domani.", ephemeral=True
            )

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
    await bot.add_cog(PollyTTS(bot))
