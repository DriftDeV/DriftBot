"""
Rilevamento e gestione del dispositivo di calcolo (NVIDIA CUDA / AMD ROCm / Apple MPS / CPU).

Le build ROCm di PyTorch espongono la *stessa* API di CUDA: `torch.cuda.is_available()` è True,
il device si chiama "cuda" e `torch.version.hip` è valorizzato (mentre `torch.version.cuda` è None).
Per questo nel codice si usa sempre `get_device()` invece di scrivere "cuda" a mano, e
`free_gpu_memory()` invece di `torch.cuda.empty_cache()`.

Questo modulo non deve fallire se PyTorch manca: così il bot parte lo stesso e i cog che
non usano la GPU (es. musica) continuano a funzionare.

Variabile d'ambiente opzionale:
    DRIFTBOT_DEVICE=cuda|cuda:1|cpu|mps   forza il dispositivo (es. per scegliere la GPU).
"""

import gc
import logging
import os

try:
    import torch
except Exception:  # ImportError, ma anche errori di caricamento delle librerie GPU
    torch = None

log = logging.getLogger(__name__)


def is_rocm() -> bool:
    """True se PyTorch è una build ROCm (AMD)."""
    return torch is not None and getattr(torch.version, "hip", None) is not None


def _mps_available() -> bool:
    backend = getattr(getattr(torch, "backends", None), "mps", None)
    try:
        return backend is not None and backend.is_available()
    except Exception:
        return False


def _cuda_available() -> bool:
    if torch is None:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        log.exception("torch.cuda.is_available() ha sollevato un'eccezione")
        return False


def get_device() -> str:
    """Restituisce 'cuda' (NVIDIA *o* AMD ROCm), 'mps' o 'cpu'. Rispetta DRIFTBOT_DEVICE."""
    forced = os.environ.get("DRIFTBOT_DEVICE", "").strip().lower()
    if forced:
        return forced
    if _cuda_available():
        return "cuda"
    if _mps_available():
        return "mps"
    return "cpu"


def backend_name() -> str:
    """Nome leggibile del backend in uso: 'ROCm', 'CUDA', 'MPS' o 'CPU'."""
    device = get_device()
    if device.startswith("cuda"):
        return "ROCm" if is_rocm() else "CUDA"
    if device.startswith("mps"):
        return "MPS"
    return "CPU"


def describe() -> str:
    """Una riga di diagnostica sul dispositivo (per i log di avvio)."""
    if torch is None:
        return "PyTorch non installato: funzioni AI (TTS, AI cover) non disponibili"
    device = get_device()
    text = f"PyTorch {torch.__version__} | backend {backend_name()} | device '{device}'"
    if device.startswith("cuda"):
        try:
            text += f" | GPU: {torch.cuda.get_device_name(torch.device(device))}"
        except Exception:
            pass
        runtime = getattr(torch.version, "hip", None) or getattr(torch.version, "cuda", None)
        if runtime:
            text += f" | runtime {runtime}"
    return text


def configure_allocator() -> None:
    """
    Imposta l'allocatore di memoria GPU. Va chiamata PRIMA che la GPU venga inizializzata
    (cioè all'avvio, prima di caricare i modelli). Non sovrascrive valori già impostati dall'utente.

    - NVIDIA: `expandable_segments` riduce la frammentazione della VRAM.
    - ROCm: `expandable_segments` non è supportato in modo affidabile su tutte le versioni
      di PyTorch/ROCm, quindi si usa solo `max_split_size_mb`.
    """
    if is_rocm():
        os.environ.setdefault("PYTORCH_HIP_ALLOC_CONF", "max_split_size_mb:128")
    else:
        os.environ.setdefault(
            "PYTORCH_CUDA_ALLOC_CONF", "max_split_size_mb:128,expandable_segments:True"
        )


def free_gpu_memory() -> None:
    """Libera la memoria GPU in cache. Sicura su qualsiasi backend e senza PyTorch."""
    gc.collect()
    if torch is None:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        if _mps_available():
            torch.mps.empty_cache()
    except Exception:
        log.debug("free_gpu_memory: impossibile svuotare la cache", exc_info=True)


def is_out_of_memory(error: BaseException) -> bool:
    """True se `error` è un esaurimento di memoria GPU (stessa classe su CUDA e ROCm)."""
    oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
    if oom_type is not None and isinstance(error, oom_type):
        return True
    return "out of memory" in str(error).lower()
