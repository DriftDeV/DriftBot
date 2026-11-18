"""
Generazione di testo con un LLM: Claude (API Anthropic) oppure Ollama in locale.

Un solo punto d'ingresso per tutti i compiti del bot che hanno bisogno di un LLM per scrivere testo:

    generator = build_generator(config, session)
    text = await generator.generate(system, user)
    await generator.release()          # solo Ollama: scarica il modello dalla VRAM

Scelta del provider (dal file .env):
  - se `ANTHROPIC_API_KEY` è presente  -> Claude (nessuna GPU locale usata, nessun modello da scaricare);
  - altrimenti                          -> Ollama in locale (flusso per GPU da 8 GB: il modello viene
                                           caricato, usato e SCARICATO dalla VRAM prima di altri lavori GPU);
  - `LYRICS_LLM_ENABLED=false`          -> nessun LLM.

Se la key c'è ma Claude non risponde il bot NON ripiega sul locale: sarebbe una sorpresa per la VRAM e
nasconderebbe una key sbagliata. Il chiamante decide come degradare (ACE-Step: brano strumentale).

Privacy: con la key presente il prompt dell'utente viene inviato ad Anthropic.

Configurazione:
  ANTHROPIC_API_KEY        key Anthropic. Se manca si usa Ollama
  CLAUDE_MODEL             default claude-opus-5-5 (per spendere molto meno: claude-haiku-5-5)
  CLAUDE_EFFORT            low (default) | medium | high | xhigh | max. Vuoto = non inviarlo (modelli vecchi)
  CLAUDE_TIMEOUT           secondi massimi per richiesta, default 120
  CLAUDE_REFUSAL_FALLBACK  true (default): se i classificatori di sicurezza rifiutano, la richiesta
                           viene ripetuta server-side su un altro modello
  ANTHROPIC_BASE_URL       facoltativo (proxy/gateway)
  LYRICS_LLM_ENABLED       true/false, default true
  LYRICS_LLM_URL           Ollama, default http://127.0.0.1:11434
  LYRICS_LLM_MODEL         Ollama, default qwen2.5:7b
  LYRICS_LLM_TIMEOUT       Ollama: secondi per caricare il modello e scrivere, default 180
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

log = logging.getLogger(__name__)

DEFAULT_CLAUDE_MODEL = "claude-opus-5-5"
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    """Errore atteso, con un messaggio già adatto a essere mostrato all'utente (mai chiavi o dettagli interni)."""


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, default))
    except ValueError:
        log.warning("%s non è un numero valido: uso %s", name, default)
        return default
    return max(minimum, min(maximum, value))


# ----------------------------------------------------------------------------- configurazione

@dataclass
class ClaudeConfig:
    api_key: str = ""
    model: str = DEFAULT_CLAUDE_MODEL
    effort: str = "low"
    timeout: float = 120
    max_tokens: int = 8000      # con il thinking sempre attivo deve coprire anche il ragionamento
    max_retries: int = 2        # l'SDK ripete da solo 429/5xx/errori di rete
    base_url: str = ""
    refusal_fallback: bool = True

    @classmethod
    def from_env(cls) -> "ClaudeConfig":
        effort = os.getenv("CLAUDE_EFFORT")
        if effort is None:
            effort = cls.effort
        else:
            effort = effort.strip().lower()
            if effort and effort not in EFFORT_LEVELS:
                log.warning("CLAUDE_EFFORT=%r non valido: uso %s", effort, cls.effort)
                effort = cls.effort
        return cls(
            api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
            model=os.getenv("CLAUDE_MODEL", "").strip() or DEFAULT_CLAUDE_MODEL,
            effort=effort,
            timeout=_env_float("CLAUDE_TIMEOUT", cls.timeout, 10, 600),
            base_url=os.getenv("ANTHROPIC_BASE_URL", "").strip(),
            refusal_fallback=_env_bool("CLAUDE_REFUSAL_FALLBACK", True),
        )


@dataclass
class OllamaConfig:
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b"
    timeout: float = 180
    unload_timeout: float = 30
    poll_interval: float = 0.5
    num_ctx: int = 2048        # contesto piccolo = meno VRAM per la KV cache
    num_predict: int = 1000    # token massimi in uscita (~2000 caratteri)

    @classmethod
    def from_env(cls) -> "OllamaConfig":
        return cls(
            base_url=os.getenv("LYRICS_LLM_URL", "").strip().rstrip("/") or cls.base_url,
            model=os.getenv("LYRICS_LLM_MODEL", "").strip() or cls.model,
            timeout=_env_float("LYRICS_LLM_TIMEOUT", cls.timeout, 10, 1800),
        )


