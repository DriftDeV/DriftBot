"""
Moduli finti per le librerie pesanti (torch, rvc_python, fairseq, chatterbox, pedalboard, pydub...).

I test girano su qualunque macchina, senza GPU né download di modelli. I moduli finti vengono
inseriti SOLO se la libreria vera non è importabile.
"""

import importlib
import sys
import types


class FakeOutOfMemoryError(RuntimeError):
    """Stessa classe di torch.cuda.OutOfMemoryError (identica su CUDA e ROCm)."""


def _module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    return mod


def _install_stubs() -> None:
    def missing(name: str) -> bool:
        try:
            importlib.import_module(name)
            return False
        except Exception:
            return True

    if missing("torch"):
        sys.modules["torch"] = _module(
            "torch",
            __version__="0.0-test",
            version=types.SimpleNamespace(cuda=None, hip=None),
            cuda=types.SimpleNamespace(
                is_available=lambda: False,
                empty_cache=lambda: None,
                OutOfMemoryError=FakeOutOfMemoryError,
            ),
            serialization=types.SimpleNamespace(add_safe_globals=lambda items: None),
            load=lambda *a, **k: {},
            device=lambda name: name,
        )
    if missing("torchaudio"):
        sys.modules["torchaudio"] = _module("torchaudio", save=lambda *a, **k: None)
    if missing("chatterbox.mtl_tts"):
        class ChatterboxMultilingualTTS:  # pragma: no cover - sostituita nei test
            @classmethod
            def from_pretrained(cls, device):
                return cls()

        sys.modules["chatterbox"] = _module("chatterbox")
        sys.modules["chatterbox.mtl_tts"] = _module(
            "chatterbox.mtl_tts", ChatterboxMultilingualTTS=ChatterboxMultilingualTTS
        )
    if missing("pedalboard"):
        names = {n: type(n, (), {"__init__": lambda self, *a, **k: None})
                 for n in ("Pedalboard", "Compressor", "Reverb", "NoiseGate", "Gain")}
        names["LadderFilter"] = type("LadderFilter", (), {"HPF12": 0, "__init__": lambda self, *a, **k: None})
        sys.modules["pedalboard"] = _module("pedalboard", **names)
        sys.modules["pedalboard.io"] = _module("pedalboard.io", AudioFile=type("AudioFile", (), {}))
    if missing("pydub"):
        sys.modules["pydub"] = _module("pydub", AudioSegment=type("AudioSegment", (), {}))
    if missing("rvc_python.infer"):
        sys.modules["rvc_python"] = _module("rvc_python")
        sys.modules["rvc_python.infer"] = _module(
            "rvc_python.infer", RVCInference=type("RVCInference", (), {})
        )
    if missing("fairseq.data.dictionary"):
        sys.modules["fairseq"] = _module("fairseq")
        sys.modules["fairseq.data"] = _module("fairseq.data")
        sys.modules["fairseq.data.dictionary"] = _module(
            "fairseq.data.dictionary", Dictionary=type("Dictionary", (), {})
        )


_install_stubs()


# ---------------------------------------------------------------------------------- isolamento

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_data(tmp_path_factory, monkeypatch):
    """
    Nessun test deve toccare i dati veri del bot (database, cartelle dei server, modelli RVC, vecchi JSON):
    ogni test parte da cartelle temporanee, che i singoli test possono comunque sostituire.
    """
    import cogs
    import legacy_import
    import storage

    base = tmp_path_factory.mktemp("isolated")
    monkeypatch.setenv("DRIFTBOT_DB", str(base / "driftbot.sqlite3"))
    monkeypatch.setattr(cogs, "BASE_DATA_DIR", base / "data")
    monkeypatch.setattr(storage, "RVC_MODELS_DIR", base / "models")
    monkeypatch.setattr(legacy_import, "LEGACY_RVC_INDEX", base / "legacy-rvc-index.json")
    yield base
