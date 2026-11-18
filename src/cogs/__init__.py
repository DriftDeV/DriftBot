"""
Discord Bot Cogs Package
This module initializes the cogs system for the Discord bot.
"""

from discord.ext import commands
import json
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

BASE_DATA_DIR = Path(__file__).parent.absolute() / "data"

async def get_guild_dir(guild_id: int, subfolder: str) -> Path:
    """Restituisce il percorso della sottocartella per un server specifico."""
    path = BASE_DATA_DIR / str(guild_id) / subfolder
    path.mkdir(parents=True, exist_ok=True) # Crea la cartella se manca
    return path

async def get_guild_json(guild_id: int, subfolder: str, json_name : str = "index.json") -> Path:
    """Restituisce il percorso del file JSON e lo inizializza se vuoto."""
    path = await get_guild_dir(guild_id, subfolder) / json_name
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            json.dump({}, f)
    return path

def load_json(path: Path, default: Optional[dict] = None) -> dict:
    """Legge un file JSON (oggetto). Se manca, è corrotto o non è un oggetto restituisce `default`."""
    fallback = {} if default is None else default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:  # ValueError include JSONDecodeError
        log.warning("Impossibile leggere %s: %s", path, e)
        return fallback
    if not isinstance(data, dict):
        log.warning("%s non contiene un oggetto JSON", path)
        return fallback
    return data


def save_json(path: Path, data: Any) -> None:
    """Scrive un JSON in modo atomico: un crash a metà non lascia un file troncato."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def escape_md(text: str) -> str:
    """
    Rende innocuo il markdown di Discord in un testo che non scriviamo noi (titoli di YouTube, testi
    di canzoni...): `**`, `_`, `` ` ``, `~`, `|`, `>` e `\\` verrebbero interpretati e rovinerebbero il messaggio.
    Le menzioni (@everyone, ruoli) sono già bloccate da `allowed_mentions` del bot.
    """
    return re.sub(r"([*_`~|>\\])", r"\\\1", text)


def resolve_in_dir(base: Path, name: str) -> Optional[Path]:
    """
    Unisce `base` e `name` solo se il risultato resta dentro `base`.
    Protegge dai path traversal ("../../etc/passwd", percorsi assoluti, ecc.)
    quando `name` arriva dall'utente. Restituisce None se il percorso non è valido.
    """
    try:
        base_resolved = Path(base).resolve()
        candidate = (base_resolved / name).resolve()
    except (ValueError, OSError):
        return None
    if candidate == base_resolved or base_resolved not in candidate.parents:
        return None
    return candidate


async def setup(bot: commands.Bot) -> None:
    """
    Setup function for the cogs package.
    This is called automatically by discord.py when loading the extension.

    Args:
        bot: The Discord bot instance
    """
    pass
