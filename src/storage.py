"""
Archivio dei contenuti gestiti dal bot (soundboard, voci clonate, modelli RVC, server).

È l'unico punto che parla con SQLite e con le cartelle dei file: i cog (slash command) e la dashboard
usano le STESSE funzioni, quindi regole di validazione, nomi univoci e pulizia dei file sono identiche
ovunque. Non importa torch/discord-voice: può girare anche nel processo separato della dashboard.

Disposizione dei file su disco (invariata rispetto alla versione con i JSON):

    cogs/data/<id-server>/soundboard/<file>     suoni di un server
    cogs/data/global/soundboard/<file>          suoni globali (tutti i server)
    cogs/data/<id-server>/speakers/<file>       campioni delle voci clonate
    cogs/RVC/models/<cartella>/*.pth, *.index   modelli RVC

Gli errori "attesi" sono `StorageError` con un messaggio già adatto all'utente (in italiano).
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
import wave
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Optional, Sequence

import cogs
from database import Database

log = logging.getLogger(__name__)

GLOBAL = 0                    # guild_id dei suoni globali
MAX_NAME_LENGTH = 100         # il nome finisce in un Choice di Discord (max 100 caratteri)
MIN_PASSWORD_LENGTH = 8


def _mb(env: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(env, default))) * 1024 * 1024
    except ValueError:
        return default * 1024 * 1024


MAX_SOUND_BYTES = _mb("DASHBOARD_MAX_SOUND_MB", 8)
MAX_VOICE_BYTES = _mb("DASHBOARD_MAX_VOICE_MB", 50)
MAX_RVC_BYTES = _mb("DASHBOARD_MAX_RVC_MB", 1024)

# Cartella dei modelli RVC: la usa anche cogs/RVC/rvc.py (che importa torch: qui non lo si può fare)
RVC_MODELS_DIR = Path(cogs.__file__).parent.absolute() / "RVC" / "models"


class StorageError(Exception):
    """Errore atteso: il testo è pensato per essere mostrato all'utente."""


class InvalidInput(StorageError):
    pass


class NotFound(StorageError):
    pass


class Duplicate(StorageError):
    pass


# ----------------------------------------------------------------------------- percorsi

def default_db_path() -> Path:
    override = os.getenv("DRIFTBOT_DB")
    return Path(override) if override else Path(cogs.BASE_DATA_DIR) / "driftbot.sqlite3"


def _scope_dir(guild_id: int) -> Path:
    return Path(cogs.BASE_DATA_DIR) / ("global" if guild_id == GLOBAL else str(guild_id))


def sounds_dir(guild_id: int) -> Path:
    return _scope_dir(guild_id) / "soundboard"


def voices_dir(guild_id: int) -> Path:
    return _scope_dir(guild_id) / "speakers"


def rvc_models_dir() -> Path:
    return Path(RVC_MODELS_DIR)


def safe_file(base: Path, filename: str) -> Optional[Path]:
    """Percorso del file se esiste ed è DENTRO `base` (mai fuori, qualunque cosa ci sia nel database)."""
    path = cogs.resolve_in_dir(base, filename)
    if path is None or not path.is_file():
        return None
    return path


# --------------------------------------------------------------------------- validazione

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def clean_name(name: Any, what: str = "Il nome") -> str:
    if not isinstance(name, str):
        raise InvalidInput(f"{what} non è valido.")
    name = re.sub(r"\s+", " ", _CONTROL.sub(" ", name)).strip()
    if not name:
        raise InvalidInput(f"{what} non può essere vuoto.")
    if len(name) > MAX_NAME_LENGTH:
        raise InvalidInput(f"{what} può avere al massimo {MAX_NAME_LENGTH} caratteri.")
    return name


def parse_id(value: Any) -> Optional[int]:
    """Converte l'id (arrivato come stringa da un Choice o da un URL) in intero positivo, altrimenti None."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 2**63 else None


def sniff_audio(path: Path) -> Optional[str]:
    """Riconosce il formato dal contenuto (non dall'estensione): 'wav', 'mp3', 'ogg', 'flac', 'm4a' o None."""
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except OSError:
        return None
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[:3] == b"ID3" or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0):
        return "mp3"
    if head[:4] == b"OggS":
        return "ogg"
    if head[:4] == b"fLaC":
        return "flac"
    if head[4:8] == b"ftyp":
        return "m4a"
    return None


