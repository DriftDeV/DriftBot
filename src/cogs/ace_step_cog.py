"""
ACE-Step cog — genera musica da un prompt di testo con ACE-Step 1.5.

Catena (pensata per GPU da 8 GB, dove LLM e modello musicale non entrano insieme in VRAM):

    prompt -> [se manca il testo] un LLM scrive il testo -> [Ollama] LLM SCARICATO dalla VRAM
           -> ACE-Step compone il brano con quel testo -> il bot lo allega alla risposta

L'LLM è Claude (API) se nel .env c'è ANTHROPIC_API_KEY, altrimenti Ollama in locale (vedi text_llm.py).

Il cog NON carica modelli nel processo del bot: parla con il server REST di ACE-Step (`acestep-api`)
e con l'LLM (Claude via API oppure un server Ollama). Motivi:
  - nessun conflitto di dipendenze con chatterbox/RVC (torch, transformers),
  - il bot non si blocca e non tiene la VRAM occupata,
  - CUDA (NVIDIA) o ROCm (AMD) li gestisce l'installazione dei server, non il bot,
  - Ollama sa scaricare il modello dalla VRAM subito dopo l'uso (vedi lyrics_llm.py).

Un solo lavoro GPU alla volta (lock globale sulla catena): con Ollama l'LLM di un utente si
caricherebbe mentre ACE-Step genera per un altro, e su 8 GB non ci sta. Con Claude la scrittura del
testo non usa la GPU locale e avviene FUORI dal lock: gli altri utenti non aspettano la API.

Contratto ACE-Step usato (documentazione ACE-Step 1.5, docs/en/API.md):
  POST /release_task   {prompt, lyrics, audio_duration, vocal_language, ...}  -> data.task_id
  POST /query_result   {task_id_list: [...]}     -> data[].status 0=in corso 1=ok 2=fallito
  GET  /v1/audio?path=...                        -> file audio
Ogni risposta JSON ha la busta {data, code, error, timestamp, extra}.

Configurazione (file .env):
  ACESTEP_API_URL           default http://127.0.0.1:8001
  ACESTEP_API_KEY           opzionale (header Authorization: Bearer)
  ACESTEP_MAX_SECONDS       durata massima E predefinita, default 180 (il server accetta fino a 600)
  ACESTEP_TIMEOUT           secondi massimi di attesa per una generazione, default 600
  ACESTEP_MAX_PENDING       richieste accettate contemporaneamente dal bot (in coda + in corso), default 5
  ACESTEP_AUDIO_FORMAT      mp3 (default), flac, opus, aac, wav
  ACESTEP_DEFAULT_LANGUAGE  lingua del testo se non indicata: it (default), en, es, fr, de, pt
  ANTHROPIC_API_KEY, CLAUDE_*, LYRICS_LLM_*   LLM che scrive il testo: vedi text_llm.py
"""

import asyncio
import io
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from lyrics_llm import DEFAULT_LANGUAGE, LANGUAGES, LyricsWriter
from text_llm import LLMConfig, LLMError, TextGenerator, build_generator

log = logging.getLogger(__name__)

SERVER_MIN_SECONDS = 10     # limiti del server ACE-Step
SERVER_MAX_SECONDS = 600
INSTRUMENTAL_LYRICS = "[Instrumental]"
ALLOWED_FORMATS = ("mp3", "flac", "opus", "aac", "wav")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Legge un intero dall'ambiente, tollerando valori assenti o non validi."""
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        log.warning("%s non è un intero valido: uso %s", name, default)
        return default
    return max(minimum, min(maximum, value))


@dataclass
class AceStepConfig:
    base_url: str = "http://127.0.0.1:8001"
    api_key: str = ""
    max_seconds: int = 180
    timeout: int = 600
    max_pending: int = 5
    audio_format: str = "mp3"
    poll_interval: float = 3.0
    default_language: str = DEFAULT_LANGUAGE
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls) -> "AceStepConfig":
        audio_format = os.getenv("ACESTEP_AUDIO_FORMAT", "mp3").strip().lower()
        if audio_format not in ALLOWED_FORMATS:
            log.warning("ACESTEP_AUDIO_FORMAT=%r non valido: uso mp3", audio_format)
            audio_format = "mp3"
        language = os.getenv("ACESTEP_DEFAULT_LANGUAGE", DEFAULT_LANGUAGE).strip().lower()
        if language not in LANGUAGES:
            log.warning("ACESTEP_DEFAULT_LANGUAGE=%r non supportata: uso %s", language, DEFAULT_LANGUAGE)
            language = DEFAULT_LANGUAGE
        return cls(
            default_language=language,
            llm=LLMConfig.from_env(),
            base_url=os.getenv("ACESTEP_API_URL", cls.base_url).strip().rstrip("/") or cls.base_url,
            api_key=os.getenv("ACESTEP_API_KEY", "").strip(),
            max_seconds=_env_int("ACESTEP_MAX_SECONDS", 180, SERVER_MIN_SECONDS, SERVER_MAX_SECONDS),
            timeout=_env_int("ACESTEP_TIMEOUT", 600, 30, 3000),
            max_pending=_env_int("ACESTEP_MAX_PENDING", 5, 1, 50),
            audio_format=audio_format,
        )


