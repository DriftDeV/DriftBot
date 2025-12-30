"""Discord TTS Cog using Chatterbox for voice cloning."""

import asyncio
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from cogs import get_guild_dir, get_guild_json
import discord
import torch
import torchaudio as ta
from discord import app_commands
from discord.ext import commands

import json

# Import Chatterbox after ensuring proper initialization
try:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS
except ImportError as e:
    print(f"Error importing Chatterbox: {e}")
    ChatterboxMultilingualTTS = None

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
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model: Optional[ChatterboxMultilingualTTS] = None
        self._model_lock = asyncio.Lock()

        # FIX 1: Save the original torch.load BEFORE patching it
        self.original_torch_load = torch.load

        # Initialize model at startup
        self.bot.loop.create_task(self._async_init_model())

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
        map_location = torch.device(self.device)

        # FIX 2: Use the saved original function, NOT torch.load
        if 'map_location' not in kwargs:
            kwargs['map_location'] = map_location
        return self.original_torch_load(*args, **kwargs)

    async def get_speaker_name(self, filename, interaction : discord.Interaction) -> str :
        speakers_json = await get_guild_json(interaction.guild_id, "speakers")
        with open(speakers_json, "r", encoding="utf-8") as f:
            current_speakers = json.load(f)
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
        speakers_json = await get_guild_json(interaction.guild_id, "speakers")
        with open(speakers_json, "r", encoding="utf-8") as f:
            current_speakers = json.load(f)

        return [app_commands.Choice(name=name, value=filename)
            for name, filename in current_speakers.items()
            if current.lower() in name.lower()][:25]

    async def _async_init_model(self) -> None:
        self.log(f"[TORCH] Usando il devoce {self.device}", "INFO")
        """Initialize the TTS model asynchronously."""
        if ChatterboxMultilingualTTS is None:
            self.log("ChatterboxMultilingualTTS not available", "ERROR")
            return

        if self.device == "cpu":
            # Check for MPS (Mac) just in case, though logs say Linux
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                 self.device = "mps"

            # Apply the patch
            torch.load = self.patched_torch_load

        try:
            self.log(f"Initializing TTS model on {self.device}...", "PROCESS")
            async with self._model_lock:
                self.model = await self.bot.loop.run_in_executor(
                    None, self._init_model_sync
                )
            self.log("TTS model initialized successfully", "SUCCESS")
        except Exception as e:
            self.log(f"Failed to initialize model: {e}", "ERROR")

    def _init_model_sync(self) -> ChatterboxMultilingualTTS:
        """Synchronous model initialization."""
        return ChatterboxMultilingualTTS.from_pretrained(device=self.device)

    async def generate_audio(
        self,
        text: str,
        output_audio: str,
        target_audio: str,
        speaker_name: str,
        language : str
    ) -> bool:
        """Generate audio from text using voice cloning."""
        try:
            self.log(f"Generating audio for speaker: {speaker_name}", "PROCESS")

            # Run generation in executor to avoid blocking
            wav = self.model.generate(text, audio_prompt_path=target_audio, language_id=language)

            # Save the generated audio
            ta.save(output_audio, wav, self.model.sr)
            self.log(f"Audio generated successfully for {speaker_name}", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Error generating audio: {e}", "ERROR")
            return False

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
        testo: str,
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

        if not interaction.user.voice:
            await interaction.response.send_message(
                "❌ You must be in a voice channel!",
                ephemeral=True,
            )
            return

        # Setup and defer response
        speaker_dir = await get_guild_dir(interaction.guild_id, "speakers")
        await interaction.response.defer()
        target_channel = interaction.user.voice.channel
        speaker_path = speaker_dir / speaker
        language = lang
        speaker_name = await self.get_speaker_name(speaker, interaction)

        # Verify speaker file exists
        if not speaker_path.exists():
            self.log(f"Missing speaker file: {speaker_path}", "ERROR")
            await interaction.followup.send(
                f"❌ Configuration error: file '{speaker}' not found."
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
        file_out = f"tts_{uuid.uuid4()}.wav"
        testo_stripped = testo.strip()
        self.log(
            f"Starting generation: '{testo_stripped}' (speaker: {speaker_name})",
            "PROCESS",
        )

        success = await self.generate_audio(
            testo_stripped,
            file_out,
            str(speaker_path),
            speaker_name,
            language
        )

        if not success:
            await interaction.followup.send(
                "❌ Error creating audio. Try different text or speaker."
            )
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
                try:
                    if os.path.exists(file_out):
                        os.remove(file_out)
                        self.log(f"Temporary file removed: {file_out}", "INFO")
                except Exception as e:
                    self.log(f"File removal error: {e}", "WARNING")

            vc.play(source, after=after_playback)
            await interaction.followup.send(
                f"🗣️ **{speaker_name}**: {testo_stripped}"
            )

        except Exception as e:
            self.log(f"Playback error: {e}", "ERROR")
            await interaction.followup.send(f"⚠️ Playback error: {e}")

            # Cleanup on error
            if os.path.exists(file_out):
                os.remove(file_out)

    @app_commands.command(
        name="leave",
        description="Disconnect the bot from the voice channel",
    )
    async def disconnetti(self, interaction: discord.Interaction) -> None:
        """Disconnect the bot from voice channel."""
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect()
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