@dataclass
class LLMConfig:
    enabled: bool = True
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    claude: ClaudeConfig = field(default_factory=ClaudeConfig)

    @property
    def provider(self) -> Optional[str]:
        """'claude' se c'è la key, 'ollama' altrimenti, None se l'LLM è disattivato."""
        if not self.enabled:
            return None
        return "claude" if self.claude.api_key else "ollama"

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            enabled=_env_bool("LYRICS_LLM_ENABLED", True),
            ollama=OllamaConfig.from_env(),
            claude=ClaudeConfig.from_env(),
        )


# ------------------------------------------------------------------------------- interfaccia

class TextGenerator:
    """Interfaccia comune dei provider."""

    label: str = ""                 # nome mostrato all'utente
    uses_local_gpu: bool = False    # True = occupa la VRAM locale (va serializzato con gli altri lavori GPU)

    async def generate(self, system: str, user: str) -> str:
        raise NotImplementedError

    async def release(self) -> None:
        """Libera le risorse locali dopo l'uso (Ollama: scarica il modello dalla VRAM). Non solleva mai."""

    async def close(self) -> None:
        """Chiude le connessioni. Non solleva mai."""


def build_generator(config: LLMConfig, session: aiohttp.ClientSession) -> Optional[TextGenerator]:
    provider = config.provider
    if provider == "claude":
        return ClaudeGenerator(config.claude)
    if provider == "ollama":
        return OllamaGenerator(config.ollama, session)
    return None


# ----------------------------------------------------------------------------------- Claude

# Se il server rifiuta il parametro `fallbacks` (beta non disponibile per questo account) smettiamo
# di inviarlo per il resto della vita del processo, invece di fallire ogni richiesta.
_fallbacks_unsupported = False


def reset_fallback_state() -> None:
    global _fallbacks_unsupported
    _fallbacks_unsupported = False


def _import_anthropic():
    """L'SDK è opzionale: senza, il bot parte lo stesso e l'errore è un messaggio chiaro."""
    try:
        import anthropic
    except ImportError as e:
        raise LLMError("La libreria `anthropic` non è installata (`pip install anthropic`).") from e
    return anthropic


class ClaudeGenerator(TextGenerator):
    """Claude via SDK ufficiale `anthropic` (asincrono). Nessuna GPU locale."""

    uses_local_gpu = False

    def __init__(self, config: ClaudeConfig):
        self.config = config
        self.label = f"Claude {config.model}"
        self._client = None

    def _get_client(self):
        if self._client is None:
            anthropic = _import_anthropic()
            kwargs = {
                "api_key": self.config.api_key,
                "timeout": self.config.timeout,
                "max_retries": self.config.max_retries,
            }
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                log.debug("Chiusura del client Anthropic non riuscita", exc_info=True)
            self._client = None

    async def _create(self, client, kwargs: dict):
        """Chiama l'API, con il fallback lato server sui rifiuti dei classificatori di sicurezza."""
        global _fallbacks_unsupported
        anthropic = _import_anthropic()

        if self.config.refusal_fallback and not _fallbacks_unsupported:
            try:
                return await client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **kwargs
                )
            except anthropic.BadRequestError as e:
                text = str(getattr(e, "message", e)).lower()
                if "fallback" not in text and "beta" not in text:
                    raise                      # un 400 per altri motivi: non c'entra con i fallback
                log.warning("Fallback lato server non disponibile per questo account: lo disattivo (%s)", e)
                _fallbacks_unsupported = True
        return await client.messages.create(**kwargs)

    async def generate(self, system: str, user: str) -> str:
        anthropic = _import_anthropic()
        client = self._get_client()
        # Niente temperature/top_p: su Opus 5.5 e Haiku 5.5 un valore non predefinito dà errore 400.
        # Il thinking è sempre attivo su Opus 5.5: non si invia `thinking`, si regola `effort`.
        kwargs = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if self.config.effort:
            kwargs["output_config"] = {"effort": self.config.effort}

        try:
            response = await self._create(client, kwargs)
        except anthropic.AuthenticationError as e:
            raise LLMError("La API key di Claude non è valida o è scaduta.") from e
        except anthropic.PermissionDeniedError as e:
            raise LLMError("La API key di Claude non ha i permessi necessari.") from e
        except anthropic.NotFoundError as e:
            raise LLMError(f"Il modello Claude `{self.config.model}` non esiste o non è disponibile.") from e
        except anthropic.RateLimitError as e:
            raise LLMError("Limite di richieste a Claude raggiunto, riprova tra poco.") from e
        except anthropic.BadRequestError as e:
            detail = str(getattr(e, "message", e))
            log.warning("Claude ha rifiutato la richiesta (400): %s", detail)
            if "credit balance" in detail.lower():
                raise LLMError("Il credito Anthropic è esaurito.") from e
            raise LLMError("Claude ha rifiutato la richiesta (impostazioni del modello non valide?).") from e
        except anthropic.APITimeoutError as e:          # sottoclasse di APIConnectionError: va prima
            raise LLMError("Claude non ha risposto in tempo.") from e
        except anthropic.APIConnectionError as e:
            raise LLMError("Claude non è raggiungibile (problema di rete?).") from e
        except anthropic.APIStatusError as e:
            log.warning("Errore API Claude: HTTP %s", getattr(e, "status_code", "?"))
            raise LLMError("Il servizio Claude è temporaneamente non disponibile.") from e

        if response.stop_reason == "refusal":
            raise LLMError("Claude ha rifiutato di scrivere questo testo.")
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        if not text.strip():
            if response.stop_reason == "max_tokens":
                raise LLMError("Claude ha esaurito i token prima di scrivere il testo.")
            raise LLMError("Claude non ha restituito nessun testo.")
        return text


