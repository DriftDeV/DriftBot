"""scripts/smoke_cogs.py: lo usa il workflow di installazione/container con le librerie vere, qui con i moduli finti."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("smoke_cogs", ROOT / "scripts" / "smoke_cogs.py")
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


async def test_all_cogs_load_and_every_expected_command_is_registered():
    assert await smoke.run() == []


async def test_a_missing_command_is_reported(monkeypatch):
    monkeypatch.setattr(smoke, "EXPECTED_COMMANDS", smoke.EXPECTED_COMMANDS | {"comando-che-non-esiste"})
    assert await smoke.run() == ["comando /comando-che-non-esiste non registrato"]


async def test_the_expected_commands_are_documented_in_the_readme():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for name in smoke.EXPECTED_COMMANDS:
        assert f"/{name}" in readme or f"`{name}`" in readme, f"/{name} non è nel README"


def test_exit_code_reflects_the_problems(monkeypatch, capsys):
    async def broken():
        return ["cog finto: ImportError"]

    monkeypatch.setattr(smoke, "run", broken)
    assert smoke.main() == 1
    assert "❌ cog finto: ImportError" in capsys.readouterr().out
