import yt_dlp
import demucs
import subprocess
import discord
from discord.ext import commands
from pedalboard import Pedalboard, Compressor, Reverb, LadderFilter, NoiseGate, Gain
from pedalboard.io import AudioFile
from pydub import AudioSegment
from rvc_python.infer import RVCInference
from pathlib import Path
import os
import gc
import torch
import asyncio
import sys
import shutil
# Sblocca le classi necessarie per fairseq/RVC
from fairseq.data.dictionary import Dictionary
torch.serialization.add_safe_globals([Dictionary])
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128,expandable_segments:True"
os.chdir(os.path.abspath("./"))

BASE_DATA_DIR = Path(__file__).parent.absolute()

async def get_guild_dir(guild_id: int, subfolder: str) -> Path:
    """Restituisce il percorso della sottocartella per un server specifico."""
    path = BASE_DATA_DIR / str(guild_id) / subfolder
    path.mkdir(parents=True, exist_ok=True) # Crea la cartella se manca
    return path

async def create_temp_guild_dir(interaction : discord.Interaction) :
    return await get_guild_dir(interaction.guild_id, "temp")

async def delete_temp_guild_dir(interaction : discord.Interaction, temp_dir : Path):
    if os.path.exists(temp_dir):
        try:
            # rmtree elimina la cartella e tutto ciò che contiene
            # Usiamo asyncio.to_thread perché l'eliminazione di molti file è un'operazione I/O bloccante
            await asyncio.to_thread(shutil.rmtree, temp_dir)
        except Exception as e:
            print(f"Errore durante la pulizia della cartella {temp_dir}: {e}")

async def delete_temp_guild_dir(interaction : discord.Interaction, temp_dir : Path) :
    if os.path.exists(temp_dir) :
        os.rmdir(temp_dir)
async def download_video(temp_dir : Path, url : str) :
    os.chdir(temp_dir)
    yt_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'outtmpl': 'canzone_originale.%(ext)s',
    }
    with yt_dlp.YoutubeDL(yt_opts) as ydl :
        ydl.download([url])
    os.chdir("./")

async def separate_audio(temp_dir : Path, input_file):
    # Utilizza il modello htdemucs (molto preciso)
    os.chdir(temp_dir)
    def run_demucs() :
        subprocess.run([sys.executable, "-m", "demucs.separate", "-n", "htdemucs", "--two-stems=vocals", input_file])
    await asyncio.to_thread(run_demucs)
    torch.cuda.empty_cache()
    gc.collect()
    os.chdir(Path(__file__).parent.absolute())

async def get_rvc_version(model_path, model_name):
    """
    Ispeziona il file .pth per determinare se è RVC v1 o v2.
    """
    try:
        # Costruisce il percorso completo al file .pth
        full_path = Path(model_path) / model_name
        checkpoint = torch.load(full_path, map_location="cpu")

        # Verifica la dimensione nei pesi
        # v1 = 256, v2 = 512
        if "weight" in checkpoint:
            for key in checkpoint["weight"].keys():
                if "dec.cond.weight" in key:
                    dim = checkpoint["weight"][key].shape[0]
                    return "v1" if dim == 256 else "v2"

        # Se non lo trova nei pesi, prova nel config
        if "config" in checkpoint:
            return "v2" if checkpoint["config"][17] == 512 else "v1"

        return "v2"
    except Exception as e:
        print(f"Errore rilevamento: {e}")
        return "v2"

async def process_in_chunks(rvc_instance: RVCInference, input_path, chunk_length_ms=30000):
    audio = AudioSegment.from_wav(input_path)
    duration = len(audio)

    # Creiamo una base di silenzio della durata esatta del brano originale
    # Questo garantisce che la durata finale sia identica all'originale
    final_audio = AudioSegment.silent(duration=duration, frame_rate=44100)

    temp_path = Path("temp_chunks")
    temp_path.mkdir(exist_ok=True)

    print(f"Inizio processing a chunk: {duration // 1000}s totali.")

    for i in range(0, duration, chunk_length_ms):
        end = min(i + chunk_length_ms, duration)
        chunk = audio[i:end]
        original_chunk_len = len(chunk) # Salviamo la durata originale esatta

        chunk_input = temp_path / f"chunk_{i}.wav"
        chunk_output = temp_path / f"out_{i}.wav"

        chunk.export(chunk_input, format="wav")

        print(f"Processando segmento: {i//1000}s - {end//1000}s...")
        await asyncio.to_thread(rvc_instance.infer_file, str(chunk_input), str(chunk_output))

        # Carichiamo il chunk processato
        processed_chunk = AudioSegment.from_wav(str(chunk_output))

        # --- CORREZIONE SINCRONIZZAZIONE ---
        # 1. Tagliamo il chunk se è più lungo dell'originale
        # 2. Aggiungiamo silenzio se è più corto (molto raro)
        if len(processed_chunk) > original_chunk_len:
            processed_chunk = processed_chunk[:original_chunk_len]
        elif len(processed_chunk) < original_chunk_len:
            diff = original_chunk_len - len(processed_chunk)
            processed_chunk += AudioSegment.silent(duration=diff, frame_rate=44100)

        # Opzionale: Applica una piccola dissolvenza (fade) di 10ms
        # all'inizio e alla fine per evitare i "click" tra i chunk
        processed_chunk = processed_chunk.fade_in(10).fade_out(10)

        # Inseriamo il pezzo nella posizione esatta (i) della traccia finale
        final_audio = final_audio.overlay(processed_chunk, position=i)

        # Pulizia
        if os.path.exists(chunk_input): os.remove(chunk_input)
        if os.path.exists(chunk_output): os.remove(chunk_output)

    return final_audio