# ----------------------------------------------------------------------------------- Ollama

def _normalize_model_name(name: str) -> str:
    name = name.strip().lower()
    return name if ":" in name else f"{name}:latest"


class OllamaGenerator(TextGenerator):
    """
    Ollama in locale. Pensato per GPU da 8 GB: la richiesta usa `keep_alive: 0` (Ollama scarica il
    modello subito dopo la risposta) e `release()` verifica con GET /api/ps che sia davvero uscito
    dalla VRAM, inviando un unload esplicito se serve.
    """

    uses_local_gpu = True

    def __init__(self, config: OllamaConfig, session: aiohttp.ClientSession):
        self.config = config
        self.session = session
        self.label = config.model

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    async def generate(self, system: str, user: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "keep_alive": 0,          # scarica il modello subito dopo la risposta
            "options": {
                "temperature": 0.9,
                "num_ctx": self.config.num_ctx,
                "num_predict": self.config.num_predict,
            },
        }
        try:
            async with self.session.post(
                self._url("/api/chat"), json=payload,
                timeout=aiohttp.ClientTimeout(total=self.config.timeout),
            ) as response:
                if response.status == 404:
                    raise LLMError(
                        f"Modello `{self.config.model}` non trovato in Ollama "
                        f"(`ollama pull {self.config.model}`)."
                    )
                if response.status >= 400:
                    detail = (await response.text())[:200]
                    log.warning("Ollama HTTP %s: %s", response.status, detail)
                    raise LLMError(f"Ollama ha risposto con un errore (HTTP {response.status}).")
                try:
                    data = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, ValueError) as e:
                    raise LLMError("Risposta non valida da Ollama.") from e
        except aiohttp.ClientConnectorError as e:
            raise LLMError("Ollama non è raggiungibile (è avviato?).") from e
        except asyncio.TimeoutError as e:
            raise LLMError("Ollama non ha risposto in tempo.") from e
        except aiohttp.ClientError as e:
            log.warning("Errore di rete verso Ollama: %s", e)
            raise LLMError("Errore di comunicazione con Ollama.") from e

        message = data.get("message") if isinstance(data, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise LLMError("Il modello non ha restituito nessun testo.")
        return content

    async def _is_loaded(self) -> Optional[bool]:
        """True/False se il modello è in memoria; None se non si riesce a saperlo."""
        try:
            async with self.session.get(
                self._url("/api/ps"), timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
            return None
        models = data.get("models") if isinstance(data, dict) else None
        if not isinstance(models, list):
            return None
        wanted = _normalize_model_name(self.config.model)
        for item in models:
            if not isinstance(item, dict):
                continue
            for key in ("name", "model"):
                value = item.get(key)
                if isinstance(value, str) and _normalize_model_name(value) == wanted:
                    return True
        return False

    async def _send_unload(self) -> None:
        try:
            async with self.session.post(
                self._url("/api/chat"),
                json={"model": self.config.model, "messages": [], "keep_alive": 0},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            log.debug("Unload esplicito non riuscito: %s", e)

    async def ensure_unloaded(self) -> bool:
        """
        Attende che il modello non sia più in VRAM (inviando un unload esplicito se serve).
        Non solleva mai. True = scaricato (o impossibile da verificare), False = ancora in memoria.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.unload_timeout
        sent = False
        while True:
            loaded = await self._is_loaded()
            if loaded is not True:
                return True
            if not sent:
                sent = True
                await self._send_unload()
            if loop.time() >= deadline:
                log.warning("Il modello %s risulta ancora in memoria dopo %ss",
                            self.config.model, self.config.unload_timeout)
                return False
            await asyncio.sleep(self.config.poll_interval)

    async def release(self) -> None:
        await self.ensure_unloaded()
