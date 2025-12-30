# DriftcoordBot 🎤

Un bot Discord intelligente per la clonazione vocale e il text-to-speech avanzato.

## 📖 Descrizione

DriftcoordBot è un bot Discord progettato per offrire funzionalità avanzate di Text-to-Speech (TTS) e clonazione vocale. Supporta il riconoscimento vocale, la generazione di parlato sintetico e l'integrazione con vari modelli di AI per la creazione di cover vocali. Il bot è costruito con architettura modulare basata su Cogs, rendendo facile l'estensione e la manutenzione.

## ✨ Funzionalità Principali

### Funzionalità TTS
- 🎙️ Clonazione vocale avanzata tramite TTS
- 🌍 Supporto per più lingue (italiano, inglese, etc.)
- 🎵 Generazione di cover musicali con AI (AI Cover)
- 🔊 Soundboard personalizzabili per server Discord
- 👤 Creazione e gestione di speaker personalizzati

### Gestione del Bot
- 🤖 Slash Commands moderni
- 🎯 Architettura modulare basata su Cogs
- 📦 Dipendenze fissate per ambienti riproducibili
- 🚀 Setup automatico con Makefile e PowerShell
- 🔧 Comandi di amministrazione avanzati

### Integrazioni
- 🗣️ Integrazione con Coqui TTS
- 🎼 Support per RVC (Retrieval-based Voice Conversion)

## 📋 Requisiti

- Python 3.10
- Librerie specificate in `requirements.txt`
- Per macOS: Homebrew (opzionale)

## 🚀 Quick Start

### Windows

**Metodo 1: Setup automatico (consigliato)**

```powershell
# Eseguire PowerShell come Amministratore
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\setup-windows.ps1
```

Con dipendenze di sviluppo:

```powershell
.\setup-windows.ps1 -Dev
```

**Metodo 2: Setup manuale**

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python src/main.py
```

### macOS

```bash
# Installare Homebrew (se non present)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Installare Python
brew install python@3.10

# Setup del progetto
git clone https://github.com/DriftDeV/Python-DriftCoordBot.git
cd Python-DriftCoordBot

make install-dev  # Per sviluppo
make install      # Per hosting
make run          # Eseguire il bot
```

### Linux (Debian/Ubuntu)

```bash
# Installare Python
sudo apt update
sudo apt install python3.10 python3.10-venv

# Setup del progetto
git clone https://github.com/DriftDeV/Python-DriftCoordBot.git
cd Python-DriftCoordBot
make install-dev  # Per sviluppo
make install      # Per hosting
make run          # Eseguire il bot
```

### Linux (Fedora)

```bash
# Installare Python
sudo dnf install python3.10 python3.10-devel

# Setup del progetto
git clone https://github.com/DriftDeV/Python-DriftCoordBot.git
cd Python-DriftCoordBot
make install-dev  # Per sviluppo
make install      # Per hosting
make run          # Eseguire il bot
```

### Linux (Arch)

```bash
# Installare Python
sudo pacman -S python

# Setup del progetto
git clone https://github.com/DriftDeV/Python-DriftCoordBot.git
cd Python-DriftCoordBot
make install-dev  # Per sviluppo
make install      # Per hosting
make run          # Eseguire il bot
```

## 🛠️ Development Workflow

### Comandi di Qualità del Codice

```bash
# Formattare il codice con Black e isort
make format

# Controllare il codice con linting
make lint

# Type checking con mypy
make type-check

# Pre-commit checks (format + lint + type-check)
make pre-commit
```

### Testing

```bash
# Eseguire i test unitari
make test

