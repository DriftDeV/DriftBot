"""
scripts/install_deps.py e Makefile: rvc-python fissa requests==2.31.0 e yt-dlp vuole requests>=2.32.2, quindi
`pip install -e .` fallisce con ResolutionImpossible. Le dipendenze si installano in due passi (yt-dlp per ultimo).
"""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")

spec = importlib.util.spec_from_file_location("install_deps", ROOT / "scripts" / "install_deps.py")
install_deps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install_deps)


def test_ytdlp_goes_last_and_everything_else_goes_first():
    first, last = install_deps.split_requirements(install_deps.load_project(), [])
    assert last and all(r.lower().startswith("yt-dlp") for r in last)
    assert not any(r.lower().startswith("yt-dlp") for r in first)
    assert any(r.lower().startswith("rvc-python") for r in first)          # il motivo dello script
    assert any(r.lower().startswith("discord.py") for r in first)


def test_extras_are_added_to_the_first_group():
    first, last = install_deps.split_requirements(install_deps.load_project(), ["dev"])
    assert any(r.lower().startswith("pytest") for r in first) and all("pytest" not in r for r in last)


def test_installs_in_two_pip_calls_and_forwards_the_pip_options(monkeypatch):
    calls = []
    monkeypatch.setattr(install_deps.subprocess, "check_call", lambda cmd: calls.append(cmd))
    assert install_deps.main(["--extra", "dev", "--upgrade"]) == 0
    assert len(calls) == 2
    for cmd in calls:
        assert cmd[:4] == [sys.executable, "-m", "pip", "install"] and "--upgrade" in cmd
        assert "--extra" not in cmd and "dev" not in cmd                    # l'extra lo gestisce lo script, non pip
    assert all(r.lower().startswith("yt-dlp") for r in calls[1][5:])        # il secondo passo è solo yt-dlp
    assert not any(r.lower().startswith("yt-dlp") for r in calls[0])


def test_a_failing_pip_stops_the_installation(monkeypatch):
    def boom(cmd):
        raise install_deps.subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(install_deps.subprocess, "check_call", boom)
    with pytest.raises(install_deps.subprocess.CalledProcessError):
        install_deps.main([])


def test_the_makefile_uses_the_script_and_never_a_plain_editable_install():
    assert "scripts/install_deps.py" in MAKEFILE
    for line in MAKEFILE.splitlines():
        if not line.lstrip().startswith("#") and re.search(r"pip install .*-e ", line):
            assert "--no-deps" in line, f"`pip install -e` senza --no-deps rimette il conflitto requests: {line.strip()}"


def test_every_install_path_goes_through_install_project():
    """install, install-dev e update usano lo stesso target, così il conflitto si risolve in un solo punto."""
    for target in ("install", "install-dev", "update"):
        recipe = re.search(rf"^{target}:\n(.*?)(?=^[a-z][\w-]*:|\Z)", MAKEFILE, flags=re.MULTILINE | re.DOTALL).group(1)
        assert "install-project" in recipe, target
