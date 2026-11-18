"""
Coerenza tra documentazione, script di installazione e configurazione: istruzioni che rimandano a file o
comandi che non esistono sono un difetto vero (es. il README citava `setup-windows.ps1` senza che il file ci fosse).
"""

import re
import tomllib
from pathlib import Path

import pytest

import main

ROOT = Path(__file__).resolve().parent.parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
MAKEFILE = (ROOT / "Makefile").read_text(encoding="utf-8")
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
SETUP_PS1 = (ROOT / "setup-windows.ps1").read_text(encoding="utf-8")


# ----------------------------------------------------------------- README <-> repository

def test_scripts_cited_in_the_readme_exist():
    cited = set(re.findall(r"\.\\([\w.-]+\.ps1)", README)) | set(re.findall(r"(?<![\w/])\./([\w.-]+\.sh)", README))
    assert "setup-windows.ps1" in cited                          # il caso che ha originato il test
    for name in cited:
        assert (ROOT / name).is_file(), f"il README cita {name}, che non esiste"


def test_make_targets_cited_in_the_readme_exist():
    targets = set(re.findall(r"^([a-z][\w-]*):", MAKEFILE, flags=re.MULTILINE))
    cited = set(re.findall(r"`make ([a-z][\w-]*)", README))
    assert {"install", "test", "run", "install-torch"} <= cited
    missing = sorted(cited - targets)
    assert not missing, f"il README cita target make inesistenti: {missing}"


def test_readme_does_not_point_to_files_that_were_never_there():
    assert not (ROOT / "requirements.txt").exists()
    assert "requirements.txt" not in README                       # non esiste: si installa con make/pip install -e .


# ---------------------------------------------------- strumenti usati dal Makefile <-> dipendenze

def test_every_dev_tool_used_by_the_makefile_is_a_dev_dependency():
    """`make test` usava --cov e `make lint` usava pylint, ma nessuno dei due era installato."""
    dev = {re.split(r"[<>=!~\[ ]", d)[0].lower() for d in PYPROJECT["project"]["optional-dependencies"]["dev"]}
    needed = {"pytest", "flake8", "black", "isort", "mypy", "pylint"}
    if "--cov" in MAKEFILE:
        needed.add("pytest-cov")
    for tool in sorted(needed):
        assert re.search(rf"\b{re.escape(tool.replace('pytest-cov', 'pytest'))}\b", MAKEFILE), tool
        assert tool in dev, f"il Makefile usa {tool}, ma non è nelle dipendenze di sviluppo"


def test_editorconfig_matches_black_line_length():
    editorconfig = (ROOT / ".editorconfig").read_text(encoding="utf-8")
    py_section = editorconfig.split("[*.py]")[1].split("[")[0]
    assert int(re.search(r"max_line_length\s*=\s*(\d+)", py_section).group(1)) == PYPROJECT["tool"]["black"]["line-length"]


def test_gitattributes_normalizes_line_endings():
    assert "text=auto" in (ROOT / ".gitattributes").read_text(encoding="utf-8")


# --------------------------------------------------------------------- setup-windows.ps1
# (PowerShell non è disponibile nei test: si controlla la struttura e la coerenza con il resto del progetto)

def test_windows_script_is_structurally_sound():
    assert SETUP_PS1.count("{") == SETUP_PS1.count("}") and SETUP_PS1.count("(") == SETUP_PS1.count(")")
    assert SETUP_PS1.count('"') % 2 == 0
    assert all(ord(c) < 128 for c in SETUP_PS1)                   # solo ASCII: nessun problema di codifica
    assert "\r" not in SETUP_PS1.replace("\r\n", "")              # niente fine riga misti


def test_windows_script_matches_the_project():
    # stessa scelta di GPU del Makefile (su Windows ROCm non esiste)
    assert 'ValidateSet("auto", "cuda", "cpu")' in SETUP_PS1
    assert 'make install "GPU=$Gpu"' in SETUP_PS1 and 'make install-dev "GPU=$Gpu"' in SETUP_PS1
    assert re.search(r"^GPU \?= auto", MAKEFILE, flags=re.MULTILINE)
    # Python 3.10: la versione del progetto (fairseq non supporta le successive)
    minimum = PYPROJECT["project"]["requires-python"].lstrip(">=")
    assert minimum == "3.10" and "python310" in SETUP_PS1 and "python311" not in SETUP_PS1
    # ogni funzione definita è usata, ogni funzione usata è definita
    defined = set(re.findall(r"^function ([\w-]+)", SETUP_PS1, flags=re.MULTILINE))
    for name in defined - {"Test-CommandExists", "Test-Administrator"}:
        assert SETUP_PS1.count(name) >= 2, f"{name} è definita ma non viene mai chiamata"
    called = set(re.findall(r"^\s+(Install-[\w]+)\s*$", SETUP_PS1, flags=re.MULTILINE))
    assert called and called <= defined, called - defined


# ----------------------------------------------------------------------------- avvio di main.py

@pytest.fixture
def run_main(monkeypatch):
    """Esegue main.run() con asyncio.run sostituito: si osserva solo la gestione degli errori di avvio."""
    monkeypatch.setattr(main, "TOKEN", "token-di-prova")
    monkeypatch.setattr(main.discord.utils, "setup_logging", lambda **kwargs: None)

    def make(error=None):
        def fake_run(coroutine):
            coroutine.close()                                       # evita il warning "coroutine never awaited"
            if error is not None:
                raise error
        monkeypatch.setattr(main.asyncio, "run", fake_run)
        return main.run
    return make


def test_missing_token_exits_with_a_clear_message(run_main, monkeypatch):
    run = run_main()
    monkeypatch.setattr(main, "TOKEN", None)
    with pytest.raises(SystemExit, match="DISCORD_TOKEN mancante"):
        run()


def test_invalid_token_exits_with_a_clear_message(run_main):
    with pytest.raises(SystemExit, match="Token Discord non valido"):
        run_main(main.discord.LoginFailure("401"))()


def test_missing_privileged_intent_exits_with_a_clear_message(run_main):
    """Prima: PrivilegedIntentsRequired non è un LoginFailure e finiva in un traceback grezzo."""
    with pytest.raises(SystemExit) as exit_info:
        run_main(main.discord.PrivilegedIntentsRequired(None))()
    message = str(exit_info.value)
    assert "Message Content Intent" in message and "Developer Portal" in message


def test_normal_start_and_ctrl_c_do_not_exit_with_errors(run_main):
    run_main()()                                                    # avvio normale: nessuna eccezione
    run_main(KeyboardInterrupt())()                                 # Ctrl+C: chiusura silenziosa


def test_the_requested_intents_are_the_documented_ones():
    """Il README dice di attivare Message Content Intent perché il bot lo richiede: se cambia, va aggiornato."""
    assert main.intents.message_content is True and main.intents.voice_states and main.intents.guilds
    assert not main.intents.members and not main.intents.presences          # gli altri intent privilegiati non servono
    assert "Message Content Intent" in README
