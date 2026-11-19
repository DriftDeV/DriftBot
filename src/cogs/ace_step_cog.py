"""
AI Music (/ai-music) — genera musica da un prompt di testo con il modello scelto dall'utente.

Modelli e livelli (ognuno ha il proprio backend, avviato dal bot solo per quella generazione):
    ACE-Step   veloce   ACE-Step 1.5 turbo su GPU (quello di sempre)
    ACE-Step   accurata ACE-Step 1.5 XL turbo (DiT da 4B) su CPU: non entra negli 8 GB di VRAM, minuti di attesa
    HeartMuLa  veloce   HeartMuLa 3B su GPU, in un venv a parte con un piccolo wrapper (heartmula_server.py)
Un solo backend alla volta: gli altri vengono spenti prima (VRAM e RAM non bastano per due).

Il resto di questo documento descrive ACE-Step 1.5, il backend di riferimento (HeartMuLa imita lo stesso contratto REST).

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

Se il server è spento e nella cartella sopra il repository del bot (o in ACESTEP_DIR) c'è ACE-Step,
il bot lo avvia da solo (`uv run acestep-api`, con il modello LM per brani più coerenti) prima di
generare. Il brano non viene allegato: il bot entra nella vocale di chi l'ha chiesto e lo riproduce
(il file si allega solo se la vocale non è utilizzabile).

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
  ACESTEP_DEFAULT_SECONDS   durata se omessa, default 100 (la fascia stabile di ACE-Step è 2-4 minuti, sotto va bene)
  ACESTEP_MAX_SECONDS       durata massima, default 300 (il server accetta fino a 600, ma oltre i 4 minuti la struttura si perde)
  ACESTEP_TIMEOUT           secondi massimi di attesa per una generazione, default 600
  ACESTEP_MAX_PENDING       richieste accettate contemporaneamente dal bot (in coda + in corso), default 5
  ACESTEP_XL_MODEL          DiT del livello "accurata", default acestep-v15-xl-turbo (da scaricare, ~19 GB su disco)
  ACESTEP_ACCURATE_PORT     porta del server ACE-Step "accurata", default 8002
  ACESTEP_ACCURATE_TIMEOUT  secondi massimi di attesa per un brano "accurata" (CPU), default 3600
  HEARTMULA_DIR             cartella di heartlib (con venv/ e ckpt/), default: la prima heartlib* accanto al repo
  HEARTMULA_PORT            porta del wrapper HeartMuLa, default 8003
  ACESTEP_DIR               cartella di ACE-Step da avviare in automatico, default: la prima ACE-Step* accanto al repo
  ACESTEP_STARTUP_TIMEOUT   secondi massimi per l'avvio del server (carica i modelli), default 300
  ACESTEP_LM_MODEL          modello LM 5Hz per brani coerenti (thinking), default acestep-5Hz-lm-0.6B (il server su 8 GB sceglie comunque lo 0.6B); vuoto = senza LM
  ACESTEP_AUDIO_FORMAT      mp3 (default), flac, opus, aac, wav
  ACESTEP_DEFAULT_LANGUAGE  lingua del testo se non indicata: it (default), en, es, fr, de, pt
  ANTHROPIC_API_KEY, CLAUDE_*, LYRICS_LLM_*   LLM che prepara il brano: vedi text_llm.py
"""

import asyncio
import io
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from cogs import escape_md
from cogs.playback import with_volume
from lyrics_llm import DEFAULT_LANGUAGE, LANGUAGES, LyricsWriter, Song
from text_llm import LLMConfig, LLMError, TextGenerator, build_generator

log = logging.getLogger(__name__)

SERVER_MIN_SECONDS = 10     # limiti del server ACE-Step
SERVER_MAX_SECONDS = 600
INSTRUMENTAL_LYRICS = "[Instrumental]"
EMBED_SAFE_LIMIT = 5800     # il massimo di Discord è 6000 caratteri per embed
ALLOWED_FORMATS = ("mp3", "flac", "opus", "aac", "wav")
MAX_AUDIO_BYTES = 64 * 1024 * 1024   # il brano resta in memoria: tetto di sicurezza (180s in flac ~30 MB)
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """Legge un intero dall'ambiente, tollerando valori assenti o non validi."""
    try:
        value = int(os.getenv(name, default))
    except (TypeError, ValueError):
        log.warning("%s non è un intero valido: uso %s", name, default)
        return default
    return max(minimum, min(maximum, value))


