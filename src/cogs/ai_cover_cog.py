import discord
import os
import torch
import asyncio
from pathlib import Path
from discord.ext import commands
from discord import app_commands
import json
from cogs.RVC import rvc

CURRDIR = Path(__file__).parent.absolute()

class AICover(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = asyncio.Queue()
        self.is_processing = False
        self.worker_task = self.bot.loop.create_task(self.queue_worker())

    async def open_models_list(self):
        models_json = CURRDIR / "RVC" / "index.json"
        with open(models_json, "r", encoding="utf-8") as f:
            return json.load(f)

    async def vc_connect(self, interaction: discord.Interaction):
        if not interaction.user.voice:
            # Qui usiamo response perché non c'è ancora un defer
            await interaction.response.send_message("❌ Devi essere in un canale vocale!", ephemeral=True)
            return None

        target_channel = interaction.user.voice.channel
        vc = interaction.guild.voice_client

        try:
            if vc is None:
                vc = await target_channel.connect()
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
            return vc
        except Exception as e:
            print(f"Errore connessione vocale: {e}")
            return None

    async def model_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        models = await self.open_models_list()
        return [app_commands.Choice(name=name, value=filename) for name, filename in models.items() if current.lower() in name.lower()][:25]

    @app_commands.command(name="ai-cover", description="crea una cover ai della tua canzone preferita")
    @app_commands.describe(url="il link del video youtube", model="da chi vuoi far cantare la canzone", pitch="Trasposizione Default 0")
    @app_commands.autocomplete(model=model_autocomplete)
    @app_commands.choices(
    pitch = [
        app_commands.Choice(name="+12", value=12),
        app_commands.Choice(name="0", value=0),
        app_commands.Choice(name="-12", value=-12)
    ])
    async def ai_cover(self, interaction: discord.Interaction, url: str, model: str, pitch : int = 0):
        # Controllo iniziale voce
        if not interaction.user.voice:
            return await interaction.response.send_message("❌ Devi essere in un canale vocale!", ephemeral=True)

        # 1. Connessione Vocale
        vc = await self.vc_connect(interaction)
        if not vc:
            return

        # 2. Defer (necessario perché l'operazione dura più di 3 secondi)
        await interaction.response.defer()

        item = {
            "interaction": interaction,
            "url": url,
            "model": model,
            "Pitch": pitch
        }

        await self.queue.put(item)
        pos = self.queue.qsize()
        embed = discord.Embed(
            title=f"✅ In coda!",
            description="Sei in coda, aspetta il tuo turno!",
            color=discord.Color.yellow()
        )
        embed.add_field(name="Posizione", value=f"{pos}")
        embed.add_field(name="Modello", value=f"{model}")
        await interaction.followup.send(embed=embed)

    async def queue_worker(self) :
        while True :
            item = await self.queue.get()
            interaction = item["interaction"]
            url = item["url"]
            model = item["model"]
            pitch = item["Pitch"]
            try:
                # 1. Connessione/Controllo VC
                vc = await self.vc_connect(interaction)
                if not vc:
                    await interaction.followup.send("⚠️ Non sono riuscito a connettermi al canale vocale. Salto...")
                    continue

                # 2. Generazione AI (Operazione pesante)
                embed = discord.Embed(
                    title=f"🎙️ Generazione in corso...",
                    description="Generazione in corso, Attendi ci vorra un po...",
                    color=discord.Color.blue()
                )
                embed.add_field(name="Utente", value=f"{interaction.user.mention}")
                await interaction.followup.send(embed=embed)

                output_path = await rvc.ai_cover(interaction, model, url, pitch)

                if not os.path.exists(output_path):
                    raise FileNotFoundError(f"File audio non trovato.")

                # 3. Riproduzione e Attesa
                if vc.is_playing():
                    vc.stop()

                # Evento per capire quando la canzone finisce
                play_done = asyncio.Event()

                def after_playing(error):
                    if error:
                        print(f"Errore riproduzione: {error}")
                    # Segnala che la riproduzione è finita
                    self.bot.loop.call_soon_threadsafe(play_done.set)

                source = discord.FFmpegPCMAudio(output_path)
                vc.play(source, after=after_playing)

                embed = discord.Embed(
                    title="🎶Riproduzione in Corso!",
                    color=discord.Color.green()
                )
                embed.add_field(name="Modello", value=f"{model}")
                embed.add_field(name="Richiesto da", value=f"{interaction.user.mention}")
                await interaction.followup.send(embed=embed)

                # ASPEPTA che la canzone finisca prima di passare al prossimo elemento della coda
                await play_done.wait()

                if self.queue.empty():
                    # Aspetta magari 30 secondi prima di disconnettersi
                    await asyncio.sleep(30)
                    if self.queue.empty() and vc.is_connected():
                        await vc.disconnect()

            except Exception as e:
                print(f"Errore nel worker: {e}")
                try:
                    await interaction.followup.send(f"❌ Errore con la richiesta di {interaction.user.mention}: {e}")
                except: pass
            finally:
                # Pulizia GPU e segnalazione fine task
                torch.cuda.empty_cache()
                self.queue.task_done()

    @app_commands.command(name="skip", description="Salta la canzone attualmente in riproduzione")
    async def skip(self, interaction: discord.Interaction):
            vc = interaction.guild.voice_client

            # 1. Controlla se il bot è connesso e sta riproducendo qualcosa
            if not vc or not vc.is_playing():
                return await interaction.response.send_message("❌ Non c'è nessuna canzone in riproduzione al momento.", ephemeral=True)

            # 2. Controlla se l'utente è nello stesso canale vocale del bot
            if not interaction.user.voice or interaction.user.voice.channel.id != vc.channel.id:
                return await interaction.response.send_message("❌ Devi essere nel mio stesso canale vocale per usare questo comando!", ephemeral=True)

            # 3. Interrompi la riproduzione
            # Questo attiverà automaticamente la funzione 'after_playing' nel worker
            vc.stop()
            embed = discord.Embed(
                title="⏭️ Canzone saltata! Passo alla prossima..",
                color=discord.Color.blue()
            )
            await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICover(bot))
