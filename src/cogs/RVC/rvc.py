"""
Pipeline AI cover: download (yt-dlp) -> separazione voce/strumentale (Demucs)
-> conversione voce (RVC) -> effetti (Pedalboard) -> mix finale (pydub).

Note di progetto:
- Nessun `os.chdir()`: la working directory è globale per tutto il processo e cambiarla
  rompe gli altri cog. Si usano solo percorsi assoluti.
- Ogni richiesta lavora in una cartella di job univoca (`jobs/`), eliminata a fine uso.
- Tutto il lavoro pesante gira in un thread (`asyncio.to_thread`), mai nell'event loop.
- Il device viene da `gpu_utils.get_device()`: funziona uguale su NVIDIA (CUDA) e AMD (ROCm).
"""

import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import torch
import yt_dlp
from pedalboard import Pedalboard, Compressor, Reverb, LadderFilter, NoiseGate, Gain
from pedalboard.io import AudioFile
from pydub import AudioSegment
from rvc_python.infer import RVCInference

import gpu_utils
import storage
from cogs import resolve_in_dir

# Sblocca le classi necessarie per fairseq/RVC (torch.load con weights_only=True)
from fairseq.data.dictionary import Dictionary
if hasattr(torch.serialization, "add_safe_globals"):
    torch.serialization.add_safe_globals([Dictionary])

log = logging.getLogger(__name__)

RVC_DIR = Path(__file__).parent.absolute()
MODELS_DIR = storage.RVC_MODELS_DIR     # la stessa cartella gestita dalla dashboard (storage.py)
JOBS_DIR = RVC_DIR / "jobs"

MAX_SONG_SECONDS = int(os.getenv("AI_COVER_MAX_SECONDS", "900"))   # 15 minuti
DEMUCS_TIMEOUT = int(os.getenv("AI_COVER_DEMUCS_TIMEOUT", "1800"))  # 30 minuti
STALE_JOB_SECONDS = 3600


class CoverError(Exception):
    """Errore atteso, con un messaggio già adatto a essere mostrato all'utente."""


# ----------------------------------------------------------------------- validazione

def validate_url(url: str) -> str:
    """Accetta solo URL http(s): niente percorsi locali o schemi strani passati a yt-dlp."""
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise CoverError("URL non valido: serve un link http(s) a un video.")
    return url


def resolve_model(model_name: str) -> Path:
    """Restituisce il percorso del modello RVC, garantendo che resti dentro `models/`."""
    path = resolve_in_dir(MODELS_DIR, model_name)
    if path is None or not path.exists():
        raise CoverError(f"Modello `{model_name[:50]}` non trovato.")
    return path


def get_rvc_device() -> str:
    """Device per rvc-python: vuole l'indice esplicito ('cuda:0'), valido anche su ROCm."""
    device = gpu_utils.get_device()
    return "cuda:0" if device == "cuda" else device


# ------------------------------------------------------------------------------ job

def create_job_dir(guild_id: int) -> Path:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{guild_id}_", dir=JOBS_DIR))


def cleanup_job(path: Optional[Path]) -> None:
    """Elimina la cartella del job a cui appartiene `path` (file o cartella). Non solleva mai."""
    if path is None:
        return
    job_dir = Path(path)
    if job_dir.parent != JOBS_DIR:
        job_dir = job_dir.parent
    if job_dir.parent != JOBS_DIR:
        return  # sicurezza: non cancellare mai fuori da jobs/
    shutil.rmtree(job_dir, ignore_errors=True)


def purge_stale_jobs() -> None:
    """Rimuove i job rimasti da crash/riavvii precedenti."""
    if not JOBS_DIR.exists():
        return
    now = time.time()
    for entry in JOBS_DIR.iterdir():
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > STALE_JOB_SECONDS:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- passi

