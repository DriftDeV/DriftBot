"""
Discord Bot Cogs Package
This module initializes the cogs system for the Discord bot.
"""

from discord.ext import commands
import re
from pathlib import Path
from typing import Optional

# Cartella dei file dei server (suoni, campioni delle voci). L'elenco di cosa c'è dentro sta in SQLite:
# vedi src/database.py e src/storage.py.
BASE_DATA_DIR = Path(__file__).parent.absolute() / "data"

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
