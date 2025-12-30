try:
    import torch
    print(f"PyTorch version: {torch.__version__}")
except ImportError:
    print("ERRORE: PyTorch non è installato!")

try:
    import transformers
    print(f"Transformers version: {transformers.__version__}")

    from transformers import BeamSearchScorer
    print("SUCCESS: BeamSearchScorer importato correttamente!")
except ImportError as e:
    print(f"ERRORE IMPORT: {e}")
except Exception as e:
    print(f"ALTRO ERRORE: {e}")

import torch

print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available (ROCm): {torch.cuda.is_available()}")

if torch.cuda.is_available():
    print(f"Device name: {torch.cuda.get_device_name(0)}")

    # Test tensor su GPU
    x = torch.rand(5, 3).to('cuda')
    print("Tensor on GPU:")
    print(x)
else:
    print("ROCm non rilevato. Verifica l'installazione.")