def wav_duration(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path), "rb") as w:
            return w.getnframes() / float(w.getframerate() or 1)
    except (wave.Error, EOFError, OSError):
        return None


def _is_unique_violation(error: sqlite3.IntegrityError) -> bool:
    return "UNIQUE" in str(error).upper()


def _unlink(path: Optional[Path]) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        log.warning("Impossibile eliminare %s: %s", path, e)


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(src, dest)
    except OSError:
        shutil.move(str(src), str(dest))     # file system diversi


def _audit(conn: sqlite3.Connection, actor: str, action: str, detail: str = "") -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, actor, action, detail) VALUES (?, ?, ?, ?)",
        (time.time(), actor, action, detail[:500]),
    )


async def list_audit(db: Database, limit: int = 100) -> list[dict]:
    return await db.fetchall(
        "SELECT id, ts, actor, action, detail FROM audit_log ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 500)),),
    )


async def log_action(db: Database, actor: str, action: str, detail: str = "") -> None:
    await db.write(_audit, actor, action, detail)


# ------------------------------------------------------------------------------ server

async def sync_guilds(db: Database, guilds: Iterable[tuple[int, str, Optional[str], Optional[int]]]) -> None:
    """Aggiorna la cache dei server (id, nome, icona, membri). Chi non c'è più viene segnato come uscito."""
    rows = [(int(g[0]), str(g[1])[:200], g[2], g[3]) for g in guilds]
    now = time.time()

    def run(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE guilds SET present = 0")
        conn.executemany(
            """INSERT INTO guilds (id, name, icon_url, member_count, present, updated_at)
               VALUES (?, ?, ?, ?, 1, ?)
               ON CONFLICT (id) DO UPDATE SET name = excluded.name, icon_url = excluded.icon_url,
                   member_count = excluded.member_count, present = 1, updated_at = excluded.updated_at""",
            [(*r, now) for r in rows],
        )

    await db.write(run)


async def mark_guild_left(db: Database, guild_id: int) -> None:
    await db.execute("UPDATE guilds SET present = 0 WHERE id = ?", (int(guild_id),))


async def list_guilds(db: Database) -> list[dict]:
    """Tutti i server noti (anche quelli senza riga nella cache ma con contenuti), con i conteggi."""

    def run(conn: sqlite3.Connection) -> list[dict]:
        known = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM guilds")}
        for table in ("sounds", "voices"):
            for r in conn.execute(f"SELECT DISTINCT guild_id FROM {table} WHERE guild_id != ?", (GLOBAL,)):
                known.setdefault(r[0], {"id": r[0], "name": f"Server {r[0]}", "icon_url": None,
                                        "member_count": None, "present": 0, "updated_at": 0})
        sounds = dict(conn.execute("SELECT guild_id, COUNT(*) FROM sounds GROUP BY guild_id").fetchall())
        voices = dict(conn.execute("SELECT guild_id, COUNT(*) FROM voices GROUP BY guild_id").fetchall())
        for gid, g in known.items():
            g["sounds"], g["voices"] = sounds.get(gid, 0), voices.get(gid, 0)
        return sorted(known.values(), key=lambda g: (-g["present"], g["name"].lower()))

    return await db.read(run)


async def overview(db: Database) -> dict:
    def run(conn: sqlite3.Connection) -> dict:
        one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "guilds": one("SELECT COUNT(*) FROM guilds WHERE present = 1"),
            "sounds": one("SELECT COUNT(*) FROM sounds WHERE guild_id != 0"),
            "global_sounds": one("SELECT COUNT(*) FROM sounds WHERE guild_id = 0"),
            "voices": one("SELECT COUNT(*) FROM voices"),
            "rvc_models": one("SELECT COUNT(*) FROM rvc_models"),
            "rvc_enabled": one("SELECT COUNT(*) FROM rvc_models WHERE enabled = 1"),
            "disk_bytes": one(
                "SELECT (SELECT COALESCE(SUM(size),0) FROM sounds) + (SELECT COALESCE(SUM(size),0) FROM voices)"
                " + (SELECT COALESCE(SUM(size),0) FROM rvc_models)"
            ),
        }

    return await db.read(run)


# ------------------------------------------------------------------------------ suoni

