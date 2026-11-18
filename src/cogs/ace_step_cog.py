"""
ACE-Step cog — genera musica da un prompt di testo con ACE-Step 1.5.

Il cog NON carica il modello nel processo del bot: parla con il server REST di ACE-Step
(`acestep-api`) che gira a parte. Motivi:
  - nessun conflitto di dipendenze con chatterbox/RVC (torch, transformers),
  - il bot non si blocca durante la generazione e non tiene la VRAM occupata,
  - CUDA (NVIDIA) o ROCm (AMD) li gestisce l'installazione del server, non il bot.

Contratto usato (documentazione ACE-Step 1.5, docs/en/API.md):
  POST /release_task   {prompt, lyrics, audio_duration, ...}  -> data.task_id
  POST /query_result   {task_id_list: [...]}                 -> data[].status 0=in corso 1=ok 2=fallito
  GET  /v1/audio?path=...                                    -> file audio
Ogni risposta JSON ha la busta {data, code, error, timestamp, extra}.

Configurazione (file .env):
  ACESTEP_API_URL       default http://127.0.0.1:8001
  ACESTEP_API_KEY       opzionale (header Authorization: Bearer)
  ACESTEP_MAX_SECONDS   durata massima richiedibile, default 180 (il server accetta fino a 600)
  ACESTEP_TIMEOUT       secondi massimi di attesa per una generazione, default 600
  ACESTEP_MAX_PENDING   richieste contemporanee accettate dal bot, default 5
  ACESTEP_AUDIO_FORMAT  mp3 (default), flac, opus, aac, wav
"""

import asyncio
import io
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

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

    @classmethod
    def from_env(cls) -> "AceStepConfig":
        audio_format = os.getenv("ACESTEP_AUDIO_FORMAT", "mp3").strip().lower()
        if audio_format not in ALLOWED_FORMATS:
            log.warning("ACESTEP_AUDIO_FORMAT=%r non valido: uso mp3", audio_format)
            audio_format = "mp3"
        return cls(
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

    async def submit(self, prompt: str, lyrics: Optional[str], seconds: int) -> tuple[str, Optional[int]]:
        """Accoda una generazione. Restituisce (task_id, posizione in coda)."""
        body = {
            "prompt": prompt,
            "lyrics": lyrics or INSTRUMENTAL_LYRICS,
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

class AceStepMusic(commands.Cog):
    """Genera musica da un prompt con ACE-Step."""

    def __init__(self, bot: commands.Bot, config: Optional[AceStepConfig] = None):
        self.bot = bot
        self.config = config or AceStepConfig.from_env()
        self._session: Optional[aiohttp.ClientSession] = None
        self._active_users: set[int] = set()

    def _client(self) -> AceStepClient:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return AceStepClient(self.config, self._session)

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
        durata=f"Durata in secondi (10-{MAX_SECONDS}, default 30)",
        testo="Testo della canzone con [verse]/[chorus] (vuoto = strumentale)",
    )
    async def ace_step(
        self,
        interaction: discord.Interaction,
        prompt: app_commands.Range[str, 3, 500],
        durata: app_commands.Range[int, SERVER_MIN_SECONDS, MAX_SECONDS] = 30,
        testo: Optional[app_commands.Range[str, 1, 2000]] = None,
    ) -> None:
        prompt = prompt.strip()
        if len(prompt) < 3:
            return await interaction.response.send_message("❌ Il prompt è troppo corto.", ephemeral=True)
        durata = max(SERVER_MIN_SECONDS, min(durata, self.config.max_seconds))

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
            await self._generate(interaction, prompt, durata, testo.strip() if testo else None)
        finally:
            self._active_users.discard(user_id)

    async def _generate(
        self, interaction: discord.Interaction, prompt: str, seconds: int, lyrics: Optional[str]
    ) -> None:
        client = self._client()
        started = time.monotonic()
        try:
            task_id, position = await client.submit(prompt, lyrics, seconds)
            if position and position > 1:
                await self._edit(interaction, content=f"⏳ In coda sul server ACE-Step (posizione {position})...")

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

        await self._deliver(
            interaction,
            embed=self._result_embed(interaction, prompt, seconds, lyrics, details, time.monotonic() - started),
            audio=audio,
            filename=self._filename(prompt, self.config.audio_format),
        )

    @staticmethod
    def _result_embed(
        interaction: discord.Interaction, prompt: str, seconds: int,
        lyrics: Optional[str], details: dict, elapsed: float,
    ) -> discord.Embed:
        embed = discord.Embed(title="🎵 Musica generata", color=discord.Color.purple())
        embed.add_field(name="Prompt", value=prompt[:1024], inline=False)
        metas = details.get("metas") if isinstance(details.get("metas"), dict) else {}
        info = [f"{seconds}s", "con testo" if lyrics else "strumentale"]
        if metas.get("bpm"):
            info.append(f"{metas['bpm']} BPM")
        if metas.get("keyscale"):
            info.append(str(metas["keyscale"]))
        embed.add_field(name="Dettagli", value=" · ".join(info), inline=False)
        embed.add_field(name="Richiesto da", value=interaction.user.mention, inline=True)
        embed.set_footer(text=f"ACE-Step · generato in {elapsed:.0f}s")
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AceStepMusic(bot))
