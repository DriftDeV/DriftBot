"""Discord TTS Cog using Chatterbox for voice cloning."""

import asyncio
import os
import tempfile
import uuid
from datetime import datetime
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import gpu_utils
from cogs import get_guild_dir, get_guild_json, load_json, resolve_in_dir

# torch/torchaudio/chatterbox sono opzionali all'import: se mancano o non si caricano
# (es. libreria GPU incompatibile) il cog si carica lo stesso e /speak risponde con un errore chiaro.
try:
    import torch
    import torchaudio as ta
except Exception as e:  # ImportError o errore di caricamento librerie GPU
    print(f"Error importing torch/torchaudio: {e}")
    torch = None
    ta = None

# Import Chatterbox after ensuring proper initialization
try:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
except Exception as e:
    print(f"Error importing Chatterbox: {e}")
    ChatterboxMultilingualTTS = None

MAX_TEXT_CHARS = 500

# Reference text mapping for voice cloning
REF_TEXT_MAPPING = {
    "fronci.wav": "Ciao, questa è la voce di Fronci per il test.",
    "miku.wav": "Konichiwa, watashi wa Hatsune Miku desu.",
    "toni.wav": "Ciao sono Antonella.",
    "chief.wav": "Master Chief, pronto all'azione.",
    "giorgio.wav": "Mi chiamo Giorgio.",
}


