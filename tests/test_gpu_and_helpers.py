"""Test di gpu_utils (CUDA / ROCm / MPS / CPU), degli helper dei cog e di main.py."""

import os
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands

import gpu_utils
from cogs import resolve_in_dir
from fakes import FakeGuild, FakeInteraction


# ------------------------------------------------------------------- gpu_utils

def fake_torch(cuda=False, hip=None, mps=False, name="Test GPU", empty_cache_raises=False):
    calls = SimpleNamespace(empty_cache=0)

    def empty_cache():
        calls.empty_cache += 1
        if empty_cache_raises:
            raise RuntimeError("boom")

    class OOM(RuntimeError):
        pass

    return SimpleNamespace(
        __version__="2.6.0",
        version=SimpleNamespace(cuda=None if hip else ("12.4" if cuda else None), hip=hip),
        cuda=SimpleNamespace(
            is_available=lambda: cuda,
            empty_cache=empty_cache,
            get_device_name=lambda device=None: name,
            OutOfMemoryError=OOM,
        ),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
        mps=SimpleNamespace(empty_cache=lambda: None),
        device=lambda d: d,
        _calls=calls,
    )


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ("DRIFTBOT_DEVICE", "PYTORCH_CUDA_ALLOC_CONF", "PYTORCH_HIP_ALLOC_CONF"):
        monkeypatch.delenv(var, raising=False)


def test_nvidia_backend(monkeypatch):
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True))
    assert gpu_utils.get_device() == "cuda"
    assert gpu_utils.backend_name() == "CUDA"
    assert not gpu_utils.is_rocm()
    assert "Test GPU" in gpu_utils.describe() and "12.4" in gpu_utils.describe()


def test_rocm_uses_cuda_device_name(monkeypatch):
    """Su ROCm il device si chiama 'cuda' ma il backend è riconosciuto come ROCm."""
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True, hip="6.2.41"))
    assert gpu_utils.get_device() == "cuda"
    assert gpu_utils.is_rocm()
    assert gpu_utils.backend_name() == "ROCm"
    assert "6.2.41" in gpu_utils.describe()


def test_cpu_and_mps(monkeypatch):
    monkeypatch.setattr(gpu_utils, "torch", fake_torch())
    assert (gpu_utils.get_device(), gpu_utils.backend_name()) == ("cpu", "CPU")
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(mps=True))
    assert (gpu_utils.get_device(), gpu_utils.backend_name()) == ("mps", "MPS")


def test_device_override(monkeypatch):
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True))
    monkeypatch.setenv("DRIFTBOT_DEVICE", "cuda:1")
    assert gpu_utils.get_device() == "cuda:1"
    assert gpu_utils.backend_name() == "CUDA"
    monkeypatch.setenv("DRIFTBOT_DEVICE", "cpu")
    assert gpu_utils.backend_name() == "CPU"


def test_cuda_check_exception_falls_back_to_cpu(monkeypatch):
    broken = fake_torch(cuda=True)
    broken.cuda.is_available = lambda: (_ for _ in ()).throw(RuntimeError("driver rotto"))
    monkeypatch.setattr(gpu_utils, "torch", broken)
    assert gpu_utils.get_device() == "cpu"


def test_everything_is_safe_without_torch(monkeypatch):
    monkeypatch.setattr(gpu_utils, "torch", None)
    assert gpu_utils.get_device() == "cpu"
    assert not gpu_utils.is_rocm()
    assert "non installato" in gpu_utils.describe()
    gpu_utils.free_gpu_memory()  # non solleva
    gpu_utils.configure_allocator()
    assert not gpu_utils.is_out_of_memory(RuntimeError("altro"))
    assert gpu_utils.is_out_of_memory(RuntimeError("CUDA out of memory"))


def test_allocator_nvidia_vs_rocm(monkeypatch):
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True))
    gpu_utils.configure_allocator()
    assert "expandable_segments:True" in os.environ["PYTORCH_CUDA_ALLOC_CONF"]
    assert "PYTORCH_HIP_ALLOC_CONF" not in os.environ

    monkeypatch.delenv("PYTORCH_CUDA_ALLOC_CONF")
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True, hip="6.2"))
    gpu_utils.configure_allocator()
    # su ROCm niente expandable_segments (non affidabile su tutte le versioni)
    assert os.environ["PYTORCH_HIP_ALLOC_CONF"] == "max_split_size_mb:128"
    assert "PYTORCH_CUDA_ALLOC_CONF" not in os.environ


def test_allocator_respects_user_setting(monkeypatch):
    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True))
    monkeypatch.setenv("PYTORCH_CUDA_ALLOC_CONF", "garbage_collection_threshold:0.8")
    gpu_utils.configure_allocator()
    assert os.environ["PYTORCH_CUDA_ALLOC_CONF"] == "garbage_collection_threshold:0.8"


