"""
Diagnostica GPU: `make test-py` (oppure `python src/test.py`).
Funziona uguale su NVIDIA (CUDA), AMD (ROCm) e CPU.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gpu_utils

if gpu_utils.torch is None:
    sys.exit("ERRORE: PyTorch non è installato (o non si carica). Usa: make install GPU=cuda|rocm|cpu")

torch = gpu_utils.torch
print(gpu_utils.describe())
print(f"torch.version.cuda = {torch.version.cuda}")
print(f"torch.version.hip  = {getattr(torch.version, 'hip', None)}")

device = gpu_utils.get_device()

if device == "cpu":
    print("\nNessuna GPU utilizzabile da PyTorch: tutto girerà su CPU (molto più lento).")
    if os.path.exists("/dev/kfd") and not gpu_utils.is_rocm():
        print("⚠️  Trovata una GPU AMD (/dev/kfd) ma PyTorch NON è la build ROCm.")
        print("    Reinstalla con: make install-torch GPU=rocm")
    elif gpu_utils.is_rocm():
        print("⚠️  Build ROCm presente ma nessuna GPU visibile. Controlla:")
        print("    - utente nei gruppi 'render' e 'video' (poi riaccedi)")
        print("    - GPU consumer non ufficiale? Prova HSA_OVERRIDE_GFX_VERSION=10.3.0 (RDNA2) o 11.0.0 (RDNA3)")
else:
    # Test tensore sulla GPU
    x = torch.rand(5, 3, device=device)
    y = (x @ x.T).sum().item()
    print(f"Test tensore su '{device}' OK (somma = {y:.3f})")

try:
    import transformers
    print(f"Transformers version: {transformers.__version__}")
    from transformers import BeamSearchScorer  # noqa: F401
    print("SUCCESS: BeamSearchScorer importato correttamente!")
except ImportError as e:
    print(f"ERRORE IMPORT: {e}")
except Exception as e:
    print(f"ALTRO ERRORE: {e}")
