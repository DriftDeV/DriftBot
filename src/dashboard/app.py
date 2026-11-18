"""
Dashboard web del bot (aiohttp): gestione di soundboard, voci clonate e modelli RVC senza toccare i file.

Sicurezza (la dashboard può caricare ed eliminare file, quindi è trattata come un pannello di amministrazione):
- password obbligatoria (`DASHBOARD_PASSWORD`, almeno 8 caratteri) e in ascolto di default solo su 127.0.0.1;
- sessione in cookie HttpOnly + SameSite=Strict, token CSRF obbligatorio su ogni richiesta che modifica;
- limite ai tentativi di login, confronto password a tempo costante;
- upload in streaming con limiti di dimensione, controllo del formato dal CONTENUTO del file e nomi dei
  file generati dal server (mai quelli dell'utente);
- intestazioni di sicurezza (CSP senza script esterni, nosniff, no-store sulle API).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

from aiohttp import web

import cogs
import storage
from database import Database, DatabaseBusy, DatabaseClosed

from .auth import LoginLimiter, SessionStore, password_matches, tokens_match

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"
COOKIE = "driftbot_session"
MIN_PASSWORD_LENGTH = 8
MAX_FIELD_BYTES = 8 * 1024          # campo testuale di un form multipart
UPLOAD_CHUNK = 256 * 1024
ACTOR = "dashboard"
AUDIO_TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "flac": "audio/flac", "m4a": "audio/mp4"}

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data: https://cdn.discordapp.com; "
        "media-src 'self'; connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}


class ConfigError(Exception):
    """Configurazione della dashboard non valida (messaggio adatto ai log)."""


@dataclass
class DashboardConfig:
    password: str
    host: str = "127.0.0.1"
    port: int = 8080
    cookie_secure: bool = False       # metti True se la dashboard è dietro HTTPS (reverse proxy)
    trust_proxy: bool = False         # usa X-Forwarded-For per l'IP nel limite dei login (solo dietro un proxy tuo)
    session_ttl: float = 8 * 3600
    fail_delay: float = 0.4           # pausa dopo una password sbagliata
    max_failures: int = 5
    lockout: float = 300
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "DashboardConfig":
        env = os.environ if env is None else env
        password = env.get("DASHBOARD_PASSWORD", "")
        if not password:
            raise ConfigError("DASHBOARD_PASSWORD non impostata: la dashboard resta disattivata.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ConfigError(f"DASHBOARD_PASSWORD troppo corta (minimo {MIN_PASSWORD_LENGTH} caratteri).")
        try:
            port = int(env.get("DASHBOARD_PORT", "8080"))
        except ValueError as e:
            raise ConfigError("DASHBOARD_PORT non è un numero.") from e
        if not 0 <= port <= 65535:
            raise ConfigError("DASHBOARD_PORT fuori intervallo.")
        truthy = lambda v: str(v).strip().lower() in ("1", "true", "yes", "si", "sì", "on")  # noqa: E731
        return cls(
            password=password,
            host=env.get("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=port,
            cookie_secure=truthy(env.get("DASHBOARD_COOKIE_SECURE", "")),
            trust_proxy=truthy(env.get("DASHBOARD_TRUST_PROXY", "")),
        )


DB_KEY = web.AppKey("db", Database)
CONFIG_KEY = web.AppKey("config", DashboardConfig)
BOT_KEY = web.AppKey("bot", object)
SESSIONS_KEY = web.AppKey("sessions", SessionStore)
LIMITER_KEY = web.AppKey("limiter", LoginLimiter)


# ------------------------------------------------------------------------------ utilità

class _JsonHTTPError(web.HTTPException):
    """Errore HTTP con corpo JSON `{"error": "...", ...}`."""

    def __init__(self, status: int, message: str, extra: dict):
        self.status_code = status
        super().__init__(text=_dumps({"error": message, **extra}), content_type="application/json")


def json_error(status: int, message: str, **extra: Any) -> web.HTTPException:
    return _JsonHTTPError(status, message, extra)


def _dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def json_response(data: Any, status: int = 200) -> web.Response:
    return web.Response(text=_dumps(data), status=status, content_type="application/json")


def client_ip(request: web.Request) -> str:
    if request.app[CONFIG_KEY].trust_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or "?"
    return request.remote or "?"


async def json_body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except Exception:
        raise json_error(400, "Richiesta non valida (JSON atteso).")
    if not isinstance(data, dict):
        raise json_error(400, "Richiesta non valida (oggetto JSON atteso).")
    return data


def parse_scope(value: Any, *, allow_all: bool = False) -> Optional[int]:
    """'global'/'0' -> 0, '<id>' -> id, 'all' -> None (solo dove ammesso). Altro: errore 400."""
    text = str(value if value is not None else "").strip().lower()
    if allow_all and text in ("", "all"):
        return None
    if text in ("global", "globale", "0"):
        return storage.GLOBAL
    number = storage.parse_id(text)
    if number is None:
        raise json_error(400, "Server non valido.")
    return number


async def require_known_guild(db: Database, guild_id: int) -> None:
    if guild_id == storage.GLOBAL:
        return
    known = {g["id"] for g in await storage.list_guilds(db)}
    if guild_id not in known:
        raise json_error(404, "Server sconosciuto: il bot non lo ha mai visto.")


def parse_guild_ids(value: Any) -> list[int]:
    if value in (None, ""):
        return []
    items = value if isinstance(value, list) else str(value).split(",")
    ids = []
    for item in items:
        number = storage.parse_id(item)
        if number is None:
            raise json_error(400, "Elenco dei server non valido.")
        ids.append(number)
    return sorted(set(ids))


def sound_out(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "guild_id": row["guild_id"], "size": row["size"],
            "created_at": row["created_at"], "missing": row.get("missing", False),
            "format": Path(row["filename"]).suffix.lstrip(".").lower()}


def voice_out(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "guild_id": row["guild_id"], "size": row["size"],
            "duration": row["duration"], "created_at": row["created_at"], "missing": row.get("missing", False),
            "format": Path(row["filename"]).suffix.lstrip(".").lower()}


def model_out(row: dict) -> dict:
    return {"id": row["id"], "name": row["name"], "description": row["description"], "enabled": row["enabled"],
            "size": row["size"], "created_at": row["created_at"], "guild_ids": row.get("guild_ids", []),
            "missing": row.get("missing", False)}


# --------------------------------------------------------------------------- upload

@dataclass
class Upload:
    fields: dict
    path: Optional[Path]
    filename: str

    def discard(self) -> None:
        if self.path is not None:
            try:
                self.path.unlink()
            except OSError:
                pass


def _name_or_stem(upload: "Upload") -> str:
    """Il nome scelto dall'utente; se è vuoto (o solo spazi) quello del file caricato, senza estensione."""
    return (upload.fields.get("name") or "").strip() or Path(upload.filename).stem