def _flag_missing(rows: list[dict], base_for) -> list[dict]:
    for row in rows:
        row["missing"] = safe_file(base_for(row), row["filename"]) is None
    return rows


async def list_sounds(db: Database, scope: Optional[int] = None) -> list[dict]:
    """`scope` None = tutti; altrimenti esattamente quel guild_id (0 = globali)."""
    if scope is None:
        rows = await db.fetchall("SELECT * FROM sounds ORDER BY guild_id, name")
    else:
        rows = await db.fetchall("SELECT * FROM sounds WHERE guild_id = ? ORDER BY name", (int(scope),))
    return await asyncio.to_thread(_flag_missing, rows, lambda r: sounds_dir(r["guild_id"]))


async def list_sounds_for_guild(db: Database, guild_id: int) -> list[dict]:
    """Suoni usabili in un server: i suoi + quelli globali (per l'autocomplete, nessun accesso al disco)."""
    return await db.fetchall(
        "SELECT * FROM sounds WHERE guild_id IN (?, ?) ORDER BY name",
        (int(guild_id), GLOBAL),
    )


async def get_sound(db: Database, sound_id: Any) -> Optional[dict]:
    number = parse_id(sound_id)
    return None if number is None else await db.fetchone("SELECT * FROM sounds WHERE id = ?", (number,))


async def resolve_sound(db: Database, guild_id: int, sound_id: Any) -> Optional[tuple[dict, Path]]:
    """Il suono (e il suo file) se è usabile in quel server; None se non esiste, è di un altro server o manca il file."""
    row = await get_sound(db, sound_id)
    if row is None or row["guild_id"] not in (int(guild_id), GLOBAL):
        return None
    path = await asyncio.to_thread(safe_file, sounds_dir(row["guild_id"]), row["filename"])
    return (row, path) if path else None


def sound_file(row: dict) -> Optional[Path]:
    return safe_file(sounds_dir(row["guild_id"]), row["filename"])


def _check_upload(src: Path, max_bytes: int, what: str) -> str:
    try:
        size = src.stat().st_size
    except OSError as e:
        raise InvalidInput("File non leggibile.") from e
    if size == 0:
        raise InvalidInput("Il file è vuoto.")
    if size > max_bytes:
        raise InvalidInput(f"{what} supera il limite di {max_bytes // (1024 * 1024)} MB.")
    kind = sniff_audio(src)
    if kind is None:
        raise InvalidInput("Formato audio non riconosciuto (usa WAV, MP3, OGG, FLAC o M4A).")
    return kind


async def add_sound(db: Database, guild_id: int, name: Any, src: Path, *, actor: str = "bot") -> dict:
    """Registra un suono: `src` è un file temporaneo che viene SPOSTATO nella cartella del server."""
    name = clean_name(name, "Il nome del suono")
    src = Path(src)
    try:
        kind = await asyncio.to_thread(_check_upload, src, MAX_SOUND_BYTES, "Il suono")
    except StorageError:
        _unlink(src)
        raise
    filename = f"{uuid.uuid4().hex}.{kind}"
    dest = sounds_dir(guild_id) / filename
    await asyncio.to_thread(_move, src, dest)
    size = dest.stat().st_size

    def run(conn: sqlite3.Connection) -> int:
        new_id = conn.execute(
            "INSERT INTO sounds (guild_id, name, filename, size, created_at) VALUES (?, ?, ?, ?, ?)",
            (int(guild_id), name, filename, size, time.time()),
        ).lastrowid
        _audit(conn, actor, "sound.add", f"{name} (server {guild_id or 'globale'})")
        return new_id

    try:
        new_id = await db.write(run)
    except BaseException as e:
        _unlink(dest)
        if isinstance(e, sqlite3.IntegrityError) and _is_unique_violation(e):
            raise Duplicate(f"Esiste già un suono chiamato «{name}» in questo elenco.") from e
        raise
    return await get_sound(db, new_id)  # type: ignore[return-value]


