# DriftBot — Guida semplice e veloce

DriftBot è un bot Discord per Text‑to‑Speech (TTS), clonazione vocale e soundboard.  
Questo README ti spiega come installarlo e come aggiungere modelli RVC e speaker in modo semplicissimo.

---

## In 3 passi (super semplice)
1. Scarica il progetto:
```bash
git clone https://github.com/DriftDeV/DriftBot.git
cd DriftBot
```
2. Crea l'ambiente Python e installa dipendenze:
- Linux / macOS:
```bash
python3.10 -m venv venv
source venv/bin/activate
make install
```
- Windows (PowerShell):
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\setup-windows.ps1
```
3. Metti il token di Discord in un file `.env` nella cartella principale:
```env
DISCORD_TOKEN=il_tuo_token
```
Poi avvia:
```bash
make run
# oppure
python src/main.py
```

---

## Istruzioni per sistema operativo (comandi essenziali)

- Ubuntu / Debian:
```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv ffmpeg git
```

- Fedora:
```bash
sudo dnf install -y python3.10 python3.10-devel ffmpeg git
```

- macOS (con Homebrew):
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install python@3.10 ffmpeg git
```

- Windows:
  1. Installa Python 3.10 dal sito ufficiale.
  2. Apri PowerShell come amministratore e, se vuoi lo script di setup:
```powershell

```
  3. Installa ffmpeg (es. con Chocolatey: `choco install ffmpeg`) o scarica binari.

---

## Dove mettere i modelli RVC (passaggi semplici)
1. Vai nella cartella del progetto e crea la cartella dei modelli:
```
src/RVC/models/
```
2. Per ogni modello crea una cartella che contiene i file del modello (es. pesi, config). Esempio:
```
src/RVC/models/arianagrande/
src/RVC/models/billieeilishep/
```
3. Apri (o crea) il file `src/RVC/index.json` e mappa i nomi dei modelli così:
```json
{
  "nome_modello_leggibile": "nome_cartella_del_modello",
  "aria": "arianagrande",
  "billie": "billieeilishep"
}
```
- La chiave è il nome che userai nel bot, il valore è il nome della cartella dentro `models/`.

Esempio pratico:
```json
{
  "arianagrande": "arianagrande",
  "billie": "billieeilishep"
}
```

---

## Dove mettere gli speaker (per server) — struttura e file JSON
Per ogni server Discord crea una cartella con l'ID del server dentro i dati del bot. Percorso consigliato:
```
src/cogs/data/<server-id>/
```
Dentro quella cartella crea due sottocartelle:
- `speakers/` — per gli speaker personalizzati
- `soundboard/` — per i suoni della soundboard

Struttura:
```
src/cogs/data/123456789012345678/
├─ speakers/
│  ├─ index.json
│  └─ alias.json
└─ soundboard/
   └─ index.json
```

- speakers/index.json — mappa nome_speaker -> file_wav
```json
{
  "mio_speaker": "mio_speaker.wav",
  "robot": "robot.wav"
}
```

- speakers/alias.json — alias per gli speaker (opzionale)
```json
{
  "bob": "mio_speaker",
  "bobby": "mio_speaker"
}
```

- soundboard/index.json — mappa nome_suono -> file_wav
```json
{
  "applause": "applause.wav",
  "laugh": "laugh.wav"
}
```

Regole pratiche:
- Metti i file .wav dentro la stessa cartella `speakers/` o `soundboard/`.
- I nomi nei file JSON sono senza spazi e sensibili al progetto (usa underscore se vuoi).
- Se preferisci un singolo file chiamato `speaker.json` puoi usarlo con lo stesso contenuto di `index.json`, ma il bot cerca per default `index.json` e `alias.json`.

---

## Note importanti
- Assicurati che i nomi delle cartelle dei modelli corrispondano a quelli in `src/RVC/index.json`.
- Se aggiungi o modifichi file JSON, riavvia il bot perché rilegga i dati.
- FFmpeg è richiesto per il lavoro con audio: se il bot dà errore "ffmpeg not found", installalo come indicato sopra.

---

## Risoluzione rapida problemi
- "Module not found" → attiva il venv e reinstalla: `pip install -r requirements.txt`
- "ffmpeg not found" → installa ffmpeg (vedi sopra)
- Controlla la versione Python: `python --version` (consigliato 3.10+)

---

## Comandi utili per sviluppatori
- Creare venv: `make venv` (se Makefile presente)
- Installare dipendenze: `make install` o `pip install -r requirements.txt`
- Eseguire bot: `make run` o `python src/main.py`

---