def _find_sibling(env_name: str, pattern: str) -> str:
    """`env_name`, oppure la prima cartella `pattern` (con pyproject.toml) accanto al repository del bot."""
    explicit = os.getenv(env_name, "").strip()
    if explicit:
        return explicit
    sibling_root = Path(__file__).resolve().parents[3]       # <repo>/src/cogs/file.py -> cartella sopra il repo
    found = next((d for d in sorted(sibling_root.glob(pattern)) if (d / "pyproject.toml").is_file()), None)
    return str(found) if found else ""


def find_server_dir() -> str:
    """ACESTEP_DIR, oppure la prima cartella ACE-Step* accanto al repository del bot."""
    return _find_sibling("ACESTEP_DIR", "ACE-Step*")


def find_heartmula_dir() -> str:
    """HEARTMULA_DIR, oppure la prima cartella heartlib* accanto al repository del bot."""
    return _find_sibling("HEARTMULA_DIR", "heartlib*")


HEARTMULA_WRAPPER = Path(__file__).resolve().parents[1] / "heartmula_server.py"


@dataclass(frozen=True)
class Backend:
    """Un modello a un livello: ognuno ha il proprio server (e porta). `model` decide il formato della richiesta."""
    key: str
    model: str            # "ace" | "heartmula"
    label: str
    default_seconds: int = 0           # 0 = quelli della configurazione
    max_seconds: int = 0
    wait_factor: float = 0.0           # secondi di attesa per secondo di musica (misurati), 0 = sconosciuto
    min_ram_gb: int = 0                # RAM libera necessaria (picco misurato): sotto, il sistema ucciderebbe il processo


BACKENDS: dict[tuple[str, str], Backend] = {
    ("ace", "veloce"): Backend("ace-veloce", "ace", "ACE-Step 1.5 turbo"),
    # Misurato: 30 s di musica in 226 s, picco 20 GB di RAM (DiT da 4B in fp32)
    ("ace", "accurata"): Backend("ace-accurata", "ace", "ACE-Step 1.5 XL (CPU)", min_ram_gb=21),
    # Misurato su RX 6600 (pesi INT8, fp16): ~0,33 s per passo = ~4 s di attesa per ogni secondo di musica, più ~30 s
    # fissi (codec) e ~2-3 minuti in più al primo brano dopo l'avvio del server (caricamento e quantizzazione).
    # Il picco di RAM (14 GB) è il caricamento del checkpoint fp32 prima della quantizzazione INT8
    ("heartmula", "veloce"): Backend("heartmula", "heartmula", "HeartMuLa 3B", 60, 120, 5.0, 15),
}
HEARTMULA_NOTE = (
    "HeartMuLa dichiara inglese, cinese, giapponese, coreano e spagnolo: in altre lingue la pronuncia può essere imprecisa."
)
HEARTMULA_LANGUAGES = ("en", "es")


@dataclass
class AceStepConfig:
    base_url: str = "http://127.0.0.1:8001"
    api_key: str = ""
    max_seconds: int = 300
    default_seconds: int = 100
    timeout: int = 600
    max_pending: int = 5
    audio_format: str = "mp3"
    poll_interval: float = 3.0
    server_dir: str = ""        # vuoto = nessun avvio automatico
    startup_timeout: int = 300
    lm_model: str = "acestep-5Hz-lm-0.6B"    # vuoto = niente LM (e niente thinking)
    xl_model: str = "acestep-v15-xl-turbo"   # DiT del livello "accurata"
    accurate_port: int = 8002
    accurate_timeout: int = 3600             # su CPU un brano richiede minuti
    heartmula_dir: str = ""                  # vuoto = HeartMuLa non disponibile
    heartmula_port: int = 8003
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
            max_seconds=_env_int("ACESTEP_MAX_SECONDS", 300, SERVER_MIN_SECONDS, SERVER_MAX_SECONDS),
            default_seconds=_env_int("ACESTEP_DEFAULT_SECONDS", 100, SERVER_MIN_SECONDS, SERVER_MAX_SECONDS),
            timeout=_env_int("ACESTEP_TIMEOUT", 600, 30, 3000),
            max_pending=_env_int("ACESTEP_MAX_PENDING", 5, 1, 50),
            audio_format=audio_format,
            server_dir=find_server_dir(),
            startup_timeout=_env_int("ACESTEP_STARTUP_TIMEOUT", 300, 30, 3000),
            lm_model=os.getenv("ACESTEP_LM_MODEL", cls.lm_model).strip(),
            xl_model=os.getenv("ACESTEP_XL_MODEL", cls.xl_model).strip() or cls.xl_model,
            accurate_port=_env_int("ACESTEP_ACCURATE_PORT", 8002, 1024, 65535),
            accurate_timeout=_env_int("ACESTEP_ACCURATE_TIMEOUT", 3600, 60, 36000),
            heartmula_dir=find_heartmula_dir(),
            heartmula_port=_env_int("HEARTMULA_PORT", 8003, 1024, 65535),
        )