def upload_dir() -> Path:
    path = Path(cogs.BASE_DATA_DIR) / ".uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def read_upload(request: web.Request, max_bytes: int, field_names: tuple[str, ...]) -> Upload:
    """
    Legge un form multipart in streaming: i campi testuali in un dizionario, il file (campo `file`) in un
    file temporaneo (stessa cartella dei dati: lo spostamento finale è atomico). Rifiuta file troppo grandi
    PRIMA di scaricarli tutti quando il client dichiara la lunghezza, e comunque durante la lettura.
    """
    if not request.content_type.startswith("multipart/"):
        raise json_error(400, "Atteso un modulo con un file allegato.")
    if request.content_length is not None and request.content_length > max_bytes + 64 * 1024:
        raise json_error(413, f"Il file supera il limite di {max_bytes // (1024 * 1024)} MB.")

    fields: dict[str, str] = {}
    tmp_path: Optional[Path] = None
    filename = ""
    try:
        reader = await request.multipart()
        async for part in reader:
            if part.name == "file" and part.filename:
                if tmp_path is not None:
                    raise json_error(400, "Carica un solo file alla volta.")
                filename = part.filename
                fd, name = tempfile.mkstemp(prefix="up-", dir=upload_dir())
                tmp_path = Path(name)
                size = 0
                with os.fdopen(fd, "wb") as out:
                    while True:
                        chunk = await part.read_chunk(UPLOAD_CHUNK)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > max_bytes:
                            raise json_error(413, f"Il file supera il limite di {max_bytes // (1024 * 1024)} MB.")
                        await asyncio.to_thread(out.write, chunk)
            elif part.name in field_names:
                data = await part.read(decode=True)
                if len(data) > MAX_FIELD_BYTES:
                    raise json_error(413, "Campo troppo lungo.")
                fields[part.name] = data.decode("utf-8", "replace")
            else:
                await part.read()          # campo sconosciuto: scartato
    except BaseException as e:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        if isinstance(e, ValueError):         # multipart malformato
            raise json_error(400, "Modulo non valido.") from e
        raise
    if tmp_path is None:
        raise json_error(400, "Nessun file allegato.")
    return Upload(fields, tmp_path, filename)


# ------------------------------------------------------------------------- middleware

