"""Carica TUTTI i cog insieme, come fa main.py: nessun conflitto di nomi tra i comandi slash."""

from pathlib import Path

import discord
from discord.ext import commands

COGS_DIR = Path(__file__).resolve().parent.parent / "src" / "cogs"


async def test_every_cog_loads_and_command_names_are_unique():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    modules = sorted(p.stem for p in COGS_DIR.glob("*.py") if not p.name.startswith("_"))
    assert "ace_step_cog" in modules and "music" in modules

    for module in modules:
        # una collisione (es. due cog con /skip) solleverebbe CommandAlreadyRegistered
        await bot.load_extension(f"cogs.{module}")

    names = [command.name for command in bot.tree.get_commands()]
    assert len(names) == len(set(names))
    assert {"ai-music", "play", "skip", "tts-ai", "ai-cover", "soundboard", "ping", "tts", "tts-stop", "pause", "resume", "stop", "setvolume"} <= set(names)

    for module in modules:
        await bot.unload_extension(f"cogs.{module}")
    await bot.close()