def _download(job_dir: Path, url: str) -> Path:
    yt_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'match_filter': yt_dlp.utils.match_filter_func(f"duration <= {MAX_SONG_SECONDS}"),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'outtmpl': str(job_dir / 'canzone_originale.%(ext)s'),
    }
    try:
        with yt_dlp.YoutubeDL(yt_opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadError as e:
        log.warning("Download fallito: %s", e)
        raise CoverError("Impossibile scaricare il video (link non valido o non disponibile).") from e

    wav = job_dir / "canzone_originale.wav"
    if not wav.exists():
        raise CoverError(
            f"Video non scaricabile o più lungo di {MAX_SONG_SECONDS // 60} minuti."
        )
    return wav


def _demucs_devices() -> list[str]:
    device = gpu_utils.get_device()
    if device.startswith("cuda"):
        return [device, "cpu"]  # se la VRAM non basta si ripiega sulla CPU (più lento ma funziona)
    return ["cpu"]


def _separate(job_dir: Path, wav: Path) -> tuple[Path, Path]:
    """Separa voce e strumentale con htdemucs, in un sottoprocesso (libera la VRAM all'uscita)."""
    out_dir = job_dir / "separated"
    last_error = ""
    for device in _demucs_devices():
        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", "htdemucs", "--two-stems=vocals",
            "-d", device,
            "-o", str(out_dir),
            str(wav),
        ]
        try:
            result = subprocess.run(
                cmd, cwd=job_dir, capture_output=True, text=True, timeout=DEMUCS_TIMEOUT
            )
        except subprocess.TimeoutExpired as e:
            raise CoverError("La separazione della voce ha impiegato troppo tempo.") from e

        if result.returncode == 0:
            stems = out_dir / "htdemucs" / wav.stem
            vocals, instrumental = stems / "vocals.wav", stems / "no_vocals.wav"
            if vocals.exists() and instrumental.exists():
                return vocals, instrumental
            last_error = "output di Demucs mancante"
        else:
            last_error = (result.stderr or result.stdout or "").strip()
            log.error("Demucs fallito su %s: %s", device, last_error[-500:])
            if device != "cpu":
                # VRAM insufficiente o errore del driver GPU (CUDA/ROCm): ripiega sulla CPU
                motivo = "VRAM insufficiente" if gpu_utils.is_out_of_memory(RuntimeError(last_error)) else "errore GPU"
                log.warning("Demucs: %s su %s, riprovo su CPU", motivo, device)
                continue
        break

    raise CoverError("Separazione della voce fallita (Demucs).")


def get_rvc_version(model_path: Path) -> str:
    """
    Ispeziona il file .pth per determinare se è RVC v1 o v2.
    `model_path` può essere il file .pth oppure la cartella del modello.
    """
    try:
        if model_path.is_dir():
            pth = next(iter(sorted(model_path.glob("*.pth"))), None)
            if pth is None:
                return "v2"
            model_path = pth
        checkpoint = torch.load(model_path, map_location="cpu")

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
        log.warning("Rilevamento versione RVC fallito (assumo v2): %s", e)
        return "v2"