def _decorate(request: web.Request, response: web.StreamResponse) -> None:
    for key, value in SECURITY_HEADERS.items():
        response.headers.setdefault(key, value)
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    elif request.path == "/" or request.path.startswith("/static/"):
        response.headers.setdefault("Cache-Control", "no-cache")


@web.middleware
async def security_headers(request: web.Request, handler):
    try:
        response = await handler(request)
    except web.HTTPException as e:
        _decorate(request, e)
        raise
    _decorate(request, response)
    return response


@web.middleware
async def errors(request: web.Request, handler):
    try:
        return await handler(request)
    except web.HTTPException as e:
        # i 404/405 di aiohttp sulle API diventano JSON come tutti gli altri errori
        if request.path.startswith("/api/") and e.content_type != "application/json":
            raise _JsonHTTPError(e.status, {404: "Risorsa non trovata.", 405: "Metodo non consentito."}.get(
                e.status, e.reason or "Errore"), {}) from None
        raise
    except storage.Duplicate as e:
        return json_response({"error": str(e)}, 409)
    except storage.NotFound as e:
        return json_response({"error": str(e)}, 404)
    except storage.StorageError as e:
        return json_response({"error": str(e)}, 400)
    except DatabaseBusy:
        return json_response({"error": "Database occupato, riprova tra un istante."}, 503)
    except DatabaseClosed:
        return json_response({"error": "Database non disponibile."}, 503)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("Errore nella dashboard: %s %s", request.method, request.path)
        return json_response({"error": "Errore interno: controlla i log del bot."}, 500)


def _same_origin(request: web.Request) -> bool:
    origin = request.headers.get("Origin")
    if origin is None:
        return True            # richieste non-browser (curl, test): contano solo cookie + CSRF
    return urlparse(origin).netloc == request.host


PUBLIC_API = {"/api/session", "/api/login"}
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@web.middleware
async def auth(request: web.Request, handler):
    if not request.path.startswith("/api/"):
        return await handler(request)
    if request.method in UNSAFE and not _same_origin(request):
        raise json_error(403, "Origine della richiesta non consentita.")
    if request.path in PUBLIC_API:
        return await handler(request)
    session = request.app[SESSIONS_KEY].get(request.cookies.get(COOKIE))
    if session is None:
        raise json_error(401, "Accesso richiesto.")
    if request.method in UNSAFE and not tokens_match(session.csrf, request.headers.get("X-CSRF-Token")):
        raise json_error(403, "Token CSRF mancante o non valido: ricarica la pagina.")
    return await handler(request)


# --------------------------------------------------------------------------- handlers

