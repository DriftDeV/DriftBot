import asyncio
import logging
import os
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

import gpu_utils  # noqa: E402  (deve venire dopo load_dotenv: legge le variabili del .env)

# Va impostato prima che la GPU venga inizializzata da uno qualsiasi dei cog.
gpu_utils.configure_allocator()

log = logging.getLogger("driftbot")

TOKEN = os.getenv('DISCORD_TOKEN')
COGS_DIR = Path(__file__).parent / "cogs"

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # Necessario per voice channels
intents.guilds = True


async def reply_ephemeral(interaction: discord.Interaction, text: str) -> None:
    """Risponde a un'interazione con un messaggio privato, senza mai sollevare eccezioni."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException as e:
        # Interazione scaduta (>3s senza defer, >15min dopo) o già gestita: nulla da fare.
        log.debug("Impossibile rispondere all'interazione: %s", e)


class BotTree(app_commands.CommandTree):
    """CommandTree con controllo globale ed error handler per tutti gli slash command."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Tutti i comandi usano server, canali vocali e cartelle per-server: niente DM.
        if interaction.guild is None:
            await reply_ephemeral(interaction, "❌ Questo comando funziona solo in un server.")
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CheckFailure):
            # Se il check ha già risposto (es. interaction_check) non rispondiamo due volte.
            if not interaction.response.is_done():
                if isinstance(error, app_commands.MissingPermissions):
                    await reply_ephemeral(interaction, "❌ Non hai i permessi per usare questo comando.")
                elif isinstance(error, app_commands.CommandOnCooldown):
                    await reply_ephemeral(interaction, f"⏳ Riprova tra {error.retry_after:.0f} secondi.")
                else:
                    await reply_ephemeral(interaction, "❌ Non puoi usare questo comando qui.")
            return

        command = interaction.command.qualified_name if interaction.command else "?"
        log.error("Errore non gestito nel comando /%s", command, exc_info=getattr(error, "original", error))
        await reply_ephemeral(interaction, "❌ Si è verificato un errore imprevisto. Riprova tra poco.")


class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!', # Il prefisso serve comunque per comandi admin/sync manuali
            intents=intents,
            help_command=None,
            tree_cls=BotTree,
            # Il bot ripete testo scritto dagli utenti (/tts-ai) o preso dal web (titoli di /play):
            # blocca @everyone/@here e i ruoli, lascia solo i ping agli utenti.
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
        )

    async def setup_hook(self):
        # 1. Carica i Cogs. Un cog che non si carica (es. dipendenza mancante o libreria GPU
        #    non compatibile) non deve impedire agli altri di funzionare.
        print("--- Caricamento Cogs ---")
        failed = []
        for path in sorted(COGS_DIR.glob('*.py')):
            if path.name.startswith('_'):
                continue
            try:
                await self.load_extension(f'cogs.{path.stem}')
                print(f'Caricato: {path.name}')
            except Exception:
                failed.append(path.name)
                log.exception("Impossibile caricare il cog %s", path.name)
        if failed:
            print(f"⚠️  Cog NON caricati: {', '.join(failed)} (vedi errori sopra)")

        # 2. Sincronizza i comandi Slash (Tree Sync)
        # NOTA: In produzione, evita di fare il sync globale ad ogni avvio per non essere limitato da Discord.
        # Per ora, per testare, va bene qui.
        print("--- Sincronizzazione Comandi ---")
        try:
            synced = await self.tree.sync()
            print(f"Sincronizzati {len(synced)} comandi slash.")
        except Exception as e:
            print(f"Errore nel sync: {e}")



    async def on_ready(self):
        update_log = '''
        ----Bot pornto all'uso! ---
        --- AGGIORNAMENTO! ---
        + Aggiunta la coda per ai-cover
        + Miglioramenti alla gestione multiserver per ai-cover
        + Bug fix e miglioramenti
        '''
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Game(name="IL BOT E' ONLINE!", extra=update_log)

        )
        print(f'Loggato come {self.user} (ID: {self.user.id})')

async def main():
    bot = MyBot()
    async with bot:
        await bot.start(TOKEN)

if __name__ == '__main__':
    discord.utils.setup_logging(level=logging.INFO)
    if not TOKEN:
        sys.exit("❌ DISCORD_TOKEN mancante: crea un file .env con DISCORD_TOKEN=il_tuo_token")
    log.info("Dispositivo di calcolo: %s", gpu_utils.describe())
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except discord.LoginFailure:
        sys.exit("❌ Token Discord non valido: controlla DISCORD_TOKEN nel file .env")
