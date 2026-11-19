.PHONY: help install install-torch install-project install-pkuseg install-dev venv clean run dashboard lint format type-check test pre-commit update

PYTHON := python3.10
VENV := venv
BIN := $(VENV)/bin
ifeq ($(OS),Windows_NT)
    BIN := $(VENV)\Scripts
    RM := del /Q
    RMDIR := rmdir /S /Q
    VENV_ACTIVE := $(if $(VIRTUAL_ENV),1,0)
else
	DETECTED_OS := $(shell uname -s)
    RM := rm -f
    RMDIR := rm -rf
    VENV_ACTIVE := $(if $(VIRTUAL_ENV),1,0)
endif

# Helper function to check if venv is active or create it
CHECK_VENV = if [ "$(VENV_ACTIVE)" = "1" ]; then echo "Using active venv"; else $(MAKE) venv; fi

# pip e python del venv attivo oppure di quello locale
PIP := $(if $(filter 1,$(VENV_ACTIVE)),pip,$(BIN)/pip)
PY := $(if $(filter 1,$(VENV_ACTIVE)),python,$(BIN)/python)

# --- GPU -------------------------------------------------------------------
# make install GPU=cuda   -> NVIDIA (CUDA)
# make install GPU=rocm   -> AMD (ROCm, solo Linux)
# make install GPU=cpu    -> senza GPU
# Default (auto): nvidia-smi presente = cuda, /dev/kfd presente = rocm, altrimenti cpu.
# PyTorch va installato dall'indice giusto PRIMA delle altre dipendenze: su PyPI (Linux)
# c'e' solo la build CUDA e su una macchina AMD ripiegherebbe silenziosamente sulla CPU.
GPU ?= auto
ifeq ($(GPU),auto)
ifeq ($(OS),Windows_NT)
    GPU_KIND := cuda
else ifneq ($(shell command -v nvidia-smi 2>/dev/null),)
    GPU_KIND := cuda
else ifneq ($(wildcard /dev/kfd),)
    GPU_KIND := rocm
else
    GPU_KIND := cpu
endif
else
    GPU_KIND := $(GPU)
endif

# Versioni richieste da chatterbox-tts (torch==2.6.0). Cambia l'indice se usi un'altra versione ROCm/CUDA.
TORCH_VERSION := 2.6.0
TORCHVISION_VERSION := 0.21.0
TORCH_INDEX_cuda := https://download.pytorch.org/whl/cu124
TORCH_INDEX_rocm := https://download.pytorch.org/whl/rocm6.2.4
TORCH_INDEX_cpu  := https://download.pytorch.org/whl/cpu
TORCH_INDEX ?= $(TORCH_INDEX_$(GPU_KIND))

help:
	@echo "❓ Discord Python bot makefile Helper ❓"
	@echo ""
	@echo "make install-deps  > Installs dependencies for Mac and Linux"
	@echo "                     (Use PowerShell script for Windows!)"
	@echo "make install-dev   > Create Python virtual environment and installs"
	@echo "                     dependencies"
	@echo "make run           > Runs the bot!"
	@echo "make dashboard     > Dashboard web in un processo separato dal bot"
	@echo "make install GPU=cuda|rocm|cpu"
	@echo "                   > Scegli NVIDIA (CUDA), AMD (ROCm) o CPU (default: auto)"
	@echo "make install-torch > Installa solo PyTorch per la GPU scelta"
	@echo "make test-py       > Verifica che PyTorch veda la GPU"

venv:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install "pip<24.1"
	$(MAKE) install-torch
	$(BIN)/pip install "omegaconf==2.0.6" "hydra-core==1.0.7"
	$(BIN)/pip install "fairseq==0.12.2"
	$(BIN)/pip install "numpy>=1.23.5,<2.0.0" "librosa==0.9.2" "scipy==1.11.4"

install-torch:
ifeq ($(GPU_KIND),rocm)
	@echo "🔴 Installo PyTorch per AMD ROCm ($(TORCH_INDEX))"
	@echo "   Serve il driver amdgpu e l'utente nei gruppi 'render' e 'video'."
else ifeq ($(GPU_KIND),cuda)
	@echo "🟢 Installo PyTorch per NVIDIA CUDA ($(TORCH_INDEX))"
else
	@echo "⚪ Installo PyTorch per CPU ($(TORCH_INDEX))"
endif
	$(PIP) install torch==$(TORCH_VERSION) torchaudio==$(TORCH_VERSION) torchvision==$(TORCHVISION_VERSION) --index-url $(TORCH_INDEX)