async def index(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def session_info(request: web.Request) -> web.Response:
    session = request.app[SESSIONS_KEY].get(request.cookies.get(COOKIE))
    return json_response({"authenticated": session is not None, "csrf": session.csrf if session else None})


async def login(request: web.Request) -> web.Response:
    app = request.app
    ip = client_ip(request)
    limiter: LoginLimiter = app[LIMITER_KEY]
    wait = limiter.retry_after(ip)
    if wait > 0:
        raise json_error(429, f"Troppi tentativi: riprova tra {int(wait) + 1} secondi.", retry_after=int(wait) + 1)
    body = await json_body(request)
    if not password_matches(app[CONFIG_KEY].password, body.get("password")):
        limiter.failure(ip)
        log.warning("Login alla dashboard fallito da %s", ip)
        await asyncio.sleep(app[CONFIG_KEY].fail_delay)
        raise json_error(401, "Password errata.")
    limiter.success(ip)
    session = app[SESSIONS_KEY].create()
    response = json_response({"csrf": session.csrf})
    response.set_cookie(
        COOKIE, session.token, max_age=int(app[CONFIG_KEY].session_ttl), httponly=True,
        samesite="Strict", secure=app[CONFIG_KEY].cookie_secure, path="/",
    )
    await storage.log_action(app[DB_KEY], ACTOR, "login", ip)
    return response


async def logout(request: web.Request) -> web.Response:
    request.app[SESSIONS_KEY].delete(request.cookies.get(COOKIE))
    response = json_response({"ok": True})
    response.del_cookie(COOKIE, path="/")
    return response


async def get_overview(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    bot = request.app.get(BOT_KEY)
    bot_info: dict = {"connected": False}
    if bot is not None:
        try:
            ready = bot.is_ready()
            bot_info = {"connected": ready, "latency_ms": round(bot.latency * 1000) if ready else None,
                        "user": str(bot.user) if bot.user else None}
        except Exception:
            bot_info = {"connected": False}
    return json_response({
        "counts": await storage.overview(db),
        "db": db.stats(),
        "bot": bot_info,
        "limits": {"sound_mb": storage.MAX_SOUND_BYTES // 1048576, "voice_mb": storage.MAX_VOICE_BYTES // 1048576,
                   "rvc_mb": storage.MAX_RVC_BYTES // 1048576},
    })


async def get_guilds(request: web.Request) -> web.Response:
    return json_response({"guilds": await storage.list_guilds(request.app[DB_KEY])})


async def get_audit(request: web.Request) -> web.Response:
    try:
        limit = int(request.query.get("limit", "100"))
    except ValueError:
        raise json_error(400, "Limite non valido.")
    return json_response({"entries": await storage.list_audit(request.app[DB_KEY], limit)})


# -- suoni

async def sounds_list(request: web.Request) -> web.Response:
    scope = parse_scope(request.query.get("scope"), allow_all=True)
    rows = await storage.list_sounds(request.app[DB_KEY], scope)
    return json_response({"sounds": [sound_out(r) for r in rows]})


async def sounds_add(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    upload = await read_upload(request, storage.MAX_SOUND_BYTES, ("name", "scope"))
    try:
        scope = parse_scope(upload.fields.get("scope", "global"))
        await require_known_guild(db, scope)
        name = _name_or_stem(upload)
        row = await storage.add_sound(db, scope, name, upload.path, actor=ACTOR)
    except BaseException:
        upload.discard()
        raise
    return json_response({"sound": sound_out(row)}, 201)


async def sounds_update(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    sound_id, body = request.match_info["id"], await json_body(request)
    if "scope" in body:
        scope = parse_scope(body["scope"])
        await require_known_guild(db, scope)
        row = await storage.move_sound(db, sound_id, scope, name=body.get("name"), actor=ACTOR)
    elif "name" in body:
        row = await storage.rename_sound(db, sound_id, body["name"], actor=ACTOR)
    else:
        raise json_error(400, "Niente da modificare.")
    return json_response({"sound": sound_out(row)})


async def sounds_delete(request: web.Request) -> web.Response:
    await storage.delete_sound(request.app[DB_KEY], request.match_info["id"], actor=ACTOR)
    return json_response({"ok": True})


def audio_response(path: Optional[Path], name: str) -> web.StreamResponse:
    if path is None:
        raise json_error(404, "Il file audio non esiste più sul disco.")
    kind = storage.sniff_audio(path) or "wav"
    response = web.FileResponse(path, headers={
        "Content-Type": AUDIO_TYPES.get(kind, "application/octet-stream"),
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(name + '.' + kind)}",
    })
    return response


async def sounds_audio(request: web.Request) -> web.StreamResponse:
    row = await storage.get_sound(request.app[DB_KEY], request.match_info["id"])
    if row is None:
        raise json_error(404, "Suono non trovato.")
    return audio_response(await asyncio.to_thread(storage.sound_file, row), row["name"])


# -- voci

async def voices_list(request: web.Request) -> web.Response:
    scope = parse_scope(request.query.get("guild"), allow_all=True)
    if scope == storage.GLOBAL:
        raise json_error(400, "Le voci clonate appartengono a un server.")
    rows = await storage.list_voices(request.app[DB_KEY], scope)
    return json_response({"voices": [voice_out(r) for r in rows]})


async def voices_add(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    upload = await read_upload(request, storage.MAX_VOICE_BYTES, ("name", "guild"))
    try:
        guild = parse_scope(upload.fields.get("guild", ""))
        await require_known_guild(db, guild)
        name = _name_or_stem(upload)
        row = await storage.add_voice(db, guild, name, upload.path, actor=ACTOR)
    except BaseException:
        upload.discard()
        raise
    return json_response({"voice": voice_out(row)}, 201)


async def voices_update(request: web.Request) -> web.Response:
    body = await json_body(request)
    if "name" not in body:
        raise json_error(400, "Niente da modificare.")
    row = await storage.rename_voice(request.app[DB_KEY], request.match_info["id"], body["name"], actor=ACTOR)
    return json_response({"voice": voice_out(row)})


async def voices_delete(request: web.Request) -> web.Response:
    await storage.delete_voice(request.app[DB_KEY], request.match_info["id"], actor=ACTOR)
    return json_response({"ok": True})


async def voices_audio(request: web.Request) -> web.StreamResponse:
    row = await storage.get_voice(request.app[DB_KEY], request.match_info["id"])
    if row is None:
        raise json_error(404, "Voce non trovata.")
    return audio_response(await asyncio.to_thread(storage.voice_file, row), row["name"])


# -- modelli RVC

async def rvc_list(request: web.Request) -> web.Response:
    rows = await storage.list_rvc_models(request.app[DB_KEY])
    return json_response({"models": [model_out(r) for r in rows]})


async def rvc_add(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    upload = await read_upload(request, storage.MAX_RVC_BYTES, ("name", "description", "guild_ids"))
    try:
        guild_ids = parse_guild_ids(upload.fields.get("guild_ids"))
        for gid in guild_ids:
            await require_known_guild(db, gid)
        name = _name_or_stem(upload)
        row = await storage.add_rvc_model(
            db, name, upload.path, upload.filename,
            description=upload.fields.get("description", ""), guild_ids=guild_ids, actor=ACTOR,
        )
    except BaseException:
        upload.discard()
        raise
    return json_response({"model": model_out(row)}, 201)


async def rvc_update(request: web.Request) -> web.Response:
    db: Database = request.app[DB_KEY]
    body = await json_body(request)
    guild_ids = None
    if "guild_ids" in body:
        guild_ids = parse_guild_ids(body["guild_ids"])
        for gid in guild_ids:
            await require_known_guild(db, gid)
    enabled = body.get("enabled")
    if enabled is not None and not isinstance(enabled, bool):
        raise json_error(400, "Il campo «enabled» deve essere vero o falso.")
    description = body.get("description")
    if description is not None and not isinstance(description, str):
        raise json_error(400, "Descrizione non valida.")
    if not any(k in body for k in ("name", "description", "enabled", "guild_ids")):
        raise json_error(400, "Niente da modificare.")
    row = await storage.update_rvc_model(
        db, request.match_info["id"], name=body.get("name"), description=description,
        enabled=enabled, guild_ids=guild_ids, actor=ACTOR,
    )
    return json_response({"model": model_out(row)})


async def rvc_delete(request: web.Request) -> web.Response:
    await storage.delete_rvc_model(request.app[DB_KEY], request.match_info["id"], actor=ACTOR)
    return json_response({"ok": True})


async def rvc_scan(request: web.Request) -> web.Response:
    return json_response(await storage.scan_rvc_models(request.app[DB_KEY], actor=ACTOR))


# ---------------------------------------------------------------------------- app

def create_app(db: Database, config: DashboardConfig, bot: Any = None) -> web.Application:
    app = web.Application(middlewares=[security_headers, errors, auth], client_max_size=1024 * 1024)
    app[DB_KEY], app[CONFIG_KEY], app[BOT_KEY] = db, config, bot
    app[SESSIONS_KEY] = SessionStore(config.session_ttl)
    app[LIMITER_KEY] = LoginLimiter(config.max_failures, lockout=config.lockout)

    r = app.router
    r.add_get("/", index)
    r.add_static("/static", STATIC_DIR, follow_symlinks=False, show_index=False)

    r.add_get("/api/session", session_info)
    r.add_post("/api/login", login)
    r.add_post("/api/logout", logout)
    r.add_get("/api/overview", get_overview)
    r.add_get("/api/guilds", get_guilds)
    r.add_get("/api/audit", get_audit)

    r.add_get("/api/sounds", sounds_list)
    r.add_post("/api/sounds", sounds_add)
    r.add_patch("/api/sounds/{id}", sounds_update)
    r.add_delete("/api/sounds/{id}", sounds_delete)
    r.add_get("/api/sounds/{id}/audio", sounds_audio)

    r.add_get("/api/voices", voices_list)
    r.add_post("/api/voices", voices_add)
    r.add_patch("/api/voices/{id}", voices_update)
    r.add_delete("/api/voices/{id}", voices_delete)
    r.add_get("/api/voices/{id}/audio", voices_audio)

    r.add_get("/api/rvc", rvc_list)
    r.add_post("/api/rvc", rvc_add)
    r.add_post("/api/rvc/scan", rvc_scan)
    r.add_patch("/api/rvc/{id}", rvc_update)
    r.add_delete("/api/rvc/{id}", rvc_delete)
    return app


class DashboardServer:
    """Avvia/ferma la dashboard dentro un event loop esistente (cog del bot o runner standalone)."""

    def __init__(self, db: Database, config: DashboardConfig, bot: Any = None):
        self.config = config
        self.app = create_app(db, config, bot)
        self._runner: Optional[web.AppRunner] = None
        self.port: Optional[int] = None

    async def start(self) -> None:
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await site.start()
        sockets = getattr(site._server, "sockets", None) or []
        self.port = sockets[0].getsockname()[1] if sockets else self.config.port
        log.info("Dashboard in ascolto su http://%s:%s", self.config.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    @property
    def url(self) -> str:
        host = "localhost" if self.config.host in ("0.0.0.0", "::") else self.config.host
        return f"http://{host}:{self.port}"
