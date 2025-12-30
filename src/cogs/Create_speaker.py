import discord
import wave
import uuid
import os
from pathlib import Path
from discord.ext import commands
from discord import app_commands
from discord.ext import voice_recv
import json
from cogs import get_guild_dir, get_guild_json
import logging

# Silenzia i log di info della libreria voice_recv
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.WARNING)
# Configurazione cartella di salvataggio
CURRDIR = Path(__file__).parent.absolute()


class UserSpecificSink(voice_recv.AudioSink):
    """
    Sink audio che registra solo un utente specifico in formato WAV.
    Gestisce la chiusura sicura per evitare errori di scrittura su file chiusi.
    """

    def __init__(self, filename: str, target_user: discord.User):
        self.filename = filename
        self.target_user = target_user
        self.file = wave.open(filename, "wb")
        self.file.setnchannels(2)
        self.file.setsampwidth(2)
        self.file.setframerate(48000)
        self._closed = False  # Flag per tracciare lo stato del file

    def wants_opus(self) -> bool:
        return False

    def write(self, user, data):
        # Se il file è chiuso, ignora qualsiasi dato in arrivo (evita il crash NoneType)
        if self._closed:
            return

        try:
            # Scrive solo se l'audio proviene dall'utente target
            if user == self.target_user:
                self.file.writeframes(data.pcm)
        except (ValueError, AttributeError, OSError):
            # Se il file viene chiuso mentre stiamo scrivendo, gestiamo l'errore silenziosamente
            pass

    def cleanup(self):
        if not self._closed:
            self._closed = True
            try:
                self.file.close()
            except Exception as e:
                print(f"Errore durante la chiusura del file: {e}")