async def rename_sound(db: Database, sound_id: Any, name: Any, *, actor: str = "bot") -> dict:
    number, name = parse_id(sound_id), clean_name(name, "Il nome del suono")

    def run(conn: sqlite3.Connection) -> int:
        old = conn.execute("SELECT name FROM sounds WHERE id = ?", (number,)).fetchone()
        if old is None:
            return 0
        conn.execute("UPDATE sounds SET name = ? WHERE id = ?", (name, number))
        _audit(conn, actor, "sound.rename", f"{old['name']} → {name}")
        return 1

    try:
        found = number is not None and await db.write(run)
    except sqlite3.IntegrityError as e:
        if _is_unique_violation(e):
            raise Duplicate(f"Esiste già un suono chiamato «{name}» in questo elenco.") from e
        raise
    if not found:
        raise NotFound("Suono non trovato.")
    return await get_sound(db, number)  # type: ignore[return-value]


async def move_sound(
    db: Database, sound_id: Any, guild_id: int, *, name: Any = None, actor: str = "bot"
) -> dict:
    """
    Sposta un suono in un altro server oppure lo rende globale (guild_id = 0), con la possibilità di
    rinominarlo nello stesso passaggio (il controllo dei nomi doppi vale per la combinazione finale).
    """
    row = await get_sound(db, sound_id)
    if row is None:
        raise NotFound("Suono non trovato.")
    new_name = clean_name(name, "Il nome del suono") if name is not None else row["name"]
    if row["guild_id"] == int(guild_id):
        return row if new_name == row["name"] else await rename_sound(db, row["id"], new_name, actor=actor)
    src, dest = sounds_dir(row["guild_id"]) / row["filename"], sounds_dir(guild_id) / row["filename"]
    if not safe_file(sounds_dir(row["guild_id"]), row["filename"]):
        raise NotFound("Il file del suono non esiste più sul disco.")
    await asyncio.to_thread(_move, src, dest)

    def run(conn: sqlite3.Connection) -> None:
        conn.execute("UPDATE sounds SET guild_id = ?, name = ? WHERE id = ?", (int(guild_id), new_name, row["id"]))
        _audit(conn, actor, "sound.move", f"{row['name']} → {'globale' if guild_id == GLOBAL else f'server {guild_id}'}")

    try:
        await db.write(run)
    except BaseException as e:
        await asyncio.to_thread(_move, dest, src)       # annulla lo spostamento del file
        if isinstance(e, sqlite3.IntegrityError) and _is_unique_violation(e):
            raise Duplicate(f"La destinazione ha già un suono chiamato «{new_name}».") from e
        raise
    return await get_sound(db, row["id"])  # type: ignore[return-value]


