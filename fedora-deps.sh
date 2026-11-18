#!/bin/bash

# Ferma lo script se un comando fallisce
set -e

echo "🚀 Inizio configurazione ambiente di sviluppo su Fedora..."

# 1. Aggiornamento del sistema
echo "📦 Aggiornamento dei repository..."
sudo dnf update -y

# 2. Installazione strumenti di sviluppo base (C/C++, Make, Git)
echo "🛠️ Installazione GCC, G++, Make e Git..."
sudo dnf install -y gcc gcc-c++ make git curl wget
# 3. Installazione Python e librerie di sviluppo
echo "🐍 Installazione Python3, Pip e pacchetti Devel..."
sudo dnf install -y python3 python3-pip python3-devel espeak-ng

# GPU: ./fedora-deps.sh [nvidia|amd|none]   (default: rilevamento automatico)
GPU="${1:-auto}"
if [ "$GPU" = "auto" ]; then
    GPU_INFO="$(lspci 2>/dev/null | grep -Ei 'vga|3d|display' || true)"
    if echo "$GPU_INFO" | grep -qi nvidia; then
        GPU="nvidia"
    elif echo "$GPU_INFO" | grep -Eqi 'amd|ati|radeon'; then
        GPU="amd"
    else
        GPU="none"
    fi
fi
echo "🎮 GPU selezionata: $GPU"

if [ "$GPU" = "nvidia" ]; then
    echo "🟢 Configurazione NVIDIA CUDA Toolkit..."
    # Aggiunge repo Nvidia (Adatta la versione fedora se necessario, es: fedora39 o fedora40)
    # Usa fedora39 come base sicura che funziona sulle versioni recenti
    # 1. Installa il plugin necessario
    sudo dnf install -y dnf-plugins-core

    # 2. Ora riprova il comando che ti ha dato errore
    sudo curl -o /etc/yum.repos.d/cuda-fedora39.repo https://developer.download.nvidia.com/compute/cuda/repos/fedora39/x86_64/cuda-fedora39.repo
    sudo dnf clean all
    sudo dnf install -y cuda-toolkit
elif [ "$GPU" = "amd" ]; then
    echo "🔴 Configurazione AMD ROCm..."
    # Le wheel PyTorch ROCm includono già le librerie ROCm: servono solo il driver del kernel
    # (amdgpu, già incluso in Fedora) e i permessi su /dev/kfd e /dev/dri.
    sudo usermod -aG render,video "$USER"
    echo "ℹ️  Esci e rientra nella sessione per applicare i gruppi 'render' e 'video'."
    echo "ℹ️  Poi: make install GPU=rocm"
    echo "ℹ️  GPU consumer non ufficialmente supportate (es. RX 6600/7600): imposta"
    echo "    HSA_OVERRIDE_GFX_VERSION=10.3.0 (RDNA2) oppure 11.0.0 (RDNA3) nel file .env o nella shell."
else
    echo "⚪ Nessuna GPU dedicata rilevata: salto la configurazione GPU (PyTorch userà la CPU)."
fi

# 4. Installazione Visual Studio Code
echo "💻 Configurazione repository Microsoft e installazione VS Code..."
sudo rpm --import https://packages.microsoft.com/keys/microsoft.asc
sudo sh -c 'echo -e "[code]\nname=Visual Studio Code\nbaseurl=https://packages.microsoft.com/yumrepos/vscode\nenabled=1\ngpgcheck=1\ngpgkey=https://packages.microsoft.com/keys/microsoft.asc" > /etc/yum.repos.d/vscode.repo'

sudo dnf install -y code

# 5. Pulizia cache
echo "🧹 Pulizia cache DNF..."
sudo dnf clean all

# 6. Export su Bazzite (Solo se siamo in Distrobox)
if command -v distrobox-export &> /dev/null; then
    echo "📤 Rilevato Distrobox: Esporto VS Code al menu principale..."
    distrobox-export --app code
else
    echo "ℹ️ Non siamo in Distrobox o comando export non trovato. Salto esportazione."
fi

echo "✅ Installazione completata con successo!"
echo "Ora puoi avviare VS Code digitando 'code' o cercandolo nel menu applicazioni."