async def RVC(temp_dir : Path, modelpath : str, modelname : str, vocals : str, pitch: int = 0) :
    os.chdir(temp_dir)
    # 1. Inizializza l'istanza
    rvc = RVCInference(device="cuda", models_dir=modelpath)
    version = await get_rvc_version(modelpath, modelname)
    # --- FIX PRE-ELABORAZIONE ---
    # Carichiamo i vocals di Demucs e forziamo il formato corretto per evitare il TypeError
    print("Conversione audio in corso per compatibilità...")
    audio = AudioSegment.from_wav(vocals)
    audio = audio.set_channels(1).set_frame_rate(44100)
    clean_vocals = "vocals_cleaned.wav"
    audio.export(clean_vocals, format="wav")
    output_file = "output.wav"
    # 3. Caricamento e Inferenza
    print(f"Modello trovato! Caricamento di {modelname}...")
    try:
        rvc.load_model(modelname, version=version)
    except TypeError:
        # Se la tua versione di rvc-python non accetta 'version',
        # caricherà secondo il suo default (solitamente v2)
        print("Avviso: La libreria non supporta il parametro 'version' in load_model.")
        rvc.load_model(modelname)
    rvc.f0method = "rmvpe"
    rvc.f0up_key = pitch
    final_audio = await process_in_chunks(rvc, clean_vocals, chunk_length_ms=60000)
    final_audio.export(output_file, format="wav")
    del rvc # Elimina l'oggetto che contiene il modello in VRAM
    gc.collect() # Forza il Garbage Collector di Python
    torch.cuda.empty_cache() # Svuota la cache di PyTorch
    os.chdir(Path(__file__).parent.absolute())
    return output_file


async def apply_pro_effects(input_wav, output_wav):
    with AudioFile(input_wav) as f:
        samplerate = f.samplerate
        audio = f.read(f.frames)

    # Definiamo la catena con i parametri corretti per la tua versione
    board = Pedalboard([
        # 1. Pulizia rumore
        NoiseGate(threshold_db=-35, ratio=10),

        # 2. Filtro passa-alto (LadderFilter)
        # Usiamo LadderFilter.HPF12 e il parametro cutoff_hz richiesto dal costruttore
        LadderFilter(mode=LadderFilter.HPF12, cutoff_hz=150.0),

        # 3. Compressione
        Compressor(threshold_db=-18, ratio=3.5),

        # 4. Riverbero (ampiezza stereo)
        Reverb(room_size=0.4, wet_level=0.12, dry_level=0.8, width=1.0),

        # 5. Guadagno finale
        Gain(gain_db=1.5)
    ])

    effected = board(audio, samplerate)

    with AudioFile(output_wav, 'w', samplerate, effected.shape[0]) as f:
        f.write(effected)

async def mix_audio(temp_dir : Path, vocals_path, instrumental_path, final_output="canzone_finale.wav"):
    os.chdir(temp_dir)
    await apply_pro_effects(vocals_path, "pro-output.wav")
    def perform_mix() :
        print("Mixaggio finale in corso...")

        vocale = AudioSegment.from_wav("pro-output.wav")
        strumentale = AudioSegment.from_wav(instrumental_path)

        # Opzionale: Regola il volume se la voce è troppo bassa o troppo alta
        # vocale = vocale + 3  # Aumenta di 3dB

        # Sovrappone la voce alla strumentale
        combinata = strumentale.overlay(vocale)

        # Esporta il risultato
        combinata.export(final_output, format="wav")
        print(f"🎉 Canzone completata: {final_output}")
        os.chdir(Path(__file__).parent.absolute())
        return final_output

    return await asyncio.to_thread(perform_mix)

async def ai_cover(interaction : discord.Interaction, model_name : str, url : str, pitch:int = 0) :
    temp_dir = await create_temp_guild_dir(interaction)
    currdir = Path(__file__).parent.absolute()
    models = currdir / "models"
    await download_video(temp_dir, url)
    await separate_audio(temp_dir, "canzone_originale.wav")
    vocals = str(temp_dir / "separated" / "htdemucs" / "canzone_originale" / "vocals.wav")
    instrumental = str(temp_dir / "separated" / "htdemucs" / "canzone_originale" / "no_vocals.wav")
    gc.collect()
    output = await RVC(temp_dir, models, model_name, vocals, pitch)
    output = str(temp_dir / output)
    output = await mix_audio(temp_dir, output, instrumental)
    output = str(temp_dir / output)
    torch.cuda.empty_cache()
    # await delete_temp_guild_dir(interaction, temp_dir)
    return output

async def setup(bot) :
    pass