# Il massimo della durata finisce nella definizione dello slash command: va letto all'import
# (main.py ha già caricato il .env). Il valore viene comunque riverificato a runtime.
MAX_SECONDS = AceStepConfig.from_env().max_seconds
DEFAULT_SECONDS = min(AceStepConfig.from_env().default_seconds, MAX_SECONDS)


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
        self, prompt: str, lyrics: Optional[str], seconds: int, language: str = DEFAULT_LANGUAGE,
        song: Optional[Song] = None, model: str = "ace",
    ) -> tuple[str, Optional[int]]:
        """
        Accoda una generazione. Restituisce (task_id, posizione in coda).
        `song` (scritto dall'LLM) porta la caption sonora e i metadati: così tempo, tonalità e metro
        sono coerenti con lo stile invece di essere scelti dal LM piccolo del server.
        """
        if model == "heartmula":
            # il wrapper di HeartMuLa capisce solo questi campi (caption -> tag di stile, testo, durata)
            body = {
                "prompt": song.caption if song and song.caption else prompt,
                "lyrics": lyrics or "",
                "audio_duration": seconds,
            }
            return await self._release(body)
        body = {
            # la caption deve descrivere il SUONO (genere, strumenti, voce): senza `song` resta la richiesta dell'utente
            "prompt": (song.caption if song and song.caption else prompt),
            "lyrics": lyrics or INSTRUMENTAL_LYRICS,
            "vocal_language": language,
            "audio_duration": seconds,
            "batch_size": 1,                       # un solo brano: più veloce e un solo file da inviare
            "audio_format": self.config.audio_format,
            "use_random_seed": True,
            "task_type": "text2music",
            # Coerenza: con `thinking` il LM 5Hz pianifica struttura e codici audio prima del DiT
            # (senza, il DiT improvvisa da solo e il brano si sfilaccia). 8 passi è il valore del modello turbo.
            # ponytail: temperatura LM 0.7 (default server 0.85) = meno fantasia, più coerenza; da tarare ad orecchio
            "thinking": bool(self.config.lm_model),
            "lm_temperature": 0.7,
            "inference_steps": 8,
            # il LM non deve riscrivere il prompt: provato, "lofi piano" diventava "folk-rock con chitarre"
            "use_cot_caption": False,
            "use_cot_language": False,             # la lingua è già nota: il LM la tirava a indovinare ("unknown")
        }
        if song:
            for field, value in (("bpm", song.bpm), ("key_scale", song.keyscale), ("time_signature", song.timesignature)):
                if value:
                    body[field] = value            # i valori forniti battono quelli scelti dal LM
        return await self._release(body)

    async def _release(self, body: dict) -> tuple[str, Optional[int]]:
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
            f"Il brano pesa {size / 1_000_000:.1f} MB, oltre il limite di {limit / 1_000_000:.0f} MB: "
            "prova con una durata più breve."
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


MODEL_CHOICES = [
    app_commands.Choice(name="ACE-Step (consigliato)", value="ace"),
    app_commands.Choice(name="HeartMuLa", value="heartmula"),
]
LEVEL_CHOICES = [
    app_commands.Choice(name="Veloce (GPU)", value="veloce"),
    app_commands.Choice(name="Accurata (lenta: su CPU)", value="accurata"),
]