async def delete_sound(db: Database, sound_id: Any, *, actor: str = "bot") -> dict:
    number = parse_id(sound_id)

    def run(conn: sqlite3.Connection) -> Optional[dict]:
        row = conn.execute("SELECT * FROM sounds WHERE id = ?", (number,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM sounds WHERE id = ?", (number,))
        _audit(conn, actor, "sound.delete", row["name"])
        return dict(row)

    row = await db.write(run) if number is not None else None
    if row is None:
        raise NotFound("Suono non trovato.")
    await asyncio.to_thread(_unlink, cogs.resolve_in_dir(sounds_dir(row["guild_id"]), row["filename"]))
    return row


# ------------------------------------------------------------------------------- voci

async def list_voices(db: Database, guild_id: Optional[int] = None) -> list[dict]:
    if guild_id is None:
        rows = await db.fetchall("SELECT * FROM voices ORDER BY guild_id, name")
    else:
        rows = await db.fetchall("SELECT * FROM voices WHERE guild_id = ? ORDER BY name", (int(guild_id),))
    return await asyncio.to_thread(_flag_missing, rows, lambda r: voices_dir(r["guild_id"]))


async def list_voices_for_guild(db: Database, guild_id: int) -> list[dict]:
    """Per l'autocomplete: nessun accesso al disco."""
    return await db.fetchall("SELECT * FROM voices WHERE guild_id = ? ORDER BY name", (int(guild_id),))


async def get_voice(db: Database, voice_id: Any) -> Optional[dict]:
    number = parse_id(voice_id)
    return None if number is None else await db.fetchone("SELECT * FROM voices WHERE id = ?", (number,))


async def resolve_voice(db: Database, guild_id: int, voice_id: Any) -> Optional[tuple[dict, Path]]:
    row = await get_voice(db, voice_id)
    if row is None or row["guild_id"] != int(guild_id):
        return None
    path = await asyncio.to_thread(safe_file, voices_dir(row["guild_id"]), row["filename"])
    return (row, path) if path else None


def voice_file(row: dict) -> Optional[Path]:
    return safe_file(voices_dir(row["guild_id"]), row["filename"])


async def add_voice(
    db: Database, guild_id: int, name: Any, src: Path, *, source_name: Optional[str] = None, actor: str = "bot"
) -> dict:
    """Aggiunge una voce da un campione audio caricato (`src` viene spostato nella cartella del server)."""
    if int(guild_id) == GLOBAL:
        raise InvalidInput("Le voci clonate appartengono a un server.")
    name = clean_name(name, "Il nome della voce")
    src = Path(src)
    try:
        kind = await asyncio.to_thread(_check_upload, src, MAX_VOICE_BYTES, "Il campione")
    except StorageError:
        _unlink(src)
        raise
    filename = f"{uuid.uuid4().hex}.{kind}"
    dest = voices_dir(guild_id) / filename
    await asyncio.to_thread(_move, src, dest)
    size = dest.stat().st_size
    duration = await asyncio.to_thread(wav_duration, dest) if kind == "wav" else None

    def run(conn: sqlite3.Connection) -> int:
        new_id = conn.execute(
            "INSERT INTO voices (guild_id, name, source_name, filename, duration, size, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(guild_id), name, source_name or name, filename, duration, size, time.time()),
        ).lastrowid
        _audit(conn, actor, "voice.add", f"{name} (server {guild_id})")
        return new_id

    try:
        new_id = await db.write(run)
    except BaseException as e:
        _unlink(dest)
        if isinstance(e, sqlite3.IntegrityError) and _is_unique_violation(e):
            raise Duplicate(f"Esiste già una voce chiamata «{name}» in questo server.") from e
        raise
    return await get_voice(db, new_id)  # type: ignore[return-value]


async def save_recorded_voice(
    db: Database, guild_id: int, source_name: str, filename: str, duration: Optional[float] = None, *, actor: str = "bot"
) -> dict:
    """
    Salva una voce appena registrata col comando /new-speaker (il file è già in `voices_dir`).
    Se la stessa persona era già stata registrata la sua voce viene SOSTITUITA (anche se nel frattempo è
    stata rinominata) e il vecchio campione eliminato; altrimenti nasce una voce nuova.
    """
    path = safe_file(voices_dir(guild_id), filename)
    if path is None:
        raise NotFound("Il file registrato non esiste.")
    size = path.stat().st_size
    source_name = clean_name(source_name, "Il nome dell'utente")

    def run(conn: sqlite3.Connection) -> tuple[int, Optional[str]]:
        existing = conn.execute(
            "SELECT id, filename FROM voices WHERE guild_id = ? AND source_name = ? ORDER BY id LIMIT 1",
            (int(guild_id), source_name),
        ).fetchone()
        if existing is not None:
            conn.execute(
                "UPDATE voices SET filename = ?, size = ?, duration = ?, created_at = ? WHERE id = ?",
                (filename, size, duration, time.time(), existing["id"]),
            )
            _audit(conn, actor, "voice.replace", source_name)
            return existing["id"], existing["filename"]
        name, n = source_name, 1
        while conn.execute("SELECT 1 FROM voices WHERE guild_id = ? AND name = ?", (int(guild_id), name)).fetchone():
            n += 1
            name = f"{source_name[:MAX_NAME_LENGTH - 6]} ({n})"
        new_id = conn.execute(
            "INSERT INTO voices (guild_id, name, source_name, filename, duration, size, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (int(guild_id), name, source_name, filename, duration, size, time.time()),
        ).lastrowid
        _audit(conn, actor, "voice.add", f"{name} (registrata)")
        return new_id, None

    voice_id, old_filename = await db.write(run)
    if old_filename and old_filename != filename:
        await asyncio.to_thread(_unlink, cogs.resolve_in_dir(voices_dir(guild_id), old_filename))
    return await get_voice(db, voice_id)  # type: ignore[return-value]


async def rename_voice(db: Database, voice_id: Any, name: Any, *, actor: str = "bot") -> dict:
    number, name = parse_id(voice_id), clean_name(name, "Il nome della voce")

    def run(conn: sqlite3.Connection) -> int:
        old = conn.execute("SELECT name FROM voices WHERE id = ?", (number,)).fetchone()
        if old is None:
            return 0
        conn.execute("UPDATE voices SET name = ? WHERE id = ?", (name, number))
        _audit(conn, actor, "voice.rename", f"{old['name']} → {name}")
        return 1

    try:
        found = number is not None and await db.write(run)
    except sqlite3.IntegrityError as e:
        if _is_unique_violation(e):
            raise Duplicate(f"Esiste già una voce chiamata «{name}» in questo server.") from e
        raise
    if not found:
        raise NotFound("Voce non trovata.")
    return await get_voice(db, number)  # type: ignore[return-value]


async def delete_voice(db: Database, voice_id: Any, *, actor: str = "bot") -> dict:
    number = parse_id(voice_id)

    def run(conn: sqlite3.Connection) -> Optional[dict]:
        row = conn.execute("SELECT * FROM voices WHERE id = ?", (number,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM voices WHERE id = ?", (number,))
        _audit(conn, actor, "voice.delete", row["name"])
        return dict(row)

    row = await db.write(run) if number is not None else None
    if row is None:
        raise NotFound("Voce non trovata.")
    await asyncio.to_thread(_unlink, cogs.resolve_in_dir(voices_dir(row["guild_id"]), row["filename"]))
    return row


# ------------------------------------------------------------------------- modelli RVC

def _dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                total += entry.stat().st_size
    except OSError:
        pass
    return total


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")[:60] or "modello"


def model_folder(row: dict) -> Optional[Path]:
    """Cartella del modello se esiste ed è dentro la cartella dei modelli."""
    path = cogs.resolve_in_dir(rvc_models_dir(), row["folder"])
    return path if path is not None and path.is_dir() else None


def _annotate_models(rows: list[dict], access: dict[int, list[int]]) -> list[dict]:
    for row in rows:
        row["guild_ids"] = access.get(row["id"], [])
        row["enabled"] = bool(row["enabled"])
        row["missing"] = model_folder(row) is None
    return rows


async def list_rvc_models(db: Database, guild_id: Optional[int] = None, *, usable_only: bool = False) -> list[dict]:
    """
    Modelli RVC. Con `guild_id` e `usable_only` restituisce solo quelli utilizzabili in quel server
    (abilitati e, se limitati a certi server, assegnati a quello): è la lista dell'autocomplete.
    """

    def run(conn: sqlite3.Connection) -> tuple[list[dict], dict[int, list[int]]]:
        if usable_only and guild_id is not None:
            rows = conn.execute(
                """SELECT m.* FROM rvc_models m WHERE m.enabled = 1 AND (
                       NOT EXISTS (SELECT 1 FROM rvc_model_access a WHERE a.model_id = m.id)
                       OR EXISTS (SELECT 1 FROM rvc_model_access a WHERE a.model_id = m.id AND a.guild_id = ?))
                   ORDER BY m.name""",
                (int(guild_id),),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM rvc_models ORDER BY name").fetchall()
        access: dict[int, list[int]] = {}
        for r in conn.execute("SELECT model_id, guild_id FROM rvc_model_access ORDER BY guild_id"):
            access.setdefault(r[0], []).append(r[1])
        return [dict(r) for r in rows], access

    rows, access = await db.read(run)
    if usable_only:
        # senza accesso al disco: è l'autocomplete, deve rispondere in pochi millisecondi
        return [{**r, "guild_ids": access.get(r["id"], []), "enabled": bool(r["enabled"])} for r in rows]
    return await asyncio.to_thread(_annotate_models, rows, access)


async def get_rvc_model(db: Database, model_id: Any) -> Optional[dict]:
    number = parse_id(model_id)
    if number is None:
        return None
    rows = [r for r in await list_rvc_models(db) if r["id"] == number]
    return rows[0] if rows else None


async def resolve_rvc_model(db: Database, guild_id: int, model_id: Any) -> Optional[dict]:
    """Il modello se in quel server è utilizzabile (abilitato, assegnato e con la cartella presente)."""
    number = parse_id(model_id)
    if number is None:
        return None
    usable = {r["id"]: r for r in await list_rvc_models(db, guild_id, usable_only=True)}
    row = usable.get(number)
    if row is None or await asyncio.to_thread(model_folder, row) is None:
        return None
    return row


def _extract_zip(zip_path: Path, dest: Path) -> None:
    """Estrae SOLO .pth e .index, appiattendo le cartelle (nessun path traversal) e con limiti di dimensione."""
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise InvalidInput("Lo zip non è valido o è danneggiato.") from e
    with zf:
        wanted: dict[str, zipfile.ZipInfo] = {}
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = PurePosixPath(info.filename.replace("\\", "/")).name
            if not name or name.startswith(".") or Path(name).suffix.lower() not in (".pth", ".index"):
                continue
            if name in wanted:
                raise InvalidInput(f"Lo zip contiene più file chiamati «{name}».")
            wanted[name] = info
        pth = [n for n in wanted if n.lower().endswith(".pth")]
        index = [n for n in wanted if n.lower().endswith(".index")]
        if len(pth) != 1:
            raise InvalidInput("Lo zip deve contenere esattamente un file .pth (il modello).")
        if len(index) > 1:
            raise InvalidInput("Lo zip contiene più di un file .index.")
        if sum(i.file_size for i in wanted.values()) > MAX_RVC_BYTES:
            raise InvalidInput(f"Il modello supera il limite di {MAX_RVC_BYTES // (1024 * 1024)} MB.")
        dest.mkdir(parents=True)
        budget = MAX_RVC_BYTES
        for name, info in wanted.items():
            try:
                with zf.open(info) as src, open(dest / name, "wb") as out:
                    while chunk := src.read(1024 * 1024):
                        budget -= len(chunk)
                        if budget < 0:          # il file dichiarava meno di quanto contiene (zip bomb)
                            raise InvalidInput("Il modello supera il limite di dimensione.")
                        out.write(chunk)
            except (RuntimeError, zipfile.BadZipFile) as e:   # zip cifrato o corrotto
                raise InvalidInput("Impossibile leggere lo zip (cifrato o danneggiato).") from e


def _install_model_files(src: Path, original_name: str, folder: str) -> Path:
    """Crea models/<folder> da uno zip o da un singolo .pth. Atomico: o c'è tutto o non c'è nulla."""
    models = rvc_models_dir()
    models.mkdir(parents=True, exist_ok=True)
    staging = models / f".tmp-{uuid.uuid4().hex}"
    try:
        # Si decide dall'estensione: i file .pth di PyTorch sono essi stessi archivi zip!
        if original_name.lower().endswith(".zip"):
            _extract_zip(src, staging)
        elif original_name.lower().endswith(".pth"):
            if src.stat().st_size > MAX_RVC_BYTES:
                raise InvalidInput(f"Il modello supera il limite di {MAX_RVC_BYTES // (1024 * 1024)} MB.")
            staging.mkdir()
            shutil.copyfile(src, staging / f"{_slug(Path(original_name).stem)}.pth")
        else:
            raise InvalidInput("Carica un file .zip (con .pth ed eventuale .index) oppure un singolo .pth.")
        final = models / folder
        os.replace(staging, final)
        return final
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    finally:
        _unlink(src)


async def add_rvc_model(
    db: Database,
    name: Any,
    src: Path,
    original_name: str,
    *,
    description: str = "",
    guild_ids: Sequence[int] = (),
    actor: str = "bot",
) -> dict:
    name = clean_name(name, "Il nome del modello")
    description = (description or "").strip()[:500]

    taken = {r["folder"] for r in await db.fetchall("SELECT folder FROM rvc_models")}
    folder, n = _slug(name), 1
    while folder in taken or (rvc_models_dir() / folder).exists():
        n += 1
        folder = f"{_slug(name)}-{n}"

    final = await asyncio.to_thread(_install_model_files, Path(src), original_name, folder)
    size = await asyncio.to_thread(_dir_size, final)

    def run(conn: sqlite3.Connection) -> int:
        new_id = conn.execute(
            "INSERT INTO rvc_models (name, folder, description, enabled, size, created_at) VALUES (?, ?, ?, 1, ?, ?)",
            (name, folder, description, size, time.time()),
        ).lastrowid
        conn.executemany(
            "INSERT OR IGNORE INTO rvc_model_access (model_id, guild_id) VALUES (?, ?)",
            [(new_id, int(g)) for g in guild_ids],
        )
        _audit(conn, actor, "rvc.add", f"{name} ({size // (1024 * 1024)} MB)")
        return new_id

    try:
        new_id = await db.write(run)
    except BaseException as e:
        await asyncio.to_thread(shutil.rmtree, final, True)
        if isinstance(e, sqlite3.IntegrityError) and _is_unique_violation(e):
            raise Duplicate(f"Esiste già un modello chiamato «{name}».") from e
        raise
    return await get_rvc_model(db, new_id)  # type: ignore[return-value]


async def update_rvc_model(
    db: Database,
    model_id: Any,
    *,
    name: Any = None,
    description: Optional[str] = None,
    enabled: Optional[bool] = None,
    guild_ids: Optional[Sequence[int]] = None,
    actor: str = "bot",
) -> dict:
    number = parse_id(model_id)
    new_name = clean_name(name, "Il nome del modello") if name is not None else None

    def run(conn: sqlite3.Connection) -> int:
        old = conn.execute("SELECT * FROM rvc_models WHERE id = ?", (number,)).fetchone()
        if old is None:
            return 0
        if new_name is not None:
            conn.execute("UPDATE rvc_models SET name = ? WHERE id = ?", (new_name, number))
        if description is not None:
            conn.execute("UPDATE rvc_models SET description = ? WHERE id = ?", (description.strip()[:500], number))
        if enabled is not None:
            conn.execute("UPDATE rvc_models SET enabled = ? WHERE id = ?", (1 if enabled else 0, number))
        if guild_ids is not None:
            conn.execute("DELETE FROM rvc_model_access WHERE model_id = ?", (number,))
            conn.executemany(
                "INSERT OR IGNORE INTO rvc_model_access (model_id, guild_id) VALUES (?, ?)",
                [(number, int(g)) for g in guild_ids],
            )
        _audit(conn, actor, "rvc.update", new_name or old["name"])
        return 1

    try:
        found = number is not None and await db.write(run)
    except sqlite3.IntegrityError as e:
        if _is_unique_violation(e):
            raise Duplicate(f"Esiste già un modello chiamato «{new_name}».") from e
        raise
    if not found:
        raise NotFound("Modello non trovato.")
    return await get_rvc_model(db, number)  # type: ignore[return-value]


async def delete_rvc_model(db: Database, model_id: Any, *, actor: str = "bot") -> dict:
    number = parse_id(model_id)

    def run(conn: sqlite3.Connection) -> Optional[dict]:
        row = conn.execute("SELECT * FROM rvc_models WHERE id = ?", (number,)).fetchone()
        if row is None:
            return None
        conn.execute("DELETE FROM rvc_models WHERE id = ?", (number,))
        _audit(conn, actor, "rvc.delete", row["name"])
        return dict(row)

    row = await db.write(run) if number is not None else None
    if row is None:
        raise NotFound("Modello non trovato.")
    folder = cogs.resolve_in_dir(rvc_models_dir(), row["folder"])
    if folder is not None:
        await asyncio.to_thread(shutil.rmtree, folder, True)
    return row


async def scan_rvc_models(db: Database, *, actor: str = "bot") -> dict:
    """
    Registra le cartelle in models/ che contengono un .pth ma non sono nel database (es. copiate a mano).
    Restituisce i modelli aggiunti e quelli registrati la cui cartella non esiste più.
    """

    def find_folders() -> list[tuple[str, int]]:
        models = rvc_models_dir()
        if not models.is_dir():
            return []
        found = []
        for entry in sorted(models.iterdir()):
            if entry.is_dir() and not entry.name.startswith(".") and any(entry.glob("*.pth")):
                found.append((entry.name, _dir_size(entry)))
        return found

    folders = await asyncio.to_thread(find_folders)

    def run(conn: sqlite3.Connection) -> dict:
        registered = {r["folder"] for r in conn.execute("SELECT folder FROM rvc_models")}
        added = []
        for folder, size in folders:
            if folder in registered:
                continue
            name, n = folder, 1
            while conn.execute("SELECT 1 FROM rvc_models WHERE name = ?", (name,)).fetchone():
                n += 1
                name = f"{folder} ({n})"
            conn.execute(
                "INSERT INTO rvc_models (name, folder, description, enabled, size, created_at) VALUES (?, ?, '', 1, ?, ?)",
                (name, folder, size, time.time()),
            )
            added.append(name)
        on_disk = {f for f, _ in folders}
        missing = [r["name"] for r in conn.execute("SELECT name, folder FROM rvc_models")
                   if r["folder"] not in on_disk]
        if added:
            _audit(conn, actor, "rvc.scan", f"aggiunti: {', '.join(added)}")
        return {"added": added, "missing": missing}

    return await db.write(run)
