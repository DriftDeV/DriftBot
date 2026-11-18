import discord
import wave
import uuid
import os
from pathlib import Path
from typing import Awaitable, Callable, Optional
from discord.ext import commands
from discord import app_commands
from discord.ext import voice_recv
from cogs import escape_md, get_guild_dir, get_guild_json, load_json, save_json
import logging
try:
    import davey
except ImportError:  # senza davey discord.py non si connette comunque
    davey = None

log = logging.getLogger(__name__)

# Silenzia i log di info della libreria voice_recv
logging.getLogger('discord.ext.voice_recv.reader').setLevel(logging.WARNING)
# Configurazione cartella di salvataggio
CURRDIR = Path(__file__).parent.absolute()

MAX_RECORD_SECONDS = 180      # la registrazione si ferma da sola, così non cresce all'infinito
MIN_RECORD_SECONDS = 3        # sotto questa durata il campione è inutilizzabile per il voice cloning
BYTES_PER_SECOND = 48000 * 2 * 2   # 48kHz, 16 bit, stereo
MAX_NAME_LENGTH = 40          # il nome file finisce in un Choice (max 100 caratteri)


OPUS_SILENCE = b"\xf8\xff\xfe"


def enable_dave_decrypt(vc: "voice_recv.VoiceRecvClient") -> None:
    """
    voice_recv 0.5.2a toglie solo la cifratura di trasporto: con DAVE (E2EE di Discord) il payload
    resta cifrato, Opus risponde "corrupted stream" e il router muore (0 secondi registrati).
    Qui si aggiunge la decifratura DAVE dopo quella di trasporto.
    """
    if davey is None:
        return
    decryptor = vc._reader.decryptor
    transport_decrypt = decryptor.decrypt_rtp

    def decrypt_rtp(packet):
        data = transport_decrypt(packet)
        session = vc._connection.dave_session
        user_id = vc._ssrc_to_id.get(packet.ssrc)
        if session is None or not session.ready or user_id is None:
            return data
        if data == OPUS_SILENCE:  # i frame di silenzio viaggiano in chiaro
            return data
        try:
            return session.decrypt(user_id, davey.MediaType.audio, data)
        except Exception as e:
            log.debug("Decifratura DAVE fallita (user %s): %s", user_id, e)
            return OPUS_SILENCE

    decryptor.decrypt_rtp = decrypt_rtp


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
        self.bytes_written = 0

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
                self.bytes_written += len(data.pcm)
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

    @property
    def seconds(self) -> float:
        return self.bytes_written / BYTES_PER_SECOND


# Risultato finale: (tipo, testo). Il tipo decide titolo e colore del pannello.
Result = tuple[str, str]
RESULT_STYLE = {
    "ok": ("✅ Registrazione salvata", discord.Color.green),
    "warn": ("⚠️ Registrazione non salvata", discord.Color.orange),
    "error": ("❌ Registrazione non riuscita", discord.Color.red),
}


