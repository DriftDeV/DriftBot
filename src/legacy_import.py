"""
Import una tantum dei vecchi file JSON dentro SQLite.

Prima della dashboard i dati stavano in:
    cogs/data/<server>/soundboard/index.json      {"nome": "file.wav"}
    cogs/data/<server>/speakers/index.json        {"nome": "file.wav"}   (+ alias.json: {"vecchio": "nuovo"})
    cogs/RVC/index.json                           {"nome": "cartella-del-modello"}

Ad ogni avvio si importano i file che esistono ancora; dopo un import riuscito ogni file viene
rinominato in `<nome>.migrated` (mai cancellato), quindi l'operazione non si ripete e i dati originali
restano recuperabili. Un file corrotto viene lasciato dov'è e segnalato nei log. Le voci che puntano a file
inesistenti vengono saltate (e segnalate): nel database finiscono solo contenuti utilizzabili.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

import cogs
import storage
from database import Database

log = logging.getLogger(__name__)

MIGRATED_SUFFIX = ".migrated"


def _read_mapping(path: Path) -> Optional[dict]:
    """Il contenuto del file come dizionario; None se è illeggibile/corrotto (e va lasciato com'è)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError) as e:
        log.warning("File JSON non importabile (lo lascio dov'è): %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        log.warning("File JSON non importabile (non è un oggetto): %s", path)
        return None
    return data


def _guild_dirs(data_dir: Path) -> list[tuple[int, Path]]:
    found = []
    if data_dir.is_dir():
        for entry in sorted(data_dir.iterdir()):
            if entry.is_dir() and entry.name.isdigit():
                found.append((int(entry.name), entry))
    return found


def _collect(data_dir: Path, models_dir: Path, rvc_index: Path) -> dict:
    """Legge i JSON e verifica i file (operazione bloccante: gira in un thread)."""
    sounds, voices, models, files, skipped = [], [], [], [], []

    for guild_id, root in _guild_dirs(data_dir):
        sb_dir = root / "soundboard"
        index = sb_dir / "index.json"
        if index.is_file():
            mapping = _read_mapping(index)
            if mapping is not None:
                files.append(index)
                for name, filename in mapping.items():
                    path = storage.safe_file(sb_dir, str(filename))
                    if path is None:
                        skipped.append(f"suono «{name}» (server {guild_id}): file mancante")
                        continue
                    sounds.append((guild_id, str(name), path.name, path.stat().st_size))

        sp_dir = root / "speakers"
        index = sp_dir / "index.json"
        if index.is_file():
            mapping = _read_mapping(index)
            alias_file = sp_dir / "alias.json"
            aliases = _read_mapping(alias_file) if alias_file.is_file() else {}
            if mapping is not None:
                files.append(index)
                if aliases is None:
                    aliases = {}            # alias corrotto: le voci si importano lo stesso, il file resta dov'è
                elif alias_file.is_file():
                    files.append(alias_file)
                renamed_from = {new: old for old, new in aliases.items() if isinstance(new, str)}
                for name, filename in mapping.items():
                    path = storage.safe_file(sp_dir, str(filename))
                    if path is None:
                        skipped.append(f"voce «{name}» (server {guild_id}): file mancante")
                        continue
                    voices.append((guild_id, str(name), str(renamed_from.get(name, name)), path.name,
                                   storage.wav_duration(path), path.stat().st_size))

    if rvc_index.is_file():
        mapping = _read_mapping(rvc_index)
        if mapping is not None:
            files.append(rvc_index)
            for name, folder in mapping.items():
                path = cogs.resolve_in_dir(models_dir, str(folder))
                if path is None or not path.is_dir():
                    skipped.append(f"modello RVC «{name}»: cartella «{folder}» mancante")
                    continue
                models.append((str(name), path.name, storage._dir_size(path)))

    return {"sounds": sounds, "voices": voices, "models": models, "files": files, "skipped": skipped}


def _insert(conn: sqlite3.Connection, found: dict) -> dict:
    now = time.time()
    done = {"sounds": 0, "voices": 0, "models": 0}
    for guild_id, name, filename, size in found["sounds"]:
        try:
            name = storage.clean_name(name)
        except storage.StorageError:
            log.warning("Suono con nome non valido saltato: %r", name)
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO sounds (guild_id, name, filename, size, created_at) VALUES (?, ?, ?, ?, ?)",
            (guild_id, name, filename, size, now),
        )
        done["sounds"] += cur.rowcount
    for guild_id, name, source, filename, duration, size in found["voices"]:
        try:
            name = storage.clean_name(name)
        except storage.StorageError:
            log.warning("Voce con nome non valido saltata: %r", name)
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO voices (guild_id, name, source_name, filename, duration, size, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, name, source, filename, duration, size, now),
        )
        done["voices"] += cur.rowcount
    for name, folder, size in found["models"]:
        try:
            name = storage.clean_name(name)
        except storage.StorageError:
            log.warning("Modello con nome non valido saltato: %r", name)
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO rvc_models (name, folder, description, enabled, size, created_at)"
            " VALUES (?, ?, '', 1, ?, ?)",
            (name, folder, size, now),
        )
        done["models"] += cur.rowcount
    if any(done.values()):
        storage._audit(
            conn, "import", "legacy.import",
            f"{done['sounds']} suoni, {done['voices']} voci, {done['models']} modelli RVC dai vecchi JSON",
        )
    return done


def _retire(files: list[Path]) -> None:
    for path in files:
        try:
            path.replace(path.with_name(path.name + MIGRATED_SUFFIX))
        except OSError as e:
            log.warning("Impossibile rinominare %s: %s", path, e)


async def import_legacy_json(
    db: Database,
    data_dir: Optional[Path] = None,
    models_dir: Optional[Path] = None,
    rvc_index: Optional[Path] = None,
) -> dict:
    """Importa i vecchi JSON. Restituisce quanti elementi sono stati importati e quali saltati."""
    data_dir = Path(data_dir) if data_dir else Path(cogs.BASE_DATA_DIR)
    models_dir = Path(models_dir) if models_dir else storage.rvc_models_dir()
    rvc_index = Path(rvc_index) if rvc_index else Path(cogs.__file__).parent / "RVC" / "index.json"

    found = await asyncio.to_thread(_collect, data_dir, models_dir, rvc_index)
    done = await db.write(_insert, found)
    # I file si ritirano SOLO dopo il commit: se la scrittura fallisce restano intatti e si riprova al prossimo avvio
    await asyncio.to_thread(_retire, found["files"])

    for line in found["skipped"]:
        log.warning("Import JSON: saltato %s", line)
    if any(done.values()):
        log.info("Import JSON completato: %(sounds)d suoni, %(voices)d voci, %(models)d modelli RVC", done)
    return {**done, "skipped": found["skipped"]}