def test_free_gpu_memory(monkeypatch):
    torch = fake_torch(cuda=True)
    monkeypatch.setattr(gpu_utils, "torch", torch)
    gpu_utils.free_gpu_memory()
    assert torch._calls.empty_cache == 1

    monkeypatch.setattr(gpu_utils, "torch", fake_torch(cuda=True, empty_cache_raises=True))
    gpu_utils.free_gpu_memory()  # l'errore viene ingoiato

    cpu = fake_torch()
    monkeypatch.setattr(gpu_utils, "torch", cpu)
    gpu_utils.free_gpu_memory()
    assert cpu._calls.empty_cache == 0


def test_out_of_memory_detection(monkeypatch):
    torch = fake_torch(cuda=True, hip="6.2")
    monkeypatch.setattr(gpu_utils, "torch", torch)
    assert gpu_utils.is_out_of_memory(torch.cuda.OutOfMemoryError("x"))
    assert gpu_utils.is_out_of_memory(RuntimeError("HIP out of memory. Tried to allocate"))
    assert not gpu_utils.is_out_of_memory(ValueError("altro"))


# ----------------------------------------------------------------- helper dei percorsi

def test_resolve_in_dir(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    (base / "ok.wav").write_text("x")
    (tmp_path / "segreto.txt").write_text("x")

    assert resolve_in_dir(base, "ok.wav") == (base / "ok.wav").resolve()
    assert resolve_in_dir(base, "../segreto.txt") is None
    assert resolve_in_dir(base, "sub/../../segreto.txt") is None
    assert resolve_in_dir(base, str(tmp_path / "segreto.txt")) is None   # percorso assoluto
    assert resolve_in_dir(base, "/etc/passwd") is None
    assert resolve_in_dir(base, "") is None and resolve_in_dir(base, ".") is None
    assert resolve_in_dir(base, "a\x00b") is None

    (base / "link").symlink_to(tmp_path)   # symlink che esce dalla cartella
    assert resolve_in_dir(base, "link/segreto.txt") is None


# --------------------------------------------------------------------- main.py

@pytest.fixture
def main_module():
    import main
    return main


async def test_tree_blocks_dms(main_module):
    tree = main_module.BotTree.__new__(main_module.BotTree)
    dm = FakeInteraction(FakeGuild())
    dm.guild = None
    assert await tree.interaction_check(dm) is False
    assert "solo in un server" in dm.last

    ok = FakeInteraction(FakeGuild())
    assert await tree.interaction_check(ok) is True


async def test_tree_error_handler_never_leaks_exceptions(main_module, caplog):
    tree = main_module.BotTree.__new__(main_module.BotTree)
    it = FakeInteraction(FakeGuild())
    it.command = SimpleNamespace(qualified_name="boom", name="boom")

    error = app_commands.CommandInvokeError(it.command, KeyError("dettagli interni"))
    await tree.on_error(it, error)
    assert it.last == "❌ Si è verificato un errore imprevisto. Riprova tra poco."
    assert "dettagli interni" not in it.last           # niente dettagli all'utente
    assert "boom" in caplog.text                       # ma sono nel log


async def test_tree_error_handler_check_failures(main_module):
    tree = main_module.BotTree.__new__(main_module.BotTree)

    # check che ha già risposto (es. DM): nessun secondo messaggio
    it = FakeInteraction(FakeGuild())
    await it.response.send_message("già risposto")
    await tree.on_error(it, app_commands.CheckFailure())
    assert it.texts() == ["già risposto"]

    it = FakeInteraction(FakeGuild())
    await tree.on_error(it, app_commands.CheckFailure())
    assert "Non puoi usare" in it.last


async def test_reply_ephemeral_swallows_expired_interaction(main_module):
    it = FakeInteraction(FakeGuild())
    it.followup_error = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown interaction")
    await it.response.send_message("x")      # ora is_done() è True -> usa followup, che solleva
    await main_module.reply_ephemeral(it, "ciao")   # non deve sollevare


async def test_setup_hook_survives_a_broken_cog(main_module, tmp_path, monkeypatch, capsys):
    for name in ("good.py", "broken.py", "_private.py", "__init__.py"):
        (tmp_path / name).write_text("")
    monkeypatch.setattr(main_module, "COGS_DIR", tmp_path)

    loaded = []

    async def fake_load(name):
        if name.endswith("broken"):
            raise ImportError("libreria GPU non compatibile")
        loaded.append(name)

    async def fake_sync():
        return []

    bot = main_module.MyBot()
    monkeypatch.setattr(bot, "load_extension", fake_load)
    monkeypatch.setattr(bot.tree, "sync", fake_sync)
    await bot.setup_hook()                     # non deve sollevare

    assert loaded == ["cogs.good"]             # i privati/__init__ sono saltati, il cog rotto no
    assert "broken.py" in capsys.readouterr().out
    await bot.close()


def test_bot_blocks_mass_mentions(main_module):
    bot = main_module.MyBot()
    mentions = bot.allowed_mentions
    assert mentions.everyone is False and mentions.roles is False and mentions.users is True