class RecorderView(discord.ui.View):
    """
    Pannello con il pulsante per fermare la registrazione. È l'unico messaggio mostrato all'utente:
    quando la registrazione finisce (a mano o per timeout) il pannello diventa il risultato, senza
    pulsanti e senza lasciare un "in corso" appeso.
    `on_finish` viene chiamata UNA volta e restituisce (tipo, testo).
    """

    def __init__(
        self,
        vc: voice_recv.VoiceRecvClient,
        sink: UserSpecificSink,
        origin: discord.Interaction,
        on_finish: Callable[[], Awaitable[Result]],
    ):
        super().__init__(timeout=MAX_RECORD_SECONDS)
        self.vc = vc
        self.sink = sink
        self.origin = origin
        self.on_finish = on_finish
        self._stopping = False   # già premuto (o scaduto): un secondo click non deve fare nulla
        self._finished = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Il messaggio è privato (ephemeral), ma il pulsante resta riservato a chi ha avviato la registrazione
        if interaction.user.id != self.origin.user.id:
            await interaction.response.send_message(
                "❌ Solo chi ha avviato la registrazione può fermarla.", ephemeral=True
            )
            return False
        return True

    @staticmethod
    def result_embed(kind: str, text: str, timed_out: bool = False) -> discord.Embed:
        title, color = RESULT_STYLE.get(kind, RESULT_STYLE["error"])
        embed = discord.Embed(title=title, description=text, color=color())
        if timed_out:
            embed.set_footer(text=f"Tempo massimo di {MAX_RECORD_SECONDS}s raggiunto: registrazione fermata.")
        return embed

    async def _finish(self) -> Optional[Result]:
        """Ferma la registrazione, lascia la vocale e salva lo speaker. Idempotente."""
        if self._finished:
            return None
        self._finished = True

        try:
            if self.vc.is_listening():
                self.vc.stop_listening()
        except Exception as e:
            log.warning("stop_listening fallito: %s", e)
        self.sink.cleanup()

        try:
            await self.vc.disconnect()
        except Exception as e:
            log.warning("disconnect fallito: %s", e)

        try:
            return await self.on_finish()
        except Exception:
            log.exception("Salvataggio dello speaker fallito")
            return "error", "Errore durante il salvataggio dello speaker."

    @discord.ui.button(label="Interrompi Registrazione", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._stopping:
            # secondo click ravvicinato: va solo confermato, altrimenti Discord mostra "interazione fallita"
            return await interaction.response.defer()
        self._stopping = True

        # 1. Risponde SUBITO (entro 3s) togliendo il pulsante: niente doppi click
        saving = discord.Embed(title="💾 Salvataggio in corso...", color=discord.Color.light_grey())
        await interaction.response.edit_message(embed=saving, view=None)

        # 2. Ferma la registrazione e salva
        result = await self._finish()

        # 3. Il pannello diventa il risultato finale
        if result:
            try:
                await interaction.edit_original_response(embed=self.result_embed(*result), view=None)
            except discord.HTTPException as e:
                log.debug("Impossibile aggiornare il pannello: %s", e)
        self.stop()

    async def on_timeout(self):
        # Tempo massimo raggiunto senza che nessuno premesse il pulsante
        if self._stopping:
            return
        self._stopping = True
        result = await self._finish()
        if result:
            try:
                await self.origin.edit_original_response(embed=self.result_embed(*result, timed_out=True), view=None)
            except discord.HTTPException as e:
                log.debug("Impossibile aggiornare il pannello dopo il timeout: %s", e)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        log.error("Errore nella view di registrazione", exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send("❌ Errore imprevisto.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Errore imprevisto.", ephemeral=True)
        except discord.HTTPException:
            pass


class Create_Speaker(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("✅ Create_Speaker caricato...")


    async def save_speaker(self, guild_id : int, speaker_name : str, speaker_filename : str) :
        speakers_json = await get_guild_json(guild_id, "speakers")
        alias_json = await get_guild_json(guild_id, "speakers", json_name="alias.json")
        speakers = load_json(speakers_json)
        speaker_aliases = load_json(alias_json)

        speaker_name = speaker_aliases.get(speaker_name, speaker_name)
        speakers[speaker_name] = speaker_filename
        save_json(speakers_json, speakers)

    async def get_speaker_name(self, filename : str, guild_id : int) -> str :
        speakers_json = await get_guild_json(guild_id, "speakers")
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
            log.warning("Autocomplete speakers fallito: %s", e)
            return []

        return [app_commands.Choice(name=name[:100], value=filename[:100])
            for name, filename in current_speakers.items()
            if current.lower() in name.lower()][:25]


    @app_commands.command(name="rename-speaker", description="Rinomina uno speaker")
    @app_commands.describe(new_name="Il nuovo nome (alias)", speaker="Lo speaker da rinominare")
    @app_commands.autocomplete(speaker=autocomplete_speakers)
    async def rename_speaker(
        self,
        interaction : discord.Interaction,
        new_name : app_commands.Range[str, 1, 100],
        speaker : str,
    ) :
        new_name = new_name.strip()
        if not new_name:
            return await interaction.response.send_message("❌ Il nome non può essere vuoto.", ephemeral=True)

        # Ricavo il nome dello speaker
        current_name = await self.get_speaker_name(speaker, interaction.guild_id)
        if not current_name:
            return await interaction.response.send_message("❌ Speaker non trovato.", ephemeral=True)

        # Apro il file json degli speaker
        speakers_json = await get_guild_json(interaction.guild_id, "speakers")
        alias_json = await get_guild_json(interaction.guild_id, "speakers", json_name="alias.json")
        current_speakers = load_json(speakers_json)
        speaker_aliases = load_json(alias_json)

        if new_name != current_name and new_name in current_speakers:
            return await interaction.response.send_message(
                f"❌ Esiste già uno speaker chiamato `{new_name}`.", ephemeral=True
            )

        current_speakers[new_name] = current_speakers.pop(current_name)
        # Aggiorno gli alias
        speaker_aliases[current_name] = new_name

        # Scrivo i Dati
        save_json(alias_json, speaker_aliases)
        save_json(speakers_json, current_speakers)

        await interaction.response.send_message("✅ Speaker Rinominato!")

    async def _get_recording_client(
        self, channel: discord.VoiceChannel, guild: discord.Guild
    ) -> voice_recv.VoiceRecvClient:
        """
        Restituisce un VoiceRecvClient nel canale richiesto. Gli altri cog (TTS, musica, soundboard)
        si connettono con un VoiceClient normale, che non sa ascoltare: in quel caso, se non sta
        riproducendo nulla, lo sostituisco; altrimenti segnalo che il bot è occupato.
        """
        vc = guild.voice_client
        if vc is not None and not isinstance(vc, voice_recv.VoiceRecvClient):
            if vc.is_playing():
                raise RuntimeError("busy")
            await vc.disconnect()
            vc = None

        if vc is None:
            return await channel.connect(cls=voice_recv.VoiceRecvClient)
        if vc.channel.id != channel.id:
            await vc.move_to(channel)
        return vc

    @app_commands.command(name="new-speaker", description="Registra la voce di un utente specifico")
    @app_commands.describe(target="L'utente da registrare (lascia vuoto per te stesso)")
    async def create_speaker(self, interaction: discord.Interaction, target: Optional[discord.Member] = None):
        # Se nessun target è specificato, usa chi ha lanciato il comando
        target_user = target or interaction.user

        if not interaction.user.voice or interaction.user.voice.channel is None:
            await interaction.response.send_message("❌ Devi essere in un canale vocale!", ephemeral=True)
            return

        channel = interaction.user.voice.channel

        # Verifica se il target è nello stesso canale
        if target_user not in channel.members:
             await interaction.response.send_message(f"❌ L'utente {target_user.mention} non è nel tuo canale vocale!", ephemeral=True)
             return

        # Un solo messaggio privato per tutta l'operazione: prima "Connessione...", poi il pannello di
        # registrazione (o l'errore) lo SOSTITUISCONO, così non resta nulla di vecchio accanto.
        await interaction.response.send_message(f"🔄 Connessione a {channel.name}...", ephemeral=True)

        async def fail(text: str) -> None:
            try:
                await interaction.edit_original_response(content=text)
            except discord.HTTPException as e:
                log.debug("Impossibile mostrare l'errore: %s", e)

        SPEAKERS_DIR = await get_guild_dir(interaction.guild_id, "speakers")

        # Gestione connessione vocale
        try:
            vc = await self._get_recording_client(channel, interaction.guild)
        except RuntimeError:
            return await fail("⚠️ Sto riproducendo audio: aspetta che finisca e riprova.")
        except Exception as e:
            log.error("Errore di connessione vocale: %s", e)
            return await fail("❌ Errore di connessione al canale vocale.")

        if vc.is_listening():
            return await fail("⚠️ Sto già registrando un'altra sessione!")

        # Generazione nome file univoco
        unique_id = uuid.uuid4()
        # Pulizia nome utente più robusta
        safe_username = "".join(x for x in target_user.name if x.isalnum() or x in "._-")[:MAX_NAME_LENGTH]
        if not safe_username:
            safe_username = "unknown_user"

        filename_only = f"{safe_username}_{unique_id}.wav"
        filename = SPEAKERS_DIR / filename_only

        # Avvio ascolto filtrato
        sink = None
        try:
            sink = UserSpecificSink(str(filename), target_user)
            vc.listen(sink)
            enable_dave_decrypt(vc)
        except Exception as e:
            log.error("Impossibile avviare la registrazione: %s", e)
            if sink is not None:
                sink.cleanup()
            try:
                os.remove(filename)
            except OSError:
                pass
            return await fail("❌ Impossibile avviare la registrazione.")

        async def on_finish() -> Result:
            # Lo speaker viene registrato solo ORA, a registrazione conclusa e con audio valido
            if sink.seconds < MIN_RECORD_SECONDS:
                try:
                    os.remove(filename)
                except OSError:
                    pass
                return "warn", (
                    f"Registrazione troppo breve ({sink.seconds:.1f}s, minimo {MIN_RECORD_SECONDS}s): "
                    "nessuno speaker salvato."
                )
            await self.save_speaker(interaction.guild_id, target_user.name, filename_only)
            return "ok", (
                f"Speaker **{escape_md(target_user.name)}** salvato ({sink.seconds:.0f}s di audio). "
                "Ora puoi sceglierlo con `/tts-ai`."
            )

        # Pannello di registrazione. Niente percorsi del server: sono dettagli interni che non servono all'utente.
        embed = discord.Embed(
            title="🎙️ Registrazione in corso",
            description=f"Sto registrando l'audio di {target_user.mention}.",
            color=discord.Color.red()
        )
        # Timestamp dinamico
        embed.add_field(name="Inizio", value=f"<t:{int(discord.utils.utcnow().timestamp())}:R>", inline=True)
        embed.set_footer(text=f"Premi il pulsante per terminare e salvare (max {MAX_RECORD_SECONDS}s).")

        view = RecorderView(vc, sink, interaction, on_finish)
        await interaction.edit_original_response(content=None, embed=embed, view=view)



async def setup(bot):
    await bot.add_cog(Create_Speaker(bot))