class AceStepMusic(commands.Cog):
    """Genera musica da un prompt con il modello scelto, scrivendo il testo con un LLM se manca."""

    def __init__(self, bot: commands.Bot, config: Optional[AceStepConfig] = None):
        self.bot = bot
        self.config = config or AceStepConfig.from_env()
        self._session: Optional[aiohttp.ClientSession] = None
        self._active_users: set[int] = set()
        self._servers: dict[str, subprocess.Popen] = {}     # backend avviati da noi, per chiave (uno solo vivo)
        # Un solo lavoro GPU alla volta: LLM e ACE-Step non devono mai essere in VRAM insieme.
        # Pubblico: anche il TTS (/tts-ai) lo prende, perché i due modelli insieme non entrano in 8 GB.
        self.gpu_lock = asyncio.Lock()

    def _http(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _url(self, backend: Backend) -> str:
        cfg = self.config
        if backend.key == "ace-accurata":
            return f"http://127.0.0.1:{cfg.accurate_port}"
        if backend.key == "heartmula":
            return f"http://127.0.0.1:{cfg.heartmula_port}"
        return cfg.base_url

    def _client(self, backend: Backend = BACKENDS[("ace", "veloce")], seconds: Optional[int] = None) -> AceStepClient:
        cfg = replace(self.config, base_url=self._url(backend))
        if backend.key == "ace-accurata":
            cfg.timeout = self.config.accurate_timeout       # la CPU impiega minuti
        elif backend.wait_factor and seconds:
            cfg.timeout = max(cfg.timeout, int(seconds * backend.wait_factor * 1.5) + 600)
        return AceStepClient(cfg, self._http())

    @staticmethod
    def _free_ram_gb() -> float:
        """RAM disponibile in GB (/proc/meminfo)."""
        with open("/proc/meminfo") as meminfo:
            for line in meminfo:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1024 / 1024
        return float("inf")             # non Linux: non si controlla

    def _unavailable(self, backend: Backend) -> Optional[str]:
        """Messaggio per l'utente se `backend` non è installato su questo computer (None = ok)."""
        cfg = self.config
        if backend.key == "ace-accurata":
            if not cfg.server_dir:
                return "Il livello accurata richiede ACE-Step installato su questo computer."
            if not (Path(cfg.server_dir) / "checkpoints" / cfg.xl_model).is_dir():
                return (f"Il livello accurata richiede il modello `{cfg.xl_model}` (~19 GB su disco): "
                        "va scaricato, vedi il README.")
        if backend.key == "heartmula":
            root = Path(cfg.heartmula_dir) if cfg.heartmula_dir else None
            if root is None or not (root / "venv" / "bin" / "python").is_file() or not (root / "ckpt").is_dir():
                return "HeartMuLa non è installato su questo computer: vedi il README."
        return None

    async def release_gpu(self, keep: Optional[str] = None) -> None:
        """
        Spegne i server avviati da questo bot (tutti, tranne `keep`) per liberare VRAM e RAM: la chiede il TTS e
        un altro backend. Riparte da solo al prossimo /ai-music. Chi chiama deve già tenere `gpu_lock`.
        """
        for key in [k for k in self._servers if k != keep]:
            proc = self._servers.pop(key)
            if proc.poll() is None:
                proc.terminate()
                try:
                    await asyncio.to_thread(proc.wait, 30)
                except subprocess.TimeoutExpired:
                    proc.kill()

    async def cog_unload(self) -> None:
        await self.release_gpu()        # i server non devono restare orfani a tenere la VRAM
        if self._session is not None and not self._session.closed:
            await self._session.close()

    def _launch_spec(self, backend: Backend, port: int):
        """(comando, cartella, ambiente, file di log) per avviare `backend`, o None se non si può."""
        cfg = self.config
        env = {**os.environ}
        if backend.model == "heartmula":
            root = Path(cfg.heartmula_dir)
            env.update({"HEARTMULA_CKPT": str(root / "ckpt")})
            env.setdefault("PYTORCH_HIP_ALLOC_CONF", "expandable_segments:True")
            python = root / "venv" / "bin" / "python"
            return [str(python), str(HEARTMULA_WRAPPER), "--port", str(port)], str(root), env, root / "heartmula-api.log"

        if not cfg.server_dir:
            return None
        args = ["--host", "127.0.0.1", "--port", str(port)]
        if cfg.lm_model:
            args += ["--init-llm", "--lm-model-path", cfg.lm_model]
        if cfg.api_key:
            env["ACESTEP_API_KEY"] = cfg.api_key
        log_name = "acestep-api.log"
        if backend.key == "ace-accurata":
            # DiT da 4B (~9 GB in bf16): non entra negli 8 GB di VRAM, quindi gira su CPU (fp32, ~16 GB di RAM)
            env.update({"ACESTEP_CONFIG_PATH": cfg.xl_model, "ACESTEP_DEVICE": "cpu"})
            log_name = "acestep-api-xl.log"
        rocm_python = Path(cfg.server_dir) / "venv_rocm" / "bin" / "python"
        if rocm_python.is_file():
            # Il .venv di uv ha torch CUDA (NVIDIA): su AMD girerebbe su CPU. venv_rocm ha torch ROCm
            # (setup ufficiale ACE-Step); `uv run` lo ricreerebbe da zero, quindi si lancia il suo python.
            # HSA_OVERRIDE_GFX_VERSION (scheda RDNA2/3) arriva dal .env del bot.
            # stesso entry point di `acestep-api`; `-m acestep.api_server` caricherebbe il modulo due volte
            cmd = [str(rocm_python), "-c", "from acestep.api_server import main; main()", *args]
            env.setdefault("ACESTEP_LM_BACKEND", "pt")       # vllm non c'è su ROCm
            env.setdefault("MIOPEN_FIND_MODE", "FAST")       # senza, il VAE resta minuti fermo al primo uso
            # su ROCm il default è float32: il modello musicale da solo riempie gli 8 GB e va in OOM
            env.setdefault("ACESTEP_ROCM_DTYPE", "bfloat16")
            env.setdefault("PYTORCH_HIP_ALLOC_CONF", "expandable_segments:True")
        elif uv := shutil.which("uv"):
            cmd = [uv, "run", "acestep-api", *args]
        else:
            return None
        return cmd, cfg.server_dir, env, Path(cfg.server_dir) / log_name

    async def _ensure_server(
        self, client: AceStepClient, interaction: discord.Interaction, backend: Backend = BACKENDS[("ace", "veloce")]
    ) -> None:
        """
        Spegne gli altri backend avviati dal bot, poi, se quello scelto non risponde e sta su questo computer,
        lo avvia e aspetta che sia pronto. Se non si può avviare non solleva nulla: ci pensa l'errore
        "non raggiungibile" della richiesta.
        """
        await self.release_gpu(keep=backend.key)
        if await client.health():
            return
        cfg = self.config
        free = self._free_ram_gb()
        if backend.min_ram_gb and free < backend.min_ram_gb and backend.key not in self._servers:
            raise AceStepError(
                f"{backend.label} ha bisogno di ~{backend.min_ram_gb} GB di RAM libera e ora ce ne sono {free:.0f}: "
                "chiudi qualcosa e riprova."
            )
        url = urlparse(client.config.base_url)
        proc = self._servers.get(backend.key)
        if proc is None or proc.poll() is not None:
            spec = self._launch_spec(backend, url.port or 8001) if url.hostname in LOCAL_HOSTS else None
            if spec is None:
                return
            cmd, cwd, env, logpath = spec
            try:
                with open(logpath, "ab") as logfile:
                    proc = self._servers[backend.key] = subprocess.Popen(
                        cmd, cwd=cwd, env=env, stdout=logfile, stderr=subprocess.STDOUT,
                        start_new_session=True,     # niente Ctrl+C del terminale; lo spegne release_gpu()
                    )
            except OSError as e:
                log.warning("Avvio di %s non riuscito: %s", backend.label, e)
                return
            log.info("%s avviato da %s (pid %s)", backend.label, cwd, proc.pid)
        await self._edit(
            interaction, content=f"🚀 Avvio {backend.label} (carica i modelli: può volerci qualche minuto)..."
        )

        loop = asyncio.get_running_loop()
        deadline = loop.time() + cfg.startup_timeout
        while not await client.health():
            if proc.poll() is not None:
                raise AceStepError(f"{backend.label} si è chiuso all'avvio (vedi il suo file .log).")
            if loop.time() >= deadline:
                raise AceStepError(f"{backend.label} non è pronto dopo {cfg.startup_timeout}s (sta ancora caricando?).")
            await asyncio.sleep(max(self.config.poll_interval, 0.01))

    async def _start_playback(self, interaction: discord.Interaction, audio: bytes):
        """
        Entra nella vocale dell'utente e fa partire il brano.
        Restituisce (voice client, evento di fine, canale, già connesso prima?) oppure None se non si può
        (utente uscito dalla vocale, bot già occupato con altro audio, connessione rifiutata).
        """
        guild = interaction.guild
        member = guild.get_member(interaction.user.id) or interaction.user    # stato vocale aggiornato
        channel = member.voice.channel if member.voice else None
        if channel is None:
            return None
        vc = guild.voice_client
        joined = vc is None
        try:
            if vc is None:
                vc = await channel.connect()
            elif vc.is_playing() or vc.is_paused():
                return None
            elif vc.channel != channel:
                await vc.move_to(channel)
            loop = asyncio.get_running_loop()
            done = asyncio.Event()

            def after(error):
                if error:
                    log.error("Errore di riproduzione ACE-Step: %s", error)
                loop.call_soon_threadsafe(done.set)

            source = with_volume(self.bot, guild.id, discord.FFmpegPCMAudio(io.BytesIO(audio), pipe=True))
            vc.play(source, after=after)
        except Exception:
            log.exception("Impossibile riprodurre il brano in vocale")
            if joined and vc is not None:
                await vc.disconnect()
            return None
        return vc, done, channel, joined

    @staticmethod
    async def _finish_playback(vc, done: asyncio.Event, joined: bool, seconds: int) -> None:
        """Aspetta la fine del brano; se il bot era entrato apposta, esce (a meno che altri abbiano preso la voce)."""
        try:
            await asyncio.wait_for(done.wait(), seconds + 60)
        except asyncio.TimeoutError:
            vc.stop()
        except asyncio.CancelledError:
            vc.stop()
            raise
        if joined and vc.is_connected() and not (vc.is_playing() or vc.is_paused()):
            await vc.disconnect()

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
        # Il token è scaduto (coda lunga): il risultato va nel canale e, siccome un embed non notifica,
        # si cita chi lo aveva chiesto (solo lui: nessun'altra menzione è ammessa).
        mention = interaction.user.mention
        try:
            await channel.send(
                content=f"{mention} {content}" if content else mention, embed=embed, file=make_file(),
                allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[interaction.user]),
            )
        except discord.HTTPException as e:
            log.warning("Impossibile consegnare il brano: %s", e)

    @staticmethod
    def _filename(prompt: str, audio_format: str) -> str:
        slug = "".join(c if c.isalnum() else "-" for c in prompt.lower()).strip("-")
        slug = "-".join(part for part in slug.split("-") if part)[:40] or "brano"
        return f"ace-step-{slug}.{audio_format}"

    @app_commands.command(name="ai-music", description="Genera musica con l'AI e la riproduce nella tua vocale")
    @app_commands.guild_only()
    @app_commands.describe(
        prompt="Descrivi la musica: genere, strumenti, mood (es. 'lofi hip hop, piano, rilassante')",
        modello="Il modello che compone il brano",
        livello="Veloce (GPU, un minuto) o accurata (più lenta, su CPU: solo ACE-Step)",
        durata=f"Durata in secondi (10-{MAX_SECONDS}; HeartMuLa max 120). Se omessa: {DEFAULT_SECONDS} (HeartMuLa: 60)",
        testo="Testo della canzone con [verse]/[chorus]. Se omesso lo scrive l'AI",
        lingua="Lingua del testo (default: italiano)",
        strumentale="Solo musica, senza testo",
    )
    @app_commands.choices(lingua=LANGUAGE_CHOICES, modello=MODEL_CHOICES, livello=LEVEL_CHOICES)
    async def ai_music(
        self,
        interaction: discord.Interaction,
        prompt: app_commands.Range[str, 3, 500],
        modello: str,
        durata: Optional[app_commands.Range[int, SERVER_MIN_SECONDS, MAX_SECONDS]] = None,
        testo: Optional[app_commands.Range[str, 1, 2000]] = None,
        lingua: Optional[str] = None,
        strumentale: bool = False,
        livello: str = "veloce",
    ) -> None:
        prompt = prompt.strip()
        if len(prompt) < 3:
            return await interaction.response.send_message("❌ Il prompt è troppo corto.", ephemeral=True)
        if strumentale and testo:
            return await interaction.response.send_message(
                "❌ `testo` e `strumentale` sono in contrasto: usane uno solo.", ephemeral=True
            )
        backend = BACKENDS.get((modello, livello))
        if backend is None:
            return await interaction.response.send_message(
                f"❌ {modello} ha un solo livello (veloce): scegli quello.", ephemeral=True
            )
        if backend.model == "heartmula" and strumentale:
            return await interaction.response.send_message(
                "❌ HeartMuLa canta sempre: per un brano strumentale scegli ACE-Step.", ephemeral=True
            )
        if (problem := self._unavailable(backend)) is not None:
            return await interaction.response.send_message(f"❌ {problem}", ephemeral=True)
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            return await interaction.response.send_message(
                "❌ Entra prima in un canale vocale: il brano lo riproduco lì.", ephemeral=True
            )
        default = backend.default_seconds or self.config.default_seconds
        seconds = default if durata is None else durata
        seconds = max(SERVER_MIN_SECONDS, min(seconds, backend.max_seconds or self.config.max_seconds))
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
            try:
                await interaction.response.defer(thinking=True)
            except discord.NotFound:
                # Interazione scaduta (>3s prima del defer): nessuno ascolta più, inutile generare.
                log.warning("/ai-music: interazione scaduta prima del defer (user %s)", user_id)
                return
            await self._generate(
                interaction, prompt, seconds, testo.strip() if testo else None, language, strumentale, backend
            )
        finally:
            self._active_users.discard(user_id)

    def _lyrics_generator(self, instrumental: bool) -> Optional[TextGenerator]:
        """Il provider LLM da usare, o None se non serve (strumentale) o se l'LLM è disattivato."""
        if instrumental:
            return None
        return build_generator(self.config.llm, self._http())

    async def _prepare_lyrics(
        self,
        interaction: discord.Interaction,
        prompt: str,
        seconds: int,
        language: str,
        generator: TextGenerator,
        user_lyrics: Optional[str] = None,
    ) -> tuple[Optional[Song], Optional[str]]:
        """
        Con il testo dell'utente: caption, metadati e tag di sezione (le parole non cambiano).
        Senza: scrive anche il testo. Restituisce (song, nota): se l'LLM non è disponibile song è None e la
        nota spiega perché (senza testo dell'utente il brano diventa strumentale invece di fallire).
        """
        what = "caption e metadati" if user_lyrics else "il testo"
        fallback = "Uso il tuo prompt come descrizione." if user_lyrics else "Brano strumentale."
        await self._edit(interaction, content=f"✍️ Sto preparando {what} con l'AI (`{generator.label}`)...")
        writer = LyricsWriter(generator)
        try:
            # write_song()/annotate() rilasciano SEMPRE l'LLM: con Ollama lo scarica dalla VRAM prima di tornare
            if user_lyrics:
                return await writer.annotate(prompt, user_lyrics, seconds), None
            return await writer.write_song(prompt, seconds, language), None
        except LLMError as e:
            log.info("Preparazione con l'LLM fallita (%s): %s", generator.label, e)
            return None, f"Non sono riuscito a preparare {what} ({e}) {fallback}"
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Errore imprevisto con l'LLM")
            return None, f"Non sono riuscito a preparare {what}. {fallback}"
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
        backend: Backend = BACKENDS[("ace", "veloce")],
    ) -> None:
        client = self._client(backend, seconds)
        started = time.monotonic()
        generator = self._lyrics_generator(instrumental)
        source: Optional[str] = "utente" if lyrics else None
        note: Optional[str] = None
        song: Optional[Song] = None

        ahead = len(self._active_users) - 1
        if ahead > 0:
            await self._edit(
                interaction, content=f"⏳ In coda: {ahead} richiest{'a' if ahead == 1 else 'e'} prima della tua..."
            )

        async def write_lyrics() -> None:
            nonlocal lyrics, source, note, song
            song, note = await self._prepare_lyrics(interaction, prompt, seconds, language, generator, lyrics)
            if lyrics is None:                      # testo scritto dall'AI
                lyrics = song.lyrics if song else None
                source = "ai" if lyrics else None
            elif song:                              # testo dell'utente: stesse parole, con i tag di sezione
                lyrics = song.lyrics

        try:
            # Claude non usa la GPU locale: il testo si scrive prima e fuori dal lock, senza far aspettare nessuno
            if generator is not None and not generator.uses_local_gpu:
                await write_lyrics()

            async with self.gpu_lock:
                try:
                    # Ollama sì: va caricato e SCARICATO dentro il lock, prima che ACE-Step usi la GPU
                    if generator is not None and generator.uses_local_gpu:
                        await write_lyrics()

                    # il modello TTS resta in VRAM per tutto il tempo: ACE-Step non ci starebbe (OOM)
                    tts = getattr(self.bot, "get_cog", lambda name: None)("TTSCog")
                    if tts is not None:
                        await tts.release_gpu()
                    await self._ensure_server(client, interaction, backend)
                    task_id, position = await client.submit(prompt, lyrics, seconds, language, song, backend.model)
                    if position and position > 1:
                        await self._edit(
                            interaction, content=f"⏳ In coda sul server ACE-Step (posizione {position})..."
                        )

                    async def announce_running() -> None:
                        await self._edit(
                            interaction,
                            content=f"🎼 Sto componendo con {backend.label}... "
                                    + ("su CPU richiede diversi minuti." if backend.key == "ace-accurata"
                                       else f"su questa GPU richiede circa {-(-int(seconds * backend.wait_factor + 30) // 60)} minuti (qualcuno in più al primo brano)."
                                       if backend.wait_factor else "può volerci qualche minuto."),
                        )

                    details = await client.wait_for_result(task_id, on_running=announce_running)

                    file_ref = details.get("file")
                    if not isinstance(file_ref, str) or not file_ref:
                        raise AceStepError("Il server ACE-Step non ha restituito il file audio.")

                    audio = await client.download(file_ref, max_bytes=MAX_AUDIO_BYTES)
                except AceStepError as e:
                    log.info("ace-step: %s", e)
                    return await self._deliver(interaction, content=f"❌ {e}")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Errore imprevisto in /ai-music")
            return await self._deliver(
                interaction, content="❌ Errore imprevisto durante la generazione del brano."
            )

        ai_label = generator.label if source == "ai" and generator is not None else None
        if backend.model == "heartmula" and language not in HEARTMULA_LANGUAGES:
            note = f"{note} {HEARTMULA_NOTE}" if note else HEARTMULA_NOTE
        embed = self._result_embed(
            interaction, prompt, seconds, lyrics, source, ai_label, note, details, time.monotonic() - started,
            backend.label,
        )
        playing = await self._start_playback(interaction, audio)
        if playing is None:
            # Vocale non utilizzabile: meglio il file che perdere il brano (se ci sta nel limite di Discord)
            limit = getattr(interaction.guild, "filesize_limit", 8 * 1024 * 1024)
            fits = len(audio) <= limit
            return await self._deliver(
                interaction, embed=embed, audio=audio if fits else None,
                content="⚠️ Non riesco a riprodurlo in vocale (sei uscito dal canale o sto suonando altro)."
                + ("" if fits else " Il file è troppo grande per Discord."),
                filename=self._filename(prompt, self.config.audio_format),
            )
        vc, done, channel, joined = playing
        await self._deliver(interaction, embed=embed, content=f"▶️ Riproduco in **{escape_md(channel.name)}**")
        await self._finish_playback(vc, done, joined, seconds)

    @staticmethod
    def _result_embed(
        interaction: discord.Interaction, prompt: str, seconds: int,
        lyrics: Optional[str], source: Optional[str], ai_label: Optional[str], note: Optional[str],
        details: dict, elapsed: float, label: str = "ACE-Step",
    ) -> discord.Embed:
        embed = discord.Embed(title="🎵 Musica generata", color=discord.Color.purple())
        if lyrics:
            # il testo può contenere * o _ : senza escape romperebbe la formattazione
            embed.description = escape_md(lyrics)[:4000]
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
        embed.set_footer(text=f"{label} · generato in {elapsed:.0f}s")
        # Discord rifiuta embed oltre 6000 caratteri in totale (e allora il brano non arriverebbe):
        # se serve si accorcia il testo, che è la parte più lunga
        overflow = len(embed) - EMBED_SAFE_LIMIT
        if overflow > 0 and embed.description:
            keep = max(0, len(embed.description) - overflow - 1)
            embed.description = embed.description[:keep].rstrip() + "…"
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AceStepMusic(bot))
