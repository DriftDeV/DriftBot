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
sudo dnf install -y python3 python3-pip python3-devel

echo "🟢 Configurazione NVIDIA CUDA Toolkit..."
# Aggiunge repo Nvidia (Adatta la versione fedora se necessario, es: fedora39 o fedora40)
# Usa fedora39 come base sicura che funziona sulle versioni recenti
# 1. Installa il plugin necessario
sudo dnf install -y dnf-plugins-core

# 2. Ora riprova il comando che ti ha dato errore
sudo curl -o /etc/yum.repos.d/cuda-fedora39.repo https://developer.download.nvidia.com/compute/cuda/repos/fedora39/x86_64/cuda-fedora39.repo
sudo dnf clean all
sudo dnf install -y cuda-toolkit

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
