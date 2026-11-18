import asyncio
import logging
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import gpu_utils
from cogs import load_json
from cogs.RVC import rvc

log = logging.getLogger(__name__)

CURRDIR = Path(__file__).parent.absolute()

MAX_QUEUE = 10          # richieste massime in coda per tutto il bot
IDLE_DISCONNECT = 30    # secondi di attesa a coda vuota prima di lasciare la vocale


class AICover(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue: asyncio.Queue = asyncio.Queue()
        self.worker_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        self._busy = False  # True mentre il worker elabora o riproduce una richiesta

    async def cog_load(self) -> None:
        rvc.purge_stale_jobs()
        self.worker_task = asyncio.create_task(self.queue_worker())

    async def cog_unload(self) -> None:
        for task in (self.worker_task, self._idle_task):
            if task and not task.done():
                task.cancel()

    async def open_models_list(self) -> dict:
        return load_json(CURRDIR / "RVC" / "index.json")

    async def vc_connect(self, member: discord.Member, guild: discord.Guild) -> Optional[discord.VoiceClient]:
        """Connette (o sposta) il bot nel canale vocale di `member`. Non risponde a nessuna interazione."""
        if not member.voice or member.voice.channel is None:
            return None

        target_channel = member.voice.channel
        vc = guild.voice_client

        try:
            if vc is None:
                vc = await target_channel.connect()
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
            return vc
        except Exception as e:
            log.error("Errore connessione vocale: %s", e)
            return None

    async def _notify(self, interaction: discord.Interaction, **kwargs) -> None:
        """
        Invia un messaggio per questa richiesta senza mai sollevare eccezioni.
        Il token di un'interazione dura 15 minuti, ma una cover può metterci di più (coda inclusa):
        se il followup non funziona più si ripiega sul canale testuale.
        """
        try:
            await interaction.followup.send(**kwargs)
            return
        except discord.HTTPException as e:
            log.debug("followup non disponibile (%s): provo sul canale", e)
        channel = interaction.channel
        if channel is None:
            return
        # Nel canale un embed da solo non notifica nessuno: si cita chi ha fatto la richiesta
        channel_kwargs = dict(kwargs)
        if not channel_kwargs.get("content"):
            channel_kwargs["content"] = interaction.user.mention
        try:
            await channel.send(**channel_kwargs)
        except discord.HTTPException as e:
            log.warning("Impossibile notificare l'utente: %s", e)

    async def model_autocomplete(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        try:
            models = await self.open_models_list()
        except Exception as e:
            log.warning("Autocomplete modelli fallito: %s", e)
            return []
        return [app_commands.Choice(name=name[:100], value=filename[:100]) for name, filename in models.items() if current.lower() in name.lower()][:25]

    @app_commands.command(name="ai-cover", description="Crea una cover AI della tua canzone preferita")
    @app_commands.describe(
        url="Il link del video (YouTube e altri siti)",
        model="Chi deve cantare la canzone",
        pitch="Trasposizione in semitoni (default 0)",
    )
    @app_commands.autocomplete(model=model_autocomplete)
    @app_commands.choices(
    pitch = [
        app_commands.Choice(name="+12", value=12),
        app_commands.Choice(name="0", value=0),
        app_commands.Choice(name="-12", value=-12)
    ])
    async def ai_cover(self, interaction: discord.Interaction, url: str, model: str, pitch : int = 0):
        # Controllo iniziale voce
        if not interaction.user.voice or interaction.user.voice.channel is None:
            return await interaction.response.send_message("❌ Devi essere in un canale vocale!", ephemeral=True)

        # Validazione input (URL http(s) e modello dentro la cartella dei modelli)
        try:
            url = rvc.validate_url(url)
            rvc.resolve_model(model)
        except rvc.CoverError as e:
            return await interaction.response.send_message(f"❌ {e}", ephemeral=True)

        if self.queue.qsize() >= MAX_QUEUE:
            return await interaction.response.send_message(
                "⏳ La coda è piena, riprova tra qualche minuto.", ephemeral=True
            )

        # Defer (necessario perché l'operazione dura più di 3 secondi).
        # La connessione vocale avviene nel worker, quando tocca a questa richiesta:
        # connettersi qui sposterebbe il bot a metà della canzone di qualcun altro.
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
            title="✅ In coda!",
            description="Sei in coda, aspetta il tuo turno!",
            color=discord.Color.yellow()
        )
        embed.add_field(name="Posizione", value=f"{pos}")
        embed.add_field(name="Modello", value=f"{model}")
        await self._notify(interaction, embed=embed)

    async def queue_worker(self) :
        while True :
            item = await self.queue.get()
            self._busy = True
            try:
                await self._process(item)
            except asyncio.CancelledError:
                raise
            except rvc.CoverError as e:
                await self._notify(
                    item["interaction"],
                    content=f"❌ {item['interaction'].user.mention} {e}",
                )
            except Exception as e:
                log.exception("Errore nel worker AI cover")
                if gpu_utils.is_out_of_memory(e):
                    text = "memoria GPU esaurita: riprova con una canzone più corta."
                else:
                    text = "errore imprevisto durante la generazione della cover."
                await self._notify(
                    item["interaction"],
                    content=f"❌ Errore con la richiesta di {item['interaction'].user.mention}: {text}",
                )
            finally:
                # Pulizia GPU (CUDA e ROCm) e segnalazione fine task
                self._busy = False
                gpu_utils.free_gpu_memory()
                self.queue.task_done()

            if self.queue.empty():
                self._schedule_idle_disconnect(item["interaction"].guild)

    async def _process(self, item: dict) -> None:
        interaction: discord.Interaction = item["interaction"]
        guild = interaction.guild
        user = interaction.user

        # 1. Connessione/Controllo VC
        vc = await self.vc_connect(user, guild)
        if not vc:
            await self._notify(
                interaction,
                content=f"⚠️ {user.mention} non sono riuscito a connettermi al tuo canale vocale. Salto...",
            )
            return

        # 2. Generazione AI (Operazione pesante, in un thread)
        embed = discord.Embed(
            title="🎙️ Generazione in corso...",
            description="Generazione in corso, Attendi ci vorra un po...",
            color=discord.Color.blue()
        )
        embed.add_field(name="Utente", value=f"{user.mention}")
        await self._notify(interaction, embed=embed)

        output_path = await rvc.ai_cover(interaction.guild_id, item["model"], item["url"], item["Pitch"])
        try:
            if not output_path.exists():
                raise FileNotFoundError("File audio non trovato.")

            # 3. Riproduzione e Attesa. La generazione può essere durata minuti: ricontrollo la vocale.
            vc = await self.vc_connect(user, guild)
            if not vc:
                await self._notify(
                    interaction,
                    content=f"⚠️ {user.mention} la cover è pronta ma non sei più in un canale vocale.",
                )
                return

            if vc.is_playing():
                vc.stop()

            # Evento per capire quando la canzone finisce
            loop = asyncio.get_running_loop()
            play_done = asyncio.Event()

            def after_playing(error):
                if error:
                    log.error("Errore riproduzione: %s", error)
                # Segnala che la riproduzione è finita
                loop.call_soon_threadsafe(play_done.set)

            vc.play(discord.FFmpegPCMAudio(str(output_path)), after=after_playing)

            embed = discord.Embed(
                title="🎶Riproduzione in Corso!",
                color=discord.Color.green()
            )
            embed.add_field(name="Modello", value=f"{item['model']}")
            embed.add_field(name="Richiesto da", value=f"{user.mention}")
            await self._notify(interaction, embed=embed)

            # ASPEPTA che la canzone finisca prima di passare al prossimo elemento della coda
            # (con un limite: se `after` non scattasse mai la coda non deve bloccarsi per sempre)
            try:
                await asyncio.wait_for(play_done.wait(), timeout=rvc.MAX_SONG_SECONDS + 60)
            except asyncio.TimeoutError:
                log.warning("Timeout in attesa della fine della riproduzione")
                if vc.is_connected():
                    vc.stop()
        finally:
            rvc.cleanup_job(output_path)

    def _schedule_idle_disconnect(self, guild: Optional[discord.Guild]) -> None:
        if guild is None:
            return
        if self._idle_task and not self._idle_task.done():
            self._idle_task.cancel()
        self._idle_task = asyncio.create_task(self._idle_disconnect(guild))

    async def _idle_disconnect(self, guild: discord.Guild) -> None:
        # Aspetta qualche secondo prima di disconnettersi, senza bloccare il worker
        try:
            await asyncio.sleep(IDLE_DISCONNECT)
        except asyncio.CancelledError:
            return
        vc = guild.voice_client
        # Non lasciare la vocale se nel frattempo c'è altro audio (es. musica) o una nuova richiesta
        if self.queue.empty() and not self._busy and vc and vc.is_connected() and not vc.is_playing():
            try:
                await vc.disconnect()
            except Exception as e:
                log.warning("Disconnessione per inattività fallita: %s", e)

    @app_commands.command(name="skip", description="Salta la canzone attualmente in riproduzione")
    async def skip(self, interaction: discord.Interaction):
            # Se sta suonando musica (cog Music) salta quella traccia
            music = self.bot.get_cog("Music")
            if music is not None and await music.skip_if_active(interaction):
                return

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
            if self.queue.empty():
                embed = discord.Embed(
                    title="⏭️ Canzone saltata!",
                    description="Non ci sono altre richieste in coda.",
                    color=discord.Color.blue()
                )
            else:
                embed = discord.Embed(
                    title="⏭️ Canzone saltata! Passo alla prossima...",
                    color=discord.Color.blue()
                )
            await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AICover(bot))
