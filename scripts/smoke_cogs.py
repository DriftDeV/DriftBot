#!/usr/bin/env python3
"""
Verifica che il bot sia operativo con le dipendenze VERE installate: importa le librerie pesanti, carica tutti i cog
come fa main.py e controlla che i comandi slash attesi siano registrati. Non si collega a Discord e non scarica modelli.

    python scripts/smoke_cogs.py            # esce con 0 se è tutto a posto, con 1 e l'elenco dei problemi altrimenti

Lo usano il workflow .github/workflows/install-and-container.yml (venv e container) e i test (con i moduli finti di
tests/conftest.py al posto di torch e delle altre librerie pesanti).
"""

import asyncio
import sys
from pathlib import Path

# src/ sta accanto alla cartella dello script (repository) oppure accanto allo script stesso (copiato in /app nel container)
_HERE = Path(__file__).resolve().parent
SRC = next(c for c in (_HERE.parent / "src", _HERE / "src") if c.is_dir())
sys.path.insert(0, str(SRC))

# Un comando mancante qui significa che un cog non si è caricato o che è stato rinominato senza aggiornare i test.
EXPECTED_COMMANDS = {
    "ai-cover", "ai-music", "leave", "new-speaker", "pause", "ping", "play", "rename-speaker", "resume",
    "setvolume", "skip", "soundboard", "stop", "tts", "tts-ai", "tts-stop",
}


async def run() -> list[str]:
    """Restituisce l'elenco dei problemi (vuoto = tutto ok)."""
    import discord
    from discord.ext import commands

    problems: list[str] = []

    # Le librerie pesanti devono importarsi per davvero: il bot altrimenti parte lo stesso, ma senza TTS/RVC.
    import cogs.TTS_COG as tts_cog
    if tts_cog.torch is None:
        problems.append("torch/torchaudio non importabili: /tts-ai e /ai-cover girerebbero senza GPU né modelli")
    if tts_cog.ChatterboxMultilingualTTS is None:
        problems.append("chatterbox-tts non importabile: /tts-ai non funzionerebbe")
    # Il cog scarica e carica il modello TTS appena viene aggiunto: qui non serve (sono GB da Hugging Face).
    tts_cog.ChatterboxMultilingualTTS = None

    bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
    modules = sorted(p.stem for p in (SRC / "cogs").glob("*.py") if not p.name.startswith("_"))
    for module in modules:
        try:
            await bot.load_extension(f"cogs.{module}")
        except Exception as e:                      # un cog rotto non deve nascondere gli altri
            problems.append(f"cog {module}: {type(e).__name__}: {e}")

    names = {command.name for command in bot.tree.get_commands()}
    for missing in sorted(EXPECTED_COMMANDS - names):
        problems.append(f"comando /{missing} non registrato")
    print(f"{len(bot.cogs)} cog caricati, {len(names)} comandi: {', '.join(sorted(names))}")

    for module in modules:
        try:
            await bot.unload_extension(f"cogs.{module}")
        except Exception:
            pass                                    # non caricato: già segnalato sopra
    await bot.close()
    return problems


def main() -> int:
    problems = asyncio.run(run())
    for problem in problems:
        print(f"❌ {problem}")
    print("✅ Cog operativi" if not problems else f"❌ {len(problems)} problemi")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
