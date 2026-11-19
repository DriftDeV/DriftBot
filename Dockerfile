# DriftBot in un container (VPS, server, produzione).
#
#   docker build -t driftbot .                                   # CPU (default: va su qualsiasi VPS)
#   docker build -t driftbot --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu124 .      # NVIDIA
#   docker build -t driftbot --build-arg TORCH_INDEX=https://download.pytorch.org/whl/rocm6.2.4 .  # AMD (solo Linux)
#
# Meglio con docker-compose.yml (volumi, riavvio, porte): vedi la sezione "Docker" del README.
# I nomi completi delle immagini (docker.io/...) servono a Podman, che altrimenti chiede da quale registro scaricarle.

# ---------------------------------------------------------------- 1. build: compila e installa le dipendenze
FROM docker.io/library/python:3.10-slim-bookworm AS builder

# Indice dei wheel di PyTorch: decide CPU, CUDA o ROCm (stesso ruolo di GPU=... nel Makefile)
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
ARG TORCH_VERSION=2.6.0
ARG TORCHVISION_VERSION=0.21.0

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Compilatori: fairseq, pyworld e pkuseg non hanno wheel per tutte le piattaforme
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Stesso ordine del Makefile (`make venv` + `make install`). L'ordine conta:
#  - pip 24.0 (<24.1): fairseq 0.12.2 e omegaconf 2.0.6 hanno metadati che i pip più nuovi rifiutano, mentre
#    il 23.0.1 dell'immagine non legge alcuni wheel moderni (typing_extensions) e finisce a compilarli;
#  - PyTorch prima di tutto, dall'indice giusto: su PyPI (Linux) c'è solo la build CUDA;
#  - pkuseg (richiesto da chatterbox-tts) si compila solo senza isolamento, vedendo numpy.
RUN pip install "pip==24.0" \
    && pip install torch==${TORCH_VERSION} torchaudio==${TORCH_VERSION} torchvision==${TORCHVISION_VERSION} \
        --index-url ${TORCH_INDEX} \
    && pip install "omegaconf==2.0.6" "hydra-core==1.0.7" \
    && pip install "fairseq==0.12.2" \
    && pip install "numpy>=1.23.5,<2.0.0" "librosa==0.9.2" "scipy==1.11.4" "Cython>=0.29.32" \
    && pip install "pkuseg==0.0.25" --no-build-isolation

# Dipendenze del progetto, lette da pyproject.toml (cache dei layer: il codice cambia più spesso delle dipendenze).
# Il bot gira da /app/src, quindi il pacchetto del progetto non si installa. Lo script installa yt-dlp per ultimo:
# rvc-python 0.1.0 fissa requests==2.31.0 mentre yt-dlp vuole requests>=2.32.2, e pip rifiuta il conflitto se li
# installa insieme (è lo stesso script che usa il Makefile, vedi scripts/install_deps.py).
COPY pyproject.toml ./
COPY scripts/install_deps.py ./scripts/install_deps.py
RUN python scripts/install_deps.py

# ---------------------------------------------------------------- 2. runtime: solo ciò che serve per girare
FROM docker.io/library/python:3.10-slim-bookworm

# ffmpeg: tutto l'audio; libopus0: voce di Discord; libsndfile1: soundfile;
# espeak-ng: /tts (pyttsx3 su Linux). Node serve a yt-dlp per le sfide JavaScript di YouTube:
# lo si copia da un'immagine Node perché quello di Debian bookworm (v18) è troppo vecchio per yt-dlp.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 libsndfile1 espeak-ng libespeak-ng1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=docker.io/library/node:22-slim /usr/local/bin/node /usr/local/bin/node

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/cache/huggingface \
    TORCH_HOME=/cache/torch \
    XDG_CACHE_HOME=/cache

# Utente senza privilegi: il bot non ha motivo di girare come root
RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /app/src/cogs/data /app/src/cogs/RVC/models /cache \
    && chown -R bot:bot /app /cache

COPY --from=builder /opt/venv /opt/venv
COPY --chown=bot:bot src/ /app/src/

USER bot
WORKDIR /app

# Dati da conservare fuori dal container (database, suoni, voci, modelli RVC, modelli scaricati da Hugging Face)
VOLUME ["/app/src/cogs/data", "/app/src/cogs/RVC/models", "/cache"]

# Dashboard (solo se DASHBOARD_PASSWORD è impostata e DASHBOARD_HOST=0.0.0.0)
EXPOSE 8080

# Il bot chiude il database in modo pulito solo con SIGINT (asyncio.run -> KeyboardInterrupt): con il SIGTERM
# predefinito di Docker le scritture ancora in coda andrebbero perse.
STOPSIGNAL SIGINT

CMD ["python", "src/main.py"]