# Eseguire i test con report di copertura
make test
```

### Comandi Make Disponibili

```bash
make help              # Mostra tutti i comandi disponibili
make venv              # Crea l'ambiente virtuale
make install           # Installa dipendenze di produzione
make install-dev       # Installa con dipendenze di sviluppo
make clean             # Rimuove venv e cache
make run               # Esegui il bot
make lint              # Controlli di linting
make format            # Formatta il codice con Black
make type-check        # Type checking con mypy
make test              # Esegui i test unitari
make pre-commit        # Format + lint + type-check
make update            # Aggiorna tutte le dipendenze
```

## 📁 Struttura del Progetto

```
Python-DriftCoordBot/
├── fedora-deps.sh                          # Script di dipendenze per Fedora
├── Makefile                                # Automazione della build
├── pyproject.toml                          # Configurazione del progetto
├── README.md                               # Questo file
├── requirements.txt                        # Dipendenze del progetto
├── setup-windows.ps1                       # Script di setup per Windows
├── SETUP.md                                # Guida di setup dettagliata
│
├── src/                                    # Codice sorgente principale
│   ├── main.py                            # Entry point del bot
│   ├── test.py                            # Test di base
│   └── cogs/                              # Moduli estensibili del bot
│       ├── __init__.py                    # Inizializzazione dei Cogs
│       ├── ai_cover_cog.py                # Cog per AI Cover musicali
│       ├── Create_speaker.py              # Cog per creazione speaker
│       ├── ping.py                        # Cog per comando ping
│       ├── soundboards.py                 # Cog per soundboard
│       ├── speakers_alias.json            # Alias degli speaker
│       ├── TTS_COG.py                     # Cog principale di TTS
│       ├── data/                          # Dati per server
│       │   ├── index.json
│       │   └── [server-ids]/
│       │       ├── soundboard/
│       │       ├── soundboards/
│       │       └── speakers/
│       ├── RVC/                           # Voice Conversion models
│       │   ├── __init__.py
│       │   ├── index.json
│       │   ├── rvc.py
│       │   ├── models/                    # Modelli RVC
│       │   │   ├── arianagrande/
│       │   │   ├── billieeilishep/
│       │   │   ├── Geolier/
│       │   │   └── ... (altri modelli)
│       │   └── [server-ids]/
│       │       └── temp/
│       └── tests/                         # Test dei Cogs
│
├── HuggingFace/                            # Modelli da Hugging Face
├── separated/                              # Audio separati
│   └── htdemucs/
└── discordbot.egg-info/                    # Metadata del pacchetto
```

## ⚙️ Configurazione

### Environment Variables

Create a `.env` file in the project root:

```env
DISCORD_TOKEN=your_discord_bot_token
```

## Discord Bot Setup
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to "Bot" section and create a bot
4. Copy the token and add it to `.env`
5. Enable "Message Content Intent" under Privileged Gateway Intents
6. Generate OAuth2 URL with scopes: `bot`, `applications.commands`
7. Give the bot appropriate permissions in your test server

## Dependencies

### Core
- **discord.py** - Discord API wrapper
- **TTS** - Coqui Text-to-Speech
- **torch/torchaudio** - ML framework for TTS
- **transformers** - HuggingFace transformers for TTS
- **python-dotenv** - Environment variable management

### Development
- **pytest** - Testing framework
- **black** - Code formatter
- **pylint** - Code linter
- **mypy** - Type checker
- **isort** - Import sorter
- **flake8** - Code quality checker

## Troubleshooting

### FFmpeg not found
```bash
# Windows (with Chocolatey)
choco install ffmpeg

# macOS (with Homebrew)
brew install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt-get install ffmpeg
```

### Python version mismatch
Ensure you're using Python 3.11+:
```bash
python --version
```

### Virtual environment not activating
```bash
# Windows
.\venv\Scripts\Activate.ps1

# Linux/macOS
source venv/bin/activate
```

### Module import errors
Clear Python cache and reinstall:
```bash
make clean
make install-dev
```

## Contributing

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Make your changes
3. Run quality checks: `make pre-commit`
4. Commit: `git commit -m "Add my feature"`
5. Push: `git push origin feature/my-feature`
6. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Author

**drift** - DriftDeV

## Support

For issues and questions, please open an [issue on GitHub](https://github.com/DriftDeV/Python-DriftCoordBot/issues).

## 📝 TODO List

### Configurazione e Setup
- [ ] Configurare il bot con il token di Discord
- [ ] Aggiungere file `.env` con variabili di ambiente
- [ ] Testare setup su Windows, macOS e Linux

### Bug Fixes
- [ ] Risolvere l'errore di sintassi in `TTS_COG.py` alla linea 169
- [ ] Testare la compatibilità con le ultime versioni di discord.py

### Features
- [ ] Aggiungere nuove funzionalità al bot
- [ ] Migliorare la clonazione vocale
- [ ] Aggiungere supporto per più lingue
- [ ] Implementare nuovi modelli RVC

### Testing e Qualità
- [ ] Testare il bot in un server Discord reale
- [ ] Aggiungere test unitari completi
- [ ] Aumentare la copertura dei test
- [ ] Setup di CI/CD con GitHub Actions

### Documentazione
- [ ] Documentare ulteriormente le funzionalità del bot
- [ ] Creare tutorial video per l'uso
- [ ] Aggiungere esempi di utilizzo per ogni comando
- [ ] Documentare l'API dei Cogs

### Release
- [ ] Rilasciare una versione stabile (v1.0.0)
- [ ] Creare changelog completo
- [ ] Pubblicare il bot su Discord Bot listing sites

---

**Last Updated:** December 2025

