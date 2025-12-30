"""
Discord Bot Cogs Package
This module initializes the cogs system for the Discord bot.
"""

from discord.ext import commands
import asyncio
from pathlib import Path
import json

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

async def setup(bot: commands.Bot) -> None:
    """
    Setup function for the cogs package.
    This is called automatically by discord.py when loading the extension.

    Args:
        bot: The Discord bot instance
    """
    pass