class TTSCog(commands.Cog):
    """Cog for Text-to-Speech generation using Chatterbox."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # "cuda" vale sia per NVIDIA che per AMD ROCm (stessa API in PyTorch)
        self.device = gpu_utils.get_device()
        self.model: Optional["ChatterboxMultilingualTTS"] = None
        self._model_lock = asyncio.Lock()
        self._generate_lock = asyncio.Lock()  # una sola generazione alla volta sulla GPU
        self._init_task: Optional[asyncio.Task] = None

        # Salvo torch.load originale PRIMA di un eventuale patch (ripristinato in cog_unload)
        self.original_torch_load = torch.load if torch is not None else None
        self._torch_load_patched = False

    async def cog_load(self) -> None:
        # Inizializza il modello in background all'avvio
        self._init_task = asyncio.create_task(self._async_init_model())

    async def cog_unload(self) -> None:
        if self._init_task and not self._init_task.done():
            self._init_task.cancel()
        if self._torch_load_patched and torch is not None:
            torch.load = self.original_torch_load
            self._torch_load_patched = False
        self.model = None
        gpu_utils.free_gpu_memory()

    def log(self, message: str, level: str = "INFO") -> None:
        """Log messages with timestamp and emoji."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        icons = {
            "INFO": "ℹ️",
            "SUCCESS": "✅",
            "WARNING": "⚠️",
            "ERROR": "❌",
            "PROCESS": "🔄",
            "AUDIO": "🔊",
            "GPU": "🔥",
        }
        icon = icons.get(level, "📝")
        print(f"[{timestamp}] {icon} [{level:<7}] -> {message}")

    def patched_torch_load(self, *args, **kwargs):
        # Usa la funzione originale salvata, NON torch.load (che è quella patchata)
        if 'map_location' not in kwargs:
            kwargs['map_location'] = torch.device(self.device)
        return self.original_torch_load(*args, **kwargs)

    async def get_speaker_name(self, filename, interaction : discord.Interaction) -> str :
        speakers_json = await get_guild_json(interaction.guild_id, "speakers")
        current_speakers = load_json(speakers_json)
        speaker_found = ""
        for speaker, value in current_speakers.items() :
            if value == filename :
                speaker_found = speaker
        return speaker_found

    async def autocomplete_speakers(
            self,
            interaction : discord.Interaction,
            current : str,
    ) -> list[app_commands.Choice[str]]:
        try:
            speakers_json = await get_guild_json(interaction.guild_id, "speakers")
            current_speakers = load_json(speakers_json)
        except Exception as e:
            self.log(f"Autocomplete speakers fallito: {e}", "WARNING")
            return []

        return [app_commands.Choice(name=name[:100], value=filename[:100])
            for name, filename in current_speakers.items()
            if current.lower() in name.lower()][:25]

    async def _async_init_model(self) -> None:
        """Initialize the TTS model asynchronously."""
        self.log(f"[TORCH] {gpu_utils.describe()}", "INFO")
        if torch is None or ChatterboxMultilingualTTS is None:
            self.log("Chatterbox/torch non disponibili: /speak disattivato", "ERROR")
            return

        if self.device == "cpu" or self.device.startswith("mps"):
            # Su CPU/MPS i checkpoint salvati su GPU vanno rimappati sul device corretto
            torch.load = self.patched_torch_load
            self._torch_load_patched = True

        try:
            self.log(f"Initializing TTS model on {self.device}...", "PROCESS")
            async with self._model_lock:
                self.model = await asyncio.to_thread(self._init_model_sync)
            self.log("TTS model initialized successfully", "SUCCESS")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if gpu_utils.is_out_of_memory(e):
                self.log("VRAM insufficiente per caricare il modello TTS", "ERROR")
            else:
                self.log(f"Failed to initialize model: {e}", "ERROR")
            gpu_utils.free_gpu_memory()

    def _init_model_sync(self) -> "ChatterboxMultilingualTTS":
        """Synchronous model initialization."""
        return ChatterboxMultilingualTTS.from_pretrained(device=self.device)

    def _generate_sync(self, text: str, output_audio: str, target_audio: str, language: str) -> None:
        """Generazione bloccante (GPU): va eseguita in un thread, mai nell'event loop."""
        wav = self.model.generate(text, audio_prompt_path=target_audio, language_id=language)
        # torchaudio.save richiede un tensore su CPU (con CUDA/ROCm il tensore potrebbe essere sulla GPU)
        ta.save(output_audio, wav.detach().cpu(), self.model.sr)

    async def generate_audio(
        self,
        text: str,
        output_audio: str,
        target_audio: str,
        speaker_name: str,
        language : str
    ) -> Optional[str]:
        """
        Genera l'audio. Restituisce None se è andato a buon fine, altrimenti un messaggio
        d'errore da mostrare all'utente.
        """
        try:
            self.log(f"Generating audio for speaker: {speaker_name}", "PROCESS")
            async with self._generate_lock:
                await asyncio.to_thread(self._generate_sync, text, output_audio, target_audio, language)
            self.log(f"Audio generated successfully for {speaker_name}", "SUCCESS")
            return None

        except Exception as e:
            self.log(f"Error generating audio: {e}", "ERROR")
            if gpu_utils.is_out_of_memory(e):
                return "❌ Memoria GPU esaurita. Riprova con un testo più corto o tra qualche istante."
            return "❌ Error creating audio. Try different text or speaker."
        finally:
            gpu_utils.free_gpu_memory()

    @staticmethod
    def _remove_file(path: str) -> None:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError:
            pass

    @app_commands.command(
        name="speak",
        description="Generate speech from text using AI voice cloning",
    )
    @app_commands.describe(
        testo="What should I say?",
        speaker="Which voice should speak?",
        lang = "La Linuga"
    )
    @app_commands.autocomplete(speaker=autocomplete_speakers)
    @app_commands.choices(
        lang = [
            app_commands.Choice(name="Italiano", value="it"),
            app_commands.Choice(name="Inglese", value="en")
        ])
    async def speak(
        self,
        interaction: discord.Interaction,
        testo: app_commands.Range[str, 1, MAX_TEXT_CHARS],
        speaker: str,
        lang : str = "it") :
        """Generate and play TTS audio in a voice channel."""
        # Preliminary checks
        if self.model is None:
            await interaction.response.send_message(
                "❌ TTS system is not ready. Check the console.",
                ephemeral=True,
            )
            return

        if not interaction.user.voice or interaction.user.voice.channel is None:
            await interaction.response.send_message(
                "❌ You must be in a voice channel!",
                ephemeral=True,
            )
            return

        if not testo.strip():
            await interaction.response.send_message("❌ Il testo è vuoto.", ephemeral=True)
            return

        # Setup and defer response
        speaker_dir = await get_guild_dir(interaction.guild_id, "speakers")
        await interaction.response.defer()
        target_channel = interaction.user.voice.channel
        language = lang
        speaker_name = await self.get_speaker_name(speaker, interaction) or speaker

        # Verify speaker file exists (e non esce dalla cartella degli speaker)
        speaker_path = resolve_in_dir(speaker_dir, speaker)
        if speaker_path is None or not speaker_path.is_file():
            self.log(f"Missing/invalid speaker file: {speaker!r}", "ERROR")
            await interaction.followup.send(
                "❌ Configuration error: speaker file not found."
            )
            return

        # Voice connection management
        vc = interaction.guild.voice_client
        try:
            if vc is None:
                vc = await target_channel.connect()
                self.log(f"Connected to: {target_channel.name}", "INFO")
            elif vc.channel.id != target_channel.id:
                await vc.move_to(target_channel)
                self.log(f"Moved to: {target_channel.name}", "INFO")
        except Exception as e:
            self.log(f"Voice connection error: {e}", "ERROR")
            await interaction.followup.send(
                "❌ Cannot connect to voice channel."
            )
            return

        # Generate audio
        file_out = os.path.join(tempfile.gettempdir(), f"tts_{uuid.uuid4()}.wav")
        testo_stripped = testo.strip()
        self.log(
            f"Starting generation: '{testo_stripped}' (speaker: {speaker_name})",
            "PROCESS",
        )

        error_message = await self.generate_audio(
            testo_stripped,
            file_out,
            str(speaker_path),
            speaker_name,
            language
        )

        if error_message:
            self._remove_file(file_out)
            await interaction.followup.send(error_message)
            return

        # La generazione può durare a lungo: il bot potrebbe essere stato disconnesso nel frattempo
        vc = interaction.guild.voice_client
        if vc is None or not vc.is_connected():
            self._remove_file(file_out)
            await interaction.followup.send("❌ Sono stato disconnesso dal canale vocale durante la generazione.")
            return

        # Play audio
        try:
            if vc.is_playing():
                vc.stop()

            self.log(f"Playing file: {file_out}", "AUDIO")
            source = discord.FFmpegPCMAudio(file_out)

            def after_playback(error):
                """Callback executed after playback."""
                if error:
                    self.log(f"Playback error: {error}", "ERROR")

                # Clean up temporary file
                self._remove_file(file_out)
                self.log(f"Temporary file removed: {file_out}", "INFO")

            vc.play(source, after=after_playback)
            await interaction.followup.send(
                f"🗣️ **{speaker_name}**: {testo_stripped}",
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except Exception as e:
            self.log(f"Playback error: {e}", "ERROR")
            self._remove_file(file_out)
            await interaction.followup.send("⚠️ Playback error: impossibile riprodurre l'audio (FFmpeg installato?).")

    @app_commands.command(
        name="leave",
        description="Disconnect the bot from the voice channel",
    )
    async def disconnetti(self, interaction: discord.Interaction) -> None:
        """Disconnect the bot from voice channel."""
        vc = interaction.guild.voice_client
        if vc:
            try:
                await vc.disconnect()
            except Exception as e:
                self.log(f"Disconnect error: {e}", "ERROR")
                await interaction.response.send_message("❌ Errore durante la disconnessione.", ephemeral=True)
                return
            await interaction.response.send_message("👋 Disconnected.")
            self.log("Bot disconnected manually.", "INFO")
        else:
            await interaction.response.send_message(
                "❌ Not connected to any voice channel.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    """Setup function to load the cog."""
    await bot.add_cog(TTSCog(bot))
