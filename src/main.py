import discord
import os
import asyncio
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True  # Necessario per voice channels
intents.guilds = True

class MyBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix='!', # Il prefisso serve comunque per comandi admin/sync manuali
            intents=intents,
            help_command=None
        )

    async def setup_hook(self):
        # 1. Carica i Cogs
        print("--- Caricamento Cogs ---")
        for filename in os.listdir('./src/cogs'):
            if filename.endswith('.py'):
                await self.load_extension(f'cogs.{filename[:-3]}')
                print(f'Caricato: {filename}')

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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