install-brew:
	@echo "👀 -> Controllo presenza Homebrew..."
	@# Usiamo 'command -v' per vedere se brew esiste
	@if ! command -v brew >/dev/null 2>&1; then \
			echo "❌ -> Homebrew non trovato. Installazione in corso..."; \
			/bin/bash -c "$$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"; \
			echo "✅ -> Installazione completata."; \
	else \
			echo "✅ -> Homebrew è già installato."; \
	fi

reinstall-xcode :
	echo "Provo a reinstallare da zero..."; \
	sudo rm -rf /Library/Developer/CommandLineTools; \
	xcode-select --install; \

FFMPEG_URL := https://evermeet.cx/ffmpeg/ffmpeg-6.0.zip
INSTALL_DIR := /usr/local/bin

mac-ffmpeg-static:
	@echo "Scaricamento di FFmpeg statico..."
	@curl -L $(FFMPEG_URL) -o ffmpeg.zip
	@echo "Estrazione..."
	@unzip -o -q ffmpeg.zip
	@echo "Installazione in $(INSTALL_DIR) (richiede password)..."
	@sudo mv ffmpeg $(INSTALL_DIR)/ffmpeg
	@# Rimuovi il zip residuo
	@rm ffmpeg.zip
	@# Verifica permessi esecuzione
	@sudo chmod +x $(INSTALL_DIR)/ffmpeg
	@echo "FFmpeg installato con successo!"

mac-deps:
	@echo "Cerco aggiornamenti per Command Line Tools..."
	@# Cerca aggiornamenti specifici per i Command Line Tools
	@PROD=$$(softwareupdate -l | grep "\*.*Command Line Tools" | head -n 1 | awk -F"*" '{print $$2}' | sed 's/^ *//' | tr -d '\n'); \
	if [ -n "$$PROD" ]; then \
		echo "Trovato aggiornamento: $$PROD"; \
		echo "Installazione in corso (richiede password sudo)..."; \
		sudo softwareupdate -i "$$PROD" --verbose; \
	else \
		echo "Nessun aggiornamento specifico per Command Line Tools trovato."; \
	fi
	@if ! command -v python3.11 >/dev/null 2>&1; then \
		echo "🔄 -> Installo Python3.11 per MacOS... "; \
		brew install python@3.11; \
	else \
		echo "✅ -> Python3.11 già installato"; \
	fi
	@if ! command -v ffmpeg >/dev/null 2>&1; then \
		echo "🔄 -> Installo ffmpeg per MacOS... "; \
		$(MAKE) mac-ffmpeg-static; \
	else \
		echo "✅ -> ffmpeg già installato"; \
	fi

install-deps-linux:
	@echo "🐧 Rilevamento distribuzione Linux..."
	@if command -v apt-get >/dev/null 2>&1; then \
		echo "📦 Rilevato Debian/Ubuntu/Mint"; \
		sudo apt-get update; \
		sudo apt-get install -y python3.11 python3.11-venv python3-pip ffmpeg; \
	elif command -v dnf >/dev/null 2>&1; then \
		echo "📦 Rilevato Fedora/RHEL/CentOS"; \
		sudo dnf install -y python3.10 python3-pip ffmpeg; \
	elif command -v pacman >/dev/null 2>&1; then \
		echo "📦 Rilevato Arch Linux/Manjaro"; \
		sudo pacman -S --noconfirm python3.11 python-pip ffmpeg; \
	elif command -v zypper >/dev/null 2>&1; then \
		echo "📦 Rilevato OpenSUSE"; \
		sudo zypper install -y python311 python311-pip ffmpeg; \
	elif command -v apk >/dev/null 2>&1; then \
		echo "📦 Rilevato Alpine Linux"; \
		sudo apk add python3 py3-pip ffmpeg; \
	else \
		echo "❌ Distribuzione non riconosciuta automaticamente."; \
		echo "👉 Installa manualmente: Python 3.11, pip e FFmpeg."; \
		exit 1; \
	fi
	@echo "✅ Dipendenze di sistema installate!"

install-deps:
ifeq ($(OS),Windows_NT)
	@echo "⚠️  Su Windows l'installazione automatica di sistema non è supportata."
	@echo "👉 Assicurati di aver installato Python 3.11 e FFmpeg manualmente."
else
ifeq ($(DETECTED_OS),Darwin)
	@echo "🍎 Rilevato MacOS."
	$(MAKE) install-brew
	$(MAKE) mac-deps
else
	@echo "🐧 Rilevato Linux."
	$(MAKE) install-deps-linux
endif
endif

install:
	@# Verifica se python3.11 esiste, altrimenti installa le dipendenze
	@if ! command -v python3.11 >/dev/null 2>&1; then \
		echo "⚠️  Python 3.11 non trovato. Avvio installazione dipendenze di sistema..."; \
		$(MAKE) install-deps; \
	fi