# Embedding RecordView
class RecorderView(discord.ui.View):
    """
    View che contiene il pulsante per fermare la registrazione.
    """

    def __init__(self, vc: voice_recv.VoiceRecvClient, filename: str):
        super().__init__(timeout=None)
        self.vc = vc
        self.filename = filename

    @discord.ui.button(label="Interrompi Registrazione", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # 1. Aggiorna PRIMA l'interfaccia per evitare doppi click e confermare l'interazione
        button.disabled = True
        button.label = "Salvataggio in corso..."
        button.style = discord.ButtonStyle.secondary

        # Usa response.edit_message invece di defer+edit per stabilità sugli ephemeral
        await interaction.response.edit_message(view=self)

        # 2. Esegui le operazioni logiche
        if self.vc.is_listening():
            self.vc.stop_listening()

        await self.vc.disconnect()

        # 3. Invia messaggio di conferma finale
        # Nota: Usiamo followup perché abbiamo già risposto all'interazione con edit_message
        await interaction.followup.send(
            f"✅ Registrazione terminata e salvata in: `{self.filename}`",
            ephemeral=True
        )
        self.stop()


class Create_Speaker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("✅ Create_Speaker caricato...")


    async def save_speaker(self, interaction : discord.Interaction, speaker_name : str, speaker_filename : str) :
        SPEAKERSJSON = await get_guild_json(interaction.guild_id, "speakers")
        ALIASJSON = await get_guild_json(interaction.guild_id, "speakers", json_name="alias.json")
        with open(SPEAKERSJSON, "r", encoding="utf-8") as f:
            speakers = json.load(f)
        with open(ALIASJSON, "r", encoding="utf-8") as f:
            speaker_aliases = json.load(f)
            for original, alias in speaker_aliases.items() :
                if original == speaker_name :
                    speaker_name = alias

        speakers[speaker_name] = speaker_filename

        with open(SPEAKERSJSON, "w", encoding="utf-8") as f:
            json.dump(speakers, f, indent=4)

    async def get_speaker_name(self, filename) -> str :
        SPEAKERSJSON = await get_guild_json(interaction.guild_id, "speakers")

        with open(SPEAKERSJSON, "r", encoding="utf-8") as f:
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
        SPEAKERSJSON = await get_guild_json(interaction.guild_id, "speakers")


        with open(SPEAKERSJSON, "r", encoding="utf-8") as f:
            current_speakers = json.load(f)

        return [app_commands.Choice(name=name, value=filename)
            for name, filename in current_speakers.items()
            if current.lower() in name.lower()][:25]


    @app_commands.command(name="rename-speaker", description="Rename a Speaker")
    @app_commands.describe(new_name="il nome da dare (alias)")
    @app_commands.autocomplete(speaker=autocomplete_speakers)
    async def rename_speaker(self, interaction : discord.Interaction, new_name : str, speaker : str) :
        # Ricavo il nome dello speaker
        current_name = await self.get_speaker_name(speaker)

        # Apro il file json degli speaker
        SPEAKERSJSON = await get_guild_json(interaction.guild_id, "speakers")
        ALIASJSON = await get_guild_json(interaction.guild_id, "speakers", json_name="alias.json")
        with open(SPEAKERSJSON, "r", encoding="utf-8") as f:
            current_speakers = json.load(f)
            current_speakers[new_name] = current_speakers.pop(current_name)

        # Aggiorno gli alias
        with open(ALIASJSON, "r", encoding="utf-8") as f :
            speaker_alisase = json.load(f)
            speaker_alisase[current_name] = new_name

        # Scrivo i Dati
        with open(ALIASJSON, "w", encoding="utf-8") as f:
            json.dump(speaker_alisase, f, indent=4)

        with open(SPEAKERSJSON, "w", encoding="utf-8") as f:
            json.dump(current_speakers, f, indent=4)


        await interaction.response.send_message("✅ Speaker Rinominato!")

    @app_commands.command(name="new-speaker", description="Registra la voce di un utente specifico")
    @app_commands.describe(target="L'utente da registrare (lascia vuoto per te stesso)")
    async def create_speaker(self, interaction: discord.Interaction, target: discord.Member = None):
        SPEAKERS_DIR = await get_guild_dir(interaction.guild_id, "speakers")
        SPEAKERS_DIR.mkdir(parents=True, exist_ok=True) # Assicura che la cartella esista

        # Se nessun target è specificato, usa chi ha lanciato il comando
        target_user = target or interaction.user

        if not interaction.user.voice:
            await interaction.response.send_message("❌ Devi essere in un canale vocale!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        # Verifica se il target è nello stesso canale
        if target_user not in channel.members:
             await interaction.response.send_message(f"❌ L'utente {target_user.mention} non è nel tuo canale vocale!", ephemeral=True)
             return

        await interaction.response.send_message(f"🔄 Connessione a {channel.name}...", ephemeral=True)

        # Gestione connessione vocale
        if interaction.guild.voice_client is None:
            try:
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
            except Exception as e:
                return await interaction.followup.send(f"❌ Errore di connessione: {e}", ephemeral=True)
        else:
            vc = interaction.guild.voice_client

        if vc.is_listening():
            return await interaction.followup.send("⚠️ Sto già registrando un'altra sessione!", ephemeral=True)

        # Generazione nome file univoco
        unique_id = uuid.uuid4()
        # Pulizia nome utente più robusta
        safe_username = "".join(x for x in target_user.name if x.isalnum() or x in "._-")
        if not safe_username:
            safe_username = "unknown_user"

        filename = SPEAKERS_DIR / f"{safe_username}_{unique_id}.wav"

        # Avvio ascolto filtrato
        vc.listen(UserSpecificSink(str(filename), target_user))

        # Creazione Embed
        embed = discord.Embed(
            title="🎙️ Registrazione in corso",
            description=f"Sto registrando l'audio di **{target_user.mention}**.",
            color=discord.Color.red()
        )
        embed.add_field(name="Cartella", value=f"`{SPEAKERS_DIR}/`", inline=True)
        # Timestamp dinamico
        embed.add_field(name="Inizio", value=f"<t:{int(discord.utils.utcnow().timestamp())}:R>", inline=True)
        embed.set_footer(text="Premi il pulsante per terminare e salvare.")

        # Invio Embed con Pulsante (tramite followup perché abbiamo già risposto con "Connessione...")
        view = RecorderView(vc, str(filename))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        await self.save_speaker(
            interaction,
            target_user.name,
            speaker_filename=f"{safe_username}_{unique_id}.wav"
        )



async def setup(bot):
    await bot.add_cog(Create_Speaker(bot))