# Il massimo della durata finisce nella definizione dello slash command: va letto all'import
# (main.py ha già caricato il .env). Il valore viene comunque riverificato a runtime.
MAX_SECONDS = AceStepConfig.from_env().max_seconds


class AceStepError(Exception):
    """Errore atteso, con un messaggio già adatto a essere mostrato all'utente."""


# ---------------------------------------------------------------------------------- client

class AceStepClient:
    """Client minimale e tollerante per il server REST di ACE-Step 1.5."""

    def __init__(self, config: AceStepConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session

    def _headers(self) -> dict:
        headers = {"Accept": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    @staticmethod
    def _check_http(status: int) -> None:
        if status in (401, 403):
            raise AceStepError("Il server ACE-Step ha rifiutato la richiesta (API key mancante o errata).")
        if status == 429:
            raise AceStepError("La coda del server ACE-Step è piena, riprova tra qualche minuto.")
        if status >= 400:
            raise AceStepError(f"Il server ACE-Step ha risposto con un errore (HTTP {status}).")

    async def _request_json(self, method: str, path: str, **kwargs) -> Any:
        """Esegue la richiesta e restituisce `data` della busta di risposta."""
        try:
            async with self.session.request(
                method, self._url(path), headers=self._headers(),
                timeout=aiohttp.ClientTimeout(total=30), **kwargs,
            ) as response:
                self._check_http(response.status)
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as e:
                    raise AceStepError("Risposta non valida dal server ACE-Step.") from e
        except aiohttp.ClientConnectorError as e:
            raise AceStepError(
                "Il server ACE-Step non è raggiungibile. Va avviato a parte (vedi README)."
            ) from e
        except asyncio.TimeoutError as e:
            raise AceStepError("Il server ACE-Step non risponde (timeout).") from e
        except aiohttp.ClientError as e:
            log.warning("Errore di rete verso ACE-Step: %s", e)
            raise AceStepError("Errore di comunicazione con il server ACE-Step.") from e

        if not isinstance(payload, dict):
            raise AceStepError("Risposta non valida dal server ACE-Step.")
        code = payload.get("code", 200)
        if code != 200:
            log.warning("ACE-Step: code=%s error=%s", code, payload.get("error"))
            raise AceStepError("Il server ACE-Step ha segnalato un errore.")
        return payload.get("data")

    async def health(self) -> bool:
        try:
            data = await self._request_json("GET", "/health")
        except AceStepError:
            return False
        return isinstance(data, dict) and data.get("status") == "ok"

    async def submit(
        self, prompt: str, lyrics: Optional[str], seconds: int, language: str = DEFAULT_LANGUAGE
    ) -> tuple[str, Optional[int]]:
        """Accoda una generazione. Restituisce (task_id, posizione in coda)."""
        body = {
            "prompt": prompt,
            "lyrics": lyrics or INSTRUMENTAL_LYRICS,
            "vocal_language": language,
            "audio_duration": seconds,
            "batch_size": 1,                       # un solo brano: più veloce e un solo file da inviare
            "audio_format": self.config.audio_format,
            "use_random_seed": True,
            "task_type": "text2music",
        }
        data = await self._request_json("POST", "/release_task", json=body)
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not task_id:
            raise AceStepError("Il server ACE-Step non ha restituito un task valido.")
        position = data.get("queue_position")
        return str(task_id), position if isinstance(position, int) else None

    async def query(self, task_id: str) -> tuple[int, Optional[dict]]:
        """
        Stato di un task: (0 in corso | 1 completato | 2 fallito, dettagli del risultato).
        I dettagli sono il primo elemento del JSON `result` (contiene `file`, `metas`, ...).
        """
        data = await self._request_json("POST", "/query_result", json={"task_id_list": [task_id]})
        items = data if isinstance(data, list) else []
        item = next((i for i in items if isinstance(i, dict) and i.get("task_id") == task_id), None)
        if item is None:
            raise AceStepError("Il server ACE-Step non conosce più questa richiesta (riavviato?).")

        status = item.get("status")
        if status != 1:
            return (2 if status == 2 else 0), None

        result = item.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError as e:
                raise AceStepError("Risultato non valido dal server ACE-Step.") from e
        first = result[0] if isinstance(result, list) and result else result
        if not isinstance(first, dict):
            raise AceStepError("Risultato non valido dal server ACE-Step.")
        if first.get("status") == 2:       # il task è finito ma il brano singolo è fallito
            return 2, None
        return 1, first

    async def wait_for_result(self, task_id: str, on_running=None) -> dict:
        """Attende il completamento (polling). `on_running` è chiamata una volta all'avvio."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.timeout
        announced = False
        while True:
            status, details = await self.query(task_id)
            if status == 1:
                return details
            if status == 2:
                raise AceStepError("La generazione è fallita sul server ACE-Step.")
            if not announced and on_running is not None:
                announced = True
                await on_running()
            if loop.time() >= deadline:
                raise AceStepError(
                    f"La generazione ha superato il tempo massimo ({self.config.timeout}s)."
                )
            await asyncio.sleep(self.config.poll_interval)

    async def download(self, file_ref: str, max_bytes: int) -> bytes:
        """Scarica il file audio. Accetta solo URL relativi o dello stesso server, entro `max_bytes`."""
        base = urlparse(self.config.base_url)
        url = urljoin(self.config.base_url + "/", file_ref)
        target = urlparse(url)
        if (target.scheme, target.netloc) != (base.scheme, base.netloc):
            # il server è affidabile, ma non seguiamo mai un link verso un altro host
            raise AceStepError("Il server ACE-Step ha restituito un link audio non valido.")

        try:
            async with self.session.get(
                url, headers=self._headers(), timeout=aiohttp.ClientTimeout(total=180)
            ) as response:
                self._check_http(response.status)
                declared = response.content_length
                if declared is not None and declared > max_bytes:
                    raise AceStepError(self._too_big(declared, max_bytes))
                buffer = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    buffer.extend(chunk)
                    if len(buffer) > max_bytes:
                        raise AceStepError(self._too_big(len(buffer), max_bytes))
        except asyncio.TimeoutError as e:
            raise AceStepError("Download del brano scaduto (timeout).") from e
        except aiohttp.ClientError as e:
            log.warning("Download da ACE-Step fallito: %s", e)
            raise AceStepError("Impossibile scaricare il brano dal server ACE-Step.") from e
        if not buffer:
            raise AceStepError("Il server ACE-Step ha restituito un file vuoto.")
        return bytes(buffer)

    @staticmethod
    def _too_big(size: int, limit: int) -> str:
        return (
            f"Il brano pesa {size / 1_000_000:.1f} MB ma Discord accetta al massimo "
            f"{limit / 1_000_000:.0f} MB in questo server: prova con una durata più breve."
        )


# -------------------------------------------------------------------------------------- cog

LANGUAGE_CHOICES = [
    app_commands.Choice(name="Italiano", value="it"),
    app_commands.Choice(name="English", value="en"),
    app_commands.Choice(name="Español", value="es"),
    app_commands.Choice(name="Français", value="fr"),
    app_commands.Choice(name="Deutsch", value="de"),
    app_commands.Choice(name="Português", value="pt"),
]


class AceStepMusic(commands.Cog):
    """Genera musica da un prompt con ACE-Step, scrivendo il testo con un LLM se manca."""

    def __init__(self, bot: commands.Bot, config: Optional[AceStepConfig] = None):
        self.bot = bot
        self.config = config or AceStepConfig.from_env()
        self._session: Optional[aiohttp.ClientSession] = None
        self._active_users: set[int] = set()
        # Un solo lavoro GPU alla volta: LLM e ACE-Step non devono mai essere in VRAM insieme.
        self._gpu_lock = asyncio.Lock()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _client(self) -> AceStepClient:
        return AceStepClient(self.config, self._http())

    async def cog_unload(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def _edit(self, interaction: discord.Interaction, **kwargs) -> bool:
        """Modifica il messaggio di risposta. False se non è più possibile (token scaduto, ecc.)."""
        try:
            await interaction.edit_original_response(**kwargs)
            return True
        except discord.HTTPException as e:
            log.debug("edit_original_response non riuscito: %s", e)
            return False

    async def _deliver(
        self,
        interaction: discord.Interaction,
        *,
        content: Optional[str] = None,
        embed: Optional[discord.Embed] = None,
        audio: Optional[bytes] = None,
        filename: str = "ace-step.mp3",
    ) -> None:
        """
        Consegna il risultato all'utente senza mai sollevare eccezioni: prima modificando la
        risposta; se il token dell'interazione è scaduto, scrivendo nel canale.
        """
        def make_file() -> Optional[discord.File]:
            return discord.File(io.BytesIO(audio), filename=filename) if audio else None

        kwargs: dict[str, Any] = {
            "content": content, "embed": embed, "allowed_mentions": discord.AllowedMentions.none(),
        }
        if audio:
            kwargs["attachments"] = [make_file()]
        if await self._edit(interaction, **kwargs):
            return

        channel = interaction.channel
        if channel is None:
            return
        try:
            await channel.send(
                content=content, embed=embed, file=make_file(),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as e:
            log.warning("Impossibile consegnare il brano: %s", e)

    @staticmethod
    def _filename(prompt: str, audio_format: str) -> str:
        slug = "".join(c if c.isalnum() else "-" for c in prompt.lower()).strip("-")
        slug = "-".join(part for part in slug.split("-") if part)[:40] or "brano"
        return f"ace-step-{slug}.{audio_format}"

    @app_commands.command(name="ace-step", description="Genera musica con l'AI (ACE-Step) da un prompt")
    @app_commands.describe(
        prompt="Descrivi la musica: genere, strumenti, mood (es. 'lofi hip hop, piano, rilassante')",
        durata=f"Durata in secondi (10-{MAX_SECONDS}). Se omessa: {MAX_SECONDS}",
        testo="Testo della canzone con [verse]/[chorus]. Se omesso lo scrive l'AI",
        lingua="Lingua del testo (default: italiano)",
        strumentale="Solo musica, senza testo",
    )
    @app_commands.choices(lingua=LANGUAGE_CHOICES)
    async def ace_step(
        self,
        interaction: discord.Interaction,
        prompt: app_commands.Range[str, 3, 500],
        durata: Optional[app_commands.Range[int, SERVER_MIN_SECONDS, MAX_SECONDS]] = None,
        testo: Optional[app_commands.Range[str, 1, 2000]] = None,
        lingua: Optional[str] = None,
        strumentale: bool = False,
    ) -> None:
        prompt = prompt.strip()
        if len(prompt) < 3:
            return await interaction.response.send_message("❌ Il prompt è troppo corto.", ephemeral=True)
        if strumentale and testo:
            return await interaction.response.send_message(
                "❌ `testo` e `strumentale` sono in contrasto: usane uno solo.", ephemeral=True
            )
        # Senza durata si usa il massimo
        seconds = self.config.max_seconds if durata is None else durata
        seconds = max(SERVER_MIN_SECONDS, min(seconds, self.config.max_seconds))
        language = lingua if lingua in LANGUAGES else self.config.default_language

        user_id = interaction.user.id
        if user_id in self._active_users:
            return await interaction.response.send_message(
                "⏳ Hai già una generazione in corso: aspetta che finisca.", ephemeral=True
            )
        if len(self._active_users) >= self.config.max_pending:
            return await interaction.response.send_message(
                "⏳ Troppe richieste in corso, riprova tra qualche minuto.", ephemeral=True
            )

        self._active_users.add(user_id)
        try:
            await interaction.response.defer(thinking=True)
            await self._generate(
                interaction, prompt, seconds, testo.strip() if testo else None, language, strumentale
            )
        finally:
            self._active_users.discard(user_id)

    def _lyrics_generator(self, lyrics: Optional[str], instrumental: bool) -> Optional[TextGenerator]:
        """Il provider LLM da usare, o None se il testo non va scritto (dato, strumentale o LLM disattivato)."""
        if instrumental or lyrics:
            return None
        return build_generator(self.config.llm, self._http())

    async def _prepare_lyrics(
        self,
        interaction: discord.Interaction,
        prompt: str,
        seconds: int,
        language: str,
        generator: TextGenerator,
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Scrive il testo con l'LLM. Restituisce (testo, nota): se l'LLM non è disponibile il testo è None
        e la nota spiega perché (il brano diventa strumentale invece di fallire).
        """
        await self._edit(interaction, content=f"✍️ Sto scrivendo il testo con l'AI (`{generator.label}`)...")
        writer = LyricsWriter(generator)
        try:
            # write() rilascia SEMPRE l'LLM: con Ollama lo scarica dalla VRAM prima di tornare
            return await writer.write(prompt, seconds, language), None
        except LLMError as e:
            log.info("Testo non generato (%s): %s", generator.label, e)
            return None, f"Non sono riuscito a scrivere il testo ({e}) Brano strumentale."
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Errore imprevisto nella scrittura del testo")
            return None, "Non sono riuscito a scrivere il testo. Brano strumentale."
        finally:
            await generator.close()

    async def _generate(
        self,
        interaction: discord.Interaction,
        prompt: str,
        seconds: int,
        lyrics: Optional[str],
        language: str,
        instrumental: bool,
    ) -> None:
        client = self._client()
        started = time.monotonic()
        generator = self._lyrics_generator(lyrics, instrumental)
        source: Optional[str] = "utente" if lyrics else None
        note: Optional[str] = None

        ahead = len(self._active_users) - 1
        if ahead > 0:
            await self._edit(
                interaction, content=f"⏳ In coda: {ahead} richiest{'a' if ahead == 1 else 'e'} prima della tua..."
            )

        async def write_lyrics() -> None:
            nonlocal lyrics, source, note
            lyrics, note = await self._prepare_lyrics(interaction, prompt, seconds, language, generator)
            source = "ai" if lyrics else None

        try:
            # Claude non usa la GPU locale: il testo si scrive prima e fuori dal lock, senza far aspettare nessuno
            if generator is not None and not generator.uses_local_gpu:
                await write_lyrics()

            async with self._gpu_lock:
                try:
                    # Ollama sì: va caricato e SCARICATO dentro il lock, prima che ACE-Step usi la GPU
                    if generator is not None and generator.uses_local_gpu:
                        await write_lyrics()

                    task_id, position = await client.submit(prompt, lyrics, seconds, language)
                    if position and position > 1:
                        await self._edit(
                            interaction, content=f"⏳ In coda sul server ACE-Step (posizione {position})..."
                        )

                    async def announce_running() -> None:
                        await self._edit(
                            interaction,
                            content="🎼 Sto componendo il brano... può volerci qualche minuto.",
                        )

                    details = await client.wait_for_result(task_id, on_running=announce_running)

                    file_ref = details.get("file")
                    if not isinstance(file_ref, str) or not file_ref:
                        raise AceStepError("Il server ACE-Step non ha restituito il file audio.")

                    limit = getattr(interaction.guild, "filesize_limit", 8 * 1024 * 1024)
                    audio = await client.download(file_ref, max_bytes=limit)
                except AceStepError as e:
                    log.info("ace-step: %s", e)
                    return await self._deliver(interaction, content=f"❌ {e}")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Errore imprevisto in /ace-step")
            return await self._deliver(
                interaction, content="❌ Errore imprevisto durante la generazione del brano."
            )

        ai_label = generator.label if source == "ai" and generator is not None else None
        await self._deliver(
            interaction,
            embed=self._result_embed(
                interaction, prompt, seconds, lyrics, source, ai_label, note, details,
                time.monotonic() - started,
            ),
            audio=audio,
            filename=self._filename(prompt, self.config.audio_format),
        )

    @staticmethod
    def _result_embed(
        interaction: discord.Interaction, prompt: str, seconds: int,
        lyrics: Optional[str], source: Optional[str], ai_label: Optional[str], note: Optional[str],
        details: dict, elapsed: float,
    ) -> discord.Embed:
        embed = discord.Embed(title="🎵 Musica generata", color=discord.Color.purple())
        if lyrics:
            # il testo può contenere * o _ : senza escape romperebbe la formattazione
            embed.description = re.sub(r"([*_`~|>\\])", r"\\\1", lyrics)[:4000]
        embed.add_field(name="Prompt", value=prompt[:1024], inline=False)
        metas = details.get("metas") if isinstance(details.get("metas"), dict) else {}
        if source == "ai":
            origin = f"testo scritto dall'AI ({ai_label})" if ai_label else "testo scritto dall'AI"
        else:
            origin = "con testo" if source == "utente" else "strumentale"
        info = [f"{seconds}s", origin]
        if metas.get("bpm"):
            info.append(f"{metas['bpm']} BPM")
        if metas.get("keyscale"):
            info.append(str(metas["keyscale"]))
        embed.add_field(name="Dettagli", value=" · ".join(info), inline=False)
        if note:
            embed.add_field(name="⚠️ Nota", value=note[:1024], inline=False)
        embed.add_field(name="Richiesto da", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"ACE-Step · generato in {elapsed:.0f}s")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AceStepMusic(bot))