ifeq ($(VENV_ACTIVE),1)
	@echo "✅ Virtual environment is already active"
	$(MAKE) install-torch
	$(MAKE) install-pkuseg
	$(MAKE) install-project
else
	@echo "📦 Creating virtual environment..."
	$(MAKE) venv
	$(MAKE) install-pkuseg
	$(MAKE) install-project
endif

# pkuseg (richiesto da chatterbox-tts) si compila solo senza isolamento, cosi' vede numpy nel venv
install-pkuseg:
	$(PIP) install "numpy>=1.24.0,<2.0.0" "Cython>=0.29.32"
	$(PIP) install pkuseg==0.0.25 --no-build-isolation

# Dipendenze di pyproject.toml + il progetto in modalita' editable. Niente `pip install -e .`: rvc-python
# (requests==2.31.0) e yt-dlp (requests>=2.32.2) sono in conflitto e pip lo rifiuta se li installa insieme;
# scripts/install_deps.py li installa in due passi. INSTALL_ARGS="--extra dev --upgrade" passa opzioni allo script.
install-project:
	$(PY) scripts/install_deps.py $(INSTALL_ARGS)
	$(PIP) install -e . --no-deps

install-dev:
	@# Verifica se python3.11 esiste, altrimenti installa le dipendenze
	@if ! command -v python3.11 >/dev/null 2>&1; then \
		echo "⚠️  Python 3.11 non trovato. Avvio installazione dipendenze di sistema..."; \
		$(MAKE) install-deps; \
	fi
ifeq ($(VENV_ACTIVE),1)
	@echo "✅ Virtual environment is already active"
	pip install --upgrade pip setuptools wheel
	$(MAKE) install-torch
	$(MAKE) install-pkuseg
	$(MAKE) install-project INSTALL_ARGS="--extra dev"
else
	@echo "🗳️  Installazione dipendenze e Pacchetti venv (DEV)"
	$(MAKE) venv
	$(MAKE) install-pkuseg
	$(MAKE) install-project INSTALL_ARGS="--extra dev"
	@echo "✅ [DONE] Pacchetti installati con successo"
endif

clean:
	@echo "Removing virtual environment..."
	$(RMDIR) $(VENV)
	@echo "Removing Python cache files..."
	$(RM) /S /Q __pycache__
	$(RM) /S /Q .pytest_cache
	$(RM) /S /Q .mypy_cache
	$(RM) /S /Q .ruff_cache
	@echo "Clean complete!"

run:
ifeq ($(VENV_ACTIVE),1)
	python src/main.py
else
	$(BIN)/python src/main.py
endif

# Dashboard in un processo separato dal bot (richiede DASHBOARD_PASSWORD nel .env)
dashboard:
ifeq ($(VENV_ACTIVE),1)
	python src/dashboard_main.py
else
	$(BIN)/python src/dashboard_main.py
endif

test-py:
ifeq ($(VENV_ACTIVE), 1)
	python src/test.py
else
	$(BIN)/python src/test.py
endif

lint:
ifeq ($(VENV_ACTIVE),1)
	@echo "Running Pylint..."
	pylint src/
	@echo "Running Flake8..."
	flake8 src/ --max-line-length=100 --ignore=E203,W503
else
	@echo "Running Pylint..."
	$(BIN)/pylint src/
	@echo "Running Flake8..."
	$(BIN)/flake8 src/ --max-line-length=100 --ignore=E203,W503
endif

format:
ifeq ($(VENV_ACTIVE),1)
	@echo "Formatting code with Black..."
	black src/ --line-length=100
	@echo "Sorting imports with isort..."
	isort src/ --profile black --line-length=100
else
	@echo "Formatting code with Black..."
	$(BIN)/black src/ --line-length=100
	@echo "Sorting imports with isort..."
	$(BIN)/isort src/ --profile black --line-length=100
endif

type-check:
ifeq ($(VENV_ACTIVE),1)
	@echo "Running mypy type checking..."
	mypy src/ --ignore-missing-imports
else
	@echo "Running mypy type checking..."
	$(BIN)/mypy src/ --ignore-missing-imports
endif

test:
ifeq ($(VENV_ACTIVE),1)
	@echo "Running pytest..."
	pytest tests/ -v --cov=src --cov-report=html
else
	@echo "Running pytest..."
	$(BIN)/pytest tests/ -v --cov=src --cov-report=html
endif

pre-commit: format lint type-check
	@echo "Pre-commit checks passed!"

update:
	$(PIP) install --upgrade pip setuptools wheel
	$(MAKE) install-project INSTALL_ARGS="--extra dev --upgrade"

.DEFAULT_GOAL := help