def process_in_chunks(rvc_instance: RVCInference, input_path: Path, work_dir: Path, chunk_length_ms=30000):
    audio = AudioSegment.from_wav(input_path)
    duration = len(audio)

    # Creiamo una base di silenzio della durata esatta del brano originale
    # Questo garantisce che la durata finale sia identica all'originale
    final_audio = AudioSegment.silent(duration=duration, frame_rate=44100)

    temp_path = work_dir / "chunks"
    temp_path.mkdir(exist_ok=True)

    log.info("Inizio processing a chunk: %ss totali.", duration // 1000)

    for i in range(0, duration, chunk_length_ms):
        end = min(i + chunk_length_ms, duration)
        chunk = audio[i:end]
        original_chunk_len = len(chunk) # Salviamo la durata originale esatta

        chunk_input = temp_path / f"chunk_{i}.wav"
        chunk_output = temp_path / f"out_{i}.wav"

        chunk.export(chunk_input, format="wav")

        log.info("Processando segmento: %ss - %ss...", i // 1000, end // 1000)
        rvc_instance.infer_file(str(chunk_input), str(chunk_output))

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
        chunk_input.unlink(missing_ok=True)
        chunk_output.unlink(missing_ok=True)

    return final_audio


def _convert_voice(job_dir: Path, model_path: Path, vocals: Path, pitch: int) -> Path:
    """Converte la voce con RVC. Il modello viene sempre rilasciato dalla VRAM, anche in caso di errore."""
    rvc = None
    try:
        # 1. Inizializza l'istanza (device ricavato dal backend: CUDA, ROCm o CPU)
        rvc = RVCInference(device=get_rvc_device(), models_dir=str(MODELS_DIR))
        version = get_rvc_version(model_path)

        # --- FIX PRE-ELABORAZIONE ---
        # Carichiamo i vocals di Demucs e forziamo il formato corretto per evitare il TypeError
        log.info("Conversione audio in corso per compatibilità...")
        audio = AudioSegment.from_wav(vocals)
        audio = audio.set_channels(1).set_frame_rate(44100)
        clean_vocals = job_dir / "vocals_cleaned.wav"
        audio.export(clean_vocals, format="wav")

        # 3. Caricamento e Inferenza
        model_name = str(model_path.relative_to(MODELS_DIR.resolve()))
        log.info("Modello trovato! Caricamento di %s...", model_name)
        try:
            rvc.load_model(model_name, version=version)
        except TypeError:
            # Se la tua versione di rvc-python non accetta 'version',
            # caricherà secondo il suo default (solitamente v2)
            log.warning("La libreria non supporta il parametro 'version' in load_model.")
            rvc.load_model(model_name)
        rvc.f0method = "rmvpe"
        rvc.f0up_key = pitch

        final_audio = process_in_chunks(rvc, clean_vocals, job_dir, chunk_length_ms=60000)
        output_file = job_dir / "output.wav"
        final_audio.export(output_file, format="wav")
        return output_file
    finally:
        del rvc            # Elimina l'oggetto che contiene il modello in VRAM
        gpu_utils.free_gpu_memory()


def apply_pro_effects(input_wav: Path, output_wav: Path) -> None:
    with AudioFile(str(input_wav)) as f:
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

    with AudioFile(str(output_wav), 'w', samplerate, effected.shape[0]) as f:
        f.write(effected)


def mix_audio(job_dir: Path, vocals_path: Path, instrumental_path: Path) -> Path:
    pro_output = job_dir / "pro-output.wav"
    apply_pro_effects(vocals_path, pro_output)

    log.info("Mixaggio finale in corso...")
    vocale = AudioSegment.from_wav(pro_output)
    strumentale = AudioSegment.from_wav(instrumental_path)

    # Opzionale: Regola il volume se la voce è troppo bassa o troppo alta
    # vocale = vocale + 3  # Aumenta di 3dB

    # Sovrappone la voce alla strumentale
    combinata = strumentale.overlay(vocale)

    final_output = job_dir / "canzone_finale.wav"
    combinata.export(final_output, format="wav")
    log.info("🎉 Canzone completata: %s", final_output)
    return final_output


def _pipeline(guild_id: int, model_name: str, url: str, pitch: int) -> Path:
    url = validate_url(url)
    model_path = resolve_model(model_name)
    job_dir = create_job_dir(guild_id)
    try:
        wav = _download(job_dir, url)
        vocals, instrumental = _separate(job_dir, wav)
        gpu_utils.free_gpu_memory()
        converted = _convert_voice(job_dir, model_path, vocals, pitch)
        return mix_audio(job_dir, converted, instrumental)
    except BaseException:
        cleanup_job(job_dir)
        raise
    finally:
        gpu_utils.free_gpu_memory()


async def ai_cover(guild_id: int, model_name: str, url: str, pitch: int = 0) -> Path:
    """
    Genera la cover e restituisce il percorso del file finale.
    Chi chiama deve eliminare il job con `cleanup_job(path)` a fine riproduzione.
    Solleva `CoverError` per i problemi attesi (messaggio mostrabile all'utente).
    """
    return await asyncio.to_thread(_pipeline, guild_id, model_name, url, pitch)


async def setup(bot) :
    pass
