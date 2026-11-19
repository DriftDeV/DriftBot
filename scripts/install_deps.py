#!/usr/bin/env python3
"""
Installa le dipendenze di pyproject.toml nel Python che esegue lo script (il venv attivo, o quello dell'immagine Docker).

Perché non basta `pip install -e .`: rvc-python 0.1.0 fissa `requests==2.31.0`, mentre yt-dlp vuole `requests>=2.32.2`.
Messi nello stesso comando, pip rifiuta il conflitto (ResolutionImpossible). Installati in due passi pip lo accetta
con un avviso e sale a requests 2.32+: rvc-python funziona lo stesso (è la situazione del venv di sviluppo).
Quindi: prima tutto il resto, poi yt-dlp.

Uso:
    python scripts/install_deps.py                     # dipendenze del progetto
    python scripts/install_deps.py --extra dev         # + gli strumenti di sviluppo (si può ripetere)
    python scripts/install_deps.py --upgrade           # ogni altra opzione va a pip (es. --upgrade, --dry-run)

Il progetto stesso si registra a parte, con `pip install -e . --no-deps` (lo fa il Makefile).
"""

import subprocess
import sys
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def load_project() -> dict:
    try:
        import tomllib                       # Python 3.11+
    except ModuleNotFoundError:              # Python 3.10: pip ne include una copia
        from pip._vendor import tomli as tomllib
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def split_requirements(project: dict, extras: list[str]) -> tuple[list[str], list[str]]:
    """(dipendenze da installare per prime, yt-dlp da installare per ultimo)."""
    requirements = list(project["dependencies"])
    for extra in extras:
        requirements += project["optional-dependencies"][extra]
    last = [r for r in requirements if r.lower().startswith("yt-dlp")]
    return [r for r in requirements if r not in last], last


def main(argv: list[str]) -> int:
    extras: list[str] = []
    pip_args: list[str] = []
    args = iter(argv)
    for arg in args:
        if arg == "--extra":
            extras.append(next(args))
        else:
            pip_args.append(arg)

    first, last = split_requirements(load_project(), extras)
    for group in (first, last):
        if group:
            subprocess.check_call([sys.executable, "-m", "pip", "install", *pip_args, *group])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
