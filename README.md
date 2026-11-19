# DriftBot

Bot Discord con musica da YouTube, generazione di musica con l'AI, TTS con voci clonate, cover AI, soundboard e una
dashboard web per gestire tutto dal browser.

| Funzione | Comando |
|---|---|
| Musica da URL o nome (YouTube e siti supportati da `yt-dlp`) | `/play` |
| Generare un brano con l'AI (ACE-Step, HeartMuLa) | `/ai-music` |
| Cover AI di una canzone con un modello RVC | `/ai-cover` |
| TTS con voce clonata | `/tts-ai`, `/new-speaker` |
| TTS locale con la voce di Giorgio, per chi non può parlare | `/tts` |
| Soundboard | `/soundboard` |
| Controlli globali di riproduzione | `/skip` `/pause` `/resume` `/stop` `/setvolume` |

**Indice:** [Cosa serve](#cosa-serve) · [1. Crea il bot su Discord](#1-crea-il-bot-su-discord) ·
[2. Installa e avvia](#2-installa-e-avvia) · [3. Configurazione](#3-configurazione-env) · [4. Comandi](#4-comandi) ·
[5. GPU](#5-gpu-nvidia-amd-o-cpu) · [6. Dashboard](#6-dashboard) · [7. Dati e backup](#7-dati-e-backup) ·
[8. Problemi comuni](#8-problemi-comuni) · [9. Sviluppo](#9-sviluppo)

---

## Cosa serve

- Un **token di bot Discord** (passo 1).
- **Docker** (consigliato, soprattutto per un VPS) **oppure** Python 3.10, FFmpeg e `make` per l'installazione locale.
- Una **GPU** è facoltativa ma consigliata: `/tts-ai`, `/ai-cover` e `/ai-music` su CPU funzionano ma sono molto lenti.
  Il bot supporta NVIDIA (CUDA), AMD (ROCm, solo Linux) e CPU. Un VPS senza GPU va bene per `/play`, `/tts`, `/soundboard`
  e la dashboard.

---

## 1. Crea il bot su Discord

1. Nel [Discord Developer Portal](https://discord.com/developers/applications) crea una **New Application**, poi vai in **Bot**
   e copia il token: ti servirà come `DISCORD_TOKEN`.
2. Sempre in **Bot → Privileged Gateway Intents** attiva **Message Content Intent** e **Server Members Intent**
   (il secondo serve a `/new-speaker` per vedere chi è in vocale). Il bot li richiede all'avvio: se nel portale non sono
   attivi, parte con un errore che lo ricorda.
3. In **OAuth2 → URL Generator** scegli gli scope `bot` e `applications.commands` e questi permessi: *View Channels*,
   *Send Messages*, *Embed Links*, *Attach Files* (`/ai-music` allega il brano solo se non può suonarlo in vocale),
   *Connect* e *Speak*.
4. Apri l'URL generato per aggiungere il bot al tuo server. I comandi slash si sincronizzano all'avvio.

---

## 2. Installa e avvia

Scegli **una** strada: **A) Docker** (un comando, ideale per VPS e produzione) o **B) installazione locale**.

### A. Docker (consigliato)

**1. Installa Docker** con il plugin Compose. Su Ubuntu/Debian: `curl -fsSL https://get.docker.com | sh`
(poi `sudo usermod -aG docker $USER` e riaccedi). Altre piattaforme: [docs.docker.com/engine/install](https://docs.docker.com/engine/install/).

**2. Scarica il progetto e crea il file `.env`:**
```bash
git clone https://github.com/DriftDeV/DriftBot.git
cd DriftBot
cat > .env <<'EOF'
DISCORD_TOKEN=il_tuo_token
EOF
```
Il `.env` resta sul tuo computer: non finisce mai dentro l'immagine (è escluso da `.dockerignore`).
Le altre impostazioni sono nella sezione [Configurazione](#3-configurazione-env).

**3. Costruisci e avvia:**
```bash
docker compose up -d --build
docker compose logs -f          # deve comparire "Loggato come ..." e "Sincronizzati N comandi slash"
```
La prima build scarica PyTorch e le librerie audio e richiede diversi minuti. Il bot riparte da solo dopo un riavvio
del server (`restart: unless-stopped`).

**Operazioni comuni:**

| Cosa | Comando |
|---|---|
| Fermare il bot (i dati restano) | `docker compose down` |
| Riavviarlo | `docker compose restart` |
| Aggiornare il codice | `git pull && docker compose up -d --build` |
| Vedere gli ultimi log | `docker compose logs --tail 100 bot` |
| Entrare nel container | `docker compose exec bot bash` |

**GPU in Docker.** L'immagine di default usa PyTorch per **CPU**. Per la GPU cambia l'indice dei wheel alla build
(`TORCH_INDEX`, anche nel `.env`) e decommenta il blocco giusto in `docker-compose.yml`:
```bash
TORCH_INDEX=https://download.pytorch.org/whl/cu124 docker compose up -d --build        # NVIDIA: serve nvidia-container-toolkit sull'host
TORCH_INDEX=https://download.pytorch.org/whl/rocm6.2.4 docker compose up -d --build    # AMD (Linux): /dev/kfd, /dev/dri e i gruppi video/render
```
Su AMD con schede consumer aggiungi anche `HSA_OVERRIDE_GFX_VERSION` nel `.env` (vedi [GPU](#5-gpu-nvidia-amd-o-cpu)).
Verifica dentro il container: `docker compose exec bot python src/test.py`.

**Dove stanno i dati.** Tre volumi con nome: `driftbot-data` (database, suoni, voci), `driftbot-rvc` (modelli RVC) e
`driftbot-cache` (modelli scaricati da Hugging Face). Sopravvivono a `docker compose down` e agli aggiornamenti; vengono
cancellati solo da `docker compose down -v`. Backup del database e dei file:
```bash
docker compose stop bot
docker run --rm -v driftbot_driftbot-data:/data -v "$PWD":/backup docker.io/library/alpine tar czf /backup/driftbot-data.tgz -C /data .
docker compose start bot
```
(il prefisso `driftbot_` è il nome della cartella del progetto: controlla con `docker volume ls`).

**Dashboard su un VPS.** Metti `DASHBOARD_PASSWORD` nel `.env` e riavvia: la dashboard compare su `127.0.0.1:8080` **del
server**, mai direttamente su Internet. Due modi per usarla:

- tunnel SSH, senza esporre nulla: `ssh -L 8080:127.0.0.1:8080 utente@server`, poi apri `http://127.0.0.1:8080`;
- reverse proxy HTTPS (consigliato in produzione), ad esempio con [Caddy](https://caddyserver.com/), che prende da solo il certificato:
  ```
  bot.tuodominio.it {
      reverse_proxy 127.0.0.1:8080
  }
  ```
  e nel `.env` imposta `DASHBOARD_COOKIE_SECURE=1` e `DASHBOARD_TRUST_PROXY=1` (vedi [Dashboard](#6-dashboard)).

**Cosa cambia nel container:**
- `/ai-music` offre solo **ACE-Step veloce**, e solo se imposti `ACESTEP_API_URL` nel `.env` verso un ACE-Step che gira
  altrove (sull'host: `http://host.docker.internal:8001`). HeartMuLa e il livello `accurata` non sono disponibili:
  il bot li avvia da cartelle accanto al repository, che nel container non ci sono. Dettagli in [docs/ai-music.md](docs/ai-music.md).
- `/tts` (voce di Giorgio) nel container risponde che la voce non è installata: il container ha solo `espeak-ng`.
  Il resto del bot funziona normalmente.
- Non esporre mai l'API di ACE-Step o di Ollama su Internet senza protezione.

### B. Installazione locale

**1. Installa i programmi di base** (Python 3.10, FFmpeg, Git, compilatori):

- Ubuntu / Debian: `sudo apt update && sudo apt install -y python3.10 python3.10-venv ffmpeg git build-essential`
- Fedora: `sudo dnf install -y python3.10 python3.10-devel ffmpeg git gcc gcc-c++ make espeak-ng` (oppure `./fedora-deps.sh`)
- macOS: `brew install python@3.10 ffmpeg git`
- Windows: PowerShell **come amministratore**, poi
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  .\setup-windows.ps1              # installa Chocolatey, Visual C++ build tools, Python 3.10, FFmpeg, Make e Git
  .\setup-windows.ps1 -Dev         # con gli strumenti di sviluppo
  .\setup-windows.ps1 -Gpu cpu     # forza la CPU (o -Gpu cuda; ROCm è solo Linux)
  ```
- Per `/play` serve anche **Node.js 20 o più recente** (yt-dlp lo usa per le sfide JavaScript di YouTube).

**2. Scarica il progetto e installa** (il venv si crea da solo):
```bash
git clone https://github.com/DriftDeV/DriftBot.git
cd DriftBot
python3.10 -m venv venv && source venv/bin/activate
make install GPU=rocm      # oppure GPU=cuda / GPU=cpu; senza GPU=... rileva da solo
```

**3. Crea il file `.env`** nella cartella del progetto con `DISCORD_TOKEN=il_tuo_token`, poi avvia:
```bash
make run                    # oppure: python src/main.py
```

---

## 3. Configurazione (`.env`)

Il bot legge il file `.env` all'avvio. Basta `DISCORD_TOKEN`; il resto è facoltativo:

```env
DISCORD_TOKEN=il_tuo_token

# Dashboard web (spenta se manca la password)
DASHBOARD_PASSWORD=una-password-lunga-e-tua

# /ai-music: l'LLM che scrive testi e caption. Con la key usa Claude, senza usa Ollama in locale
ANTHROPIC_API_KEY=sk-ant-...
ACESTEP_API_URL=http://127.0.0.1:8001

# GPU AMD consumer (es. RX 6600 = 10.3.0, RX 7600 = 11.0.0)
HSA_OVERRIDE_GFX_VERSION=10.3.0
```

| Variabile | A cosa serve |
|---|---|
| `DISCORD_TOKEN` | **Obbligatoria.** Il token del bot |
| `DASHBOARD_PASSWORD` | Attiva la dashboard ([sezione 6](#6-dashboard) per le altre opzioni) |
| `ANTHROPIC_API_KEY` | Se presente `/ai-music` usa Claude per testi e caption; **è a pagamento** e il prompt esce dal tuo computer |
| `ACESTEP_API_URL` | Dove trovare ACE-Step per `/ai-music` (default `http://127.0.0.1:8001`) |
| `DRIFTBOT_DEVICE` | Forza il dispositivo, es. `cuda:1` per la seconda GPU, o `cpu` |
| `HSA_OVERRIDE_GFX_VERSION` | Solo AMD consumer non ufficialmente supportate |
| `AI_COVER_MAX_SECONDS` | Durata massima di un video per `/ai-cover` (default `900`) |
| `AI_COVER_DEMUCS_TIMEOUT` | Timeout della separazione voce in secondi (default `1800`) |
| `DRIFTBOT_DB` | Percorso del database (default `src/cogs/data/driftbot.sqlite3`) |

Tutte le variabili di `/ai-music` (modelli, porte, timeout, Claude/Ollama) sono nella tabella di
[docs/ai-music.md](docs/ai-music.md). Il `.env` contiene segreti: è già nel `.gitignore`, non committarlo.

---

## 4. Comandi

### Musica

`/play <url o nome>` riproduce la canzone o la accoda, con coda per server (di una playlist viene accodata solo la prima
traccia). Se la coda finisce il bot esce dalla vocale dopo 2 minuti.

`/skip`, `/pause`, `/resume`, `/stop` e `/setvolume <0-100>` sono **globali**: funzionano su qualunque audio lungo,
cioè `/play`, `/ai-cover` e `/ai-music`, e vanno usati da chi è nel canale vocale del bot. `/stop` ferma tutto, svuota
la coda di `/play` e le richieste di `/ai-cover` in attesa del server (quella già in elaborazione non si può annullare) ed
esce dalla vocale. Il volume è uno per server e vale anche per le tracce successive.

### Musica con l'AI: `/ai-music`

`/ai-music prompt:<descrizione> modello:<ACE-Step|HeartMuLa> [livello] [durata] [testo] [lingua] [strumentale]` genera un
brano originale e lo **riproduce nella tua vocale** (devi essere in un canale vocale).

- **`modello`** è obbligatorio. **`livello`**: `veloce` (default, GPU) o `accurata` (più lenta, su CPU, solo ACE-Step).
- **`testo`**: se lo scrivi tu, l'AI non lo riscrive: aggiunge solo caption, metadati e i tag delle sezioni, e il bot
  controlla che le parole siano identiche. Se lo ometti lo scrive un LLM (Claude o Ollama).
- **`durata`**: 10-300 secondi, default 100 (HeartMuLa: default 60, massimo 120). Oltre i 4 minuti ACE-Step perde struttura.
- Il bot avvia il modello scelto solo per quella generazione e ne tiene **uno alla volta**.

Come funziona, cosa installare, quanto è veloce e come regolarlo: **[docs/ai-music.md](docs/ai-music.md)**.

### Cover AI e TTS con voci clonate

- **`/ai-cover url:<link> model:<modello> [pitch]`**: crea una cover con un modello RVC e la riproduce. Le richieste vanno
  in coda (una alla volta). Scegli il modello dall'elenco che compare mentre scrivi. Un modello disattivato (o limitato ad
  altri server) non compare; se lo disattivi con una richiesta già in coda, l'utente riceve un avviso e la coda prosegue.
  Se la VRAM non basta per separare la voce, il passaggio ripiega da solo sulla CPU.
- **`/new-speaker`** registra la voce di una persona, **`/rename-speaker`** la rinomina, **`/tts-ai`** legge un testo con
  quella voce. Scegli sempre lo speaker dall'elenco: il bot usa l'identificativo, non il testo digitato.
- I modelli RVC e le voci si gestiscono anche dalla [dashboard](#6-dashboard).

### TTS locale con la voce di Giorgio: `/tts`

`/tts testo:<cosa dire>` fa **leggere il testo dal bot nel tuo canale vocale** con la voce italiana **Giorgio** installata
sul computer che ospita il bot ([pyttsx3](https://pypi.org/project/pyttsx3/): nessun servizio esterno, nessun costo).
È pensato per chi in quel momento non può parlare: scrive e il bot parla al suo posto.

- Il testo compare anche nel canale. Fino a 300 caratteri; menzioni, link ed emoji vengono resi leggibili.
- **A turno:** più persone insieme vanno in coda (3 messaggi per persona, 10 per server, uno ogni 3 secondi per utente).
- **Non interrompe la musica:** se il bot sta riproducendo altro, lo dice e non legge nulla. `/tts-stop` interrompe la lettura.
- **Serve una voce di sistema con «Giorgio» nel nome** (SAPI5 su Windows, espeak-ng su Linux, NSSpeech su macOS). Se non c'è,
  `/tts` risponde "La voce Giorgio non è installata su questo PC" e nel log compare l'elenco delle voci disponibili.

### Soundboard e altro

- **`/soundboard`** riproduce un suono dalla lista del server (i suoni globali hanno il 🌐 davanti). Si gestisce dalla dashboard.
- **`/ping`** controlla che il bot risponda; **`/leave`** lo fa uscire dalla vocale.

---

## 5. GPU: NVIDIA, AMD o CPU

Nel codice il device si chiama sempre `cuda`, sia su NVIDIA sia su AMD: lo decide la build di PyTorch installata.
**PyTorch va installato dalla build giusta prima delle altre dipendenze** (`make install` lo fa da solo):
```bash
make install GPU=cuda    # NVIDIA
make install GPU=rocm    # AMD (solo Linux)
make install GPU=cpu     # senza GPU
make install             # rilevamento automatico (nvidia-smi = cuda, /dev/kfd = rocm, altrimenti cpu)
```
Se la build non corrisponde alla tua GPU il bot parte lo stesso ma **gira in silenzio su CPU**. Verifica con `make test-py`:
mostra backend (CUDA/ROCm/CPU), nome della GPU e fa un test su tensore.

**Solo AMD (ROCm):**
- L'utente deve stare nei gruppi `render` e `video`: `sudo usermod -aG render,video $USER`, poi riaccedi.
- Schede consumer non ufficialmente supportate: imposta `HSA_OVERRIDE_GFX_VERSION` (RDNA2 es. RX 6600: `10.3.0`; RDNA3
  es. RX 7600: `11.0.0`) nel `.env` o nella shell.
- L'indice dei wheel è `rocm6.2.4` (quello di torch 2.6.0). Per un altro: `make install-torch GPU=rocm TORCH_INDEX=https://download.pytorch.org/whl/<indice>`.

**Con 8 GB di VRAM** i modelli non stanno tutti insieme: il bot li alterna da solo (TTS e `/ai-music` si danno il turno sulla
GPU; ogni cambio costa qualche decina di secondi alla richiesta successiva dell'altro). `/ai-cover` usa la GPU e non è
coordinato: non usarlo insieme a `/ai-music`.

---

## 6. Dashboard

Soundboard, voci clonate e modelli RVC si gestiscono da una pagina web: niente file JSON da modificare a mano. Tutto ciò che
il bot "ricorda" sta in un database SQLite.

**Attivarla:** metti una password (almeno 8 caratteri) nel `.env` e avvia il bot:
```env
DASHBOARD_PASSWORD=una-password-lunga-e-tua
```
Nel terminale compare `🖥️  Dashboard: http://127.0.0.1:8080`: aprila nel browser e accedi. **Senza password la dashboard
resta spenta** (il bot funziona uguale).

| Variabile (`.env`) | Default | Significato |
|---|---|---|
| `DASHBOARD_PASSWORD` | — | Password di accesso (obbligatoria per attivarla) |
| `DASHBOARD_NO_PASSWORD` | `0` | `1` = nessun login, solo con `DASHBOARD_HOST` locale |
| `DASHBOARD_PORT` | `8080` | Porta |
| `DASHBOARD_HOST` | `127.0.0.1` | Indirizzo: di default solo questo computer. `0.0.0.0` = raggiungibile dalla rete (vedi sotto) |
| `DASHBOARD_IN_BOT` | `1` | `0` = non avviarla dentro il bot (usa `make dashboard`) |
| `DASHBOARD_COOKIE_SECURE` | `0` | `1` se la dashboard è dietro HTTPS |
| `DASHBOARD_TRUST_PROXY` | `0` | `1` solo dietro un tuo reverse proxy: usa `X-Forwarded-For` per limitare i tentativi di accesso |
| `DASHBOARD_MAX_SOUND_MB` | `8` | Dimensione massima di un suono caricato |
| `DASHBOARD_MAX_VOICE_MB` | `50` | Dimensione massima del campione di una voce |
| `DASHBOARD_MAX_RVC_MB` | `1024` | Dimensione massima di un modello RVC |

**Cosa puoi fare:** *Panoramica* (stato del bot e del database) · *Soundboard* (aggiungi, ascolta, rinomina, sposta, elimina;
ogni suono è di un server **oppure globale** 🌐) · *Voci clonate* (ascolta, rinomina, elimina, carica un campione) ·
*Modelli RVC* (carica uno `.zip` con `.pth` e `.index` o un singolo `.pth`; attiva o disattiva; scegli se è disponibile in
tutti i server o solo in alcuni; «Cerca nuovi modelli» registra le cartelle copiate a mano in `src/cogs/RVC/models/`) ·
*Server* · *Registro* (chi ha cambiato cosa e quando).

**Sicurezza.** La dashboard può caricare ed eliminare file, quindi è protetta come un pannello di amministrazione:
password obbligatoria, in ascolto solo su `127.0.0.1`, cookie `HttpOnly` + `SameSite=Strict`, token CSRF su ogni modifica,
blocco dopo 5 password sbagliate, controllo del formato audio dal contenuto, nomi dei file generati dal server e
intestazioni di sicurezza (CSP, `nosniff`). **Se la apri alla rete** (`DASHBOARD_HOST=0.0.0.0`) mettila dietro un reverse
proxy **HTTPS** e imposta `DASHBOARD_COOKIE_SECURE=1`: senza HTTPS la password viaggerebbe in chiaro (il bot lo segnala nei log).
Per usarla da un altro computer senza esporla: `ssh -L 8080:127.0.0.1:8080 utente@server`.

**In un processo separato** (per tenerla attiva a bot fermo): `DASHBOARD_IN_BOT=0` nel `.env` e `make dashboard`. I due
processi usano lo stesso database senza problemi.

---

## 7. Dati e backup

- **Database:** `src/cogs/data/driftbot.sqlite3` (suoni, voci, modelli, server, registro). Per il backup copia questo file con
  il bot fermo, oppure insieme ai file `-wal` e `-shm`. In Docker è nel volume `driftbot-data` (vedi sopra).
- **File dei server:** `src/cogs/data/<id-server>/soundboard/` e `.../speakers/`; i suoni globali in
  `src/cogs/data/global/soundboard/`. I nomi dei file li genera il bot: gestisci tutto da dashboard o comandi, non rinominarli a mano.
- **Modelli RVC:** `src/cogs/RVC/models/<cartella>/`.

**Scritture contemporanee.** SQLite accetta una sola scrittura alla volta, quindi ogni modifica passa da una coda di
scrittura (un solo thread, una transazione per gruppo) mentre le letture vanno in parallelo grazie alla modalità WAL. Se
la dashboard gira in un altro processo, SQLite arbitra i due (attesa fino a 10 secondi, con nuovi tentativi). Se due persone
creano nello stesso momento un suono con lo stesso nome ne vince uno solo, l'altro riceve un messaggio chiaro e non resta
nessun file orfano.

**Se hai vecchi file JSON.** Al primo avvio il bot importa da solo `data/<server>/soundboard/index.json`,
`data/<server>/speakers/index.json` (con `alias.json`) e `RVC/index.json` nel database, poi li rinomina in
`*.json.migrated` (non li cancella). Le voci che puntano a file inesistenti vengono saltate e segnalate nei log.

---

## 8. Problemi comuni

| Sintomo | Cosa fare |
|---|---|
| `DISCORD_TOKEN mancante` | Crea il `.env` con `DISCORD_TOKEN=...` (in Docker: accanto a `docker-compose.yml`) |
| `Intent privilegiato non abilitato` | Nel Developer Portal, **Bot → Privileged Gateway Intents**, attiva *Message Content Intent* e *Server Members Intent* |
| `Token Discord non valido` | Rigenera il token nel Developer Portal e aggiornalo nel `.env` |
| I comandi slash non compaiono | Rinvita il bot con lo scope `applications.commands` (passo 1) e aspetta il log "Sincronizzati N comandi" |
| `ffmpeg not found` | Installalo (locale: vedi sezione 2B; in Docker è già nell'immagine) |
| `Module not found` | Attiva il venv e reinstalla con `make install` |
| `pip install -e .` fallisce con `ResolutionImpossible` | Non usarlo: `rvc-python` (`requests==2.31.0`) e `yt-dlp` (`requests>=2.32.2`) sono in conflitto. `make install` installa le dipendenze in due passi con `scripts/install_deps.py` (yt-dlp per ultimo) |
| `/play` non parte su YouTube | Serve Node.js 20+ (locale); aggiorna `yt-dlp` con `make update` o ricostruendo l'immagine |
| Audio assente o muto in vocale | Controlla che `davey` sia `<0.2` (come in `pyproject.toml`): le versioni più nuove non funzionano con questo `discord.py` |
| Il bot gira ma è lentissimo | PyTorch è la build CPU: controlla con `make test-py` (o `docker compose exec bot python src/test.py`) e reinstalla per la tua GPU (sezione 5) |
| `/ai-music`: "non è installato" o "non raggiungibile" | Vedi [docs/ai-music.md](docs/ai-music.md); in Docker serve `ACESTEP_API_URL` |
| `/tts`: "La voce Giorgio non è installata" | Installa una voce di sistema con «Giorgio» nel nome (in Docker non è disponibile) |
| Docker: `permission denied` sui volumi | Con una cartella al posto di un volume, dai i permessi all'utente 1000 del container: `sudo chown -R 1000:1000 <cartella>` |

---

## 9. Sviluppo

- `make help`: elenco dei comandi.
- `make install` / `make install-dev`: installa (e crea il venv se serve); `GPU=cuda|rocm|cpu` sceglie la build di PyTorch.
- `make run` (oppure `python src/main.py`): avvia il bot. `make dashboard`: solo la dashboard, in un processo separato.
- `make test`: test con copertura (servono le dipendenze di sviluppo: `make install-dev`). I test girano senza GPU: PyTorch,
  RVC e Chatterbox sono sostituiti da moduli finti (`tests/conftest.py`).
- `make lint`, `make format`, `make type-check`, `make pre-commit`: controlli di qualità. `make update`: aggiorna le dipendenze.
- `make test-py`: verifica che PyTorch veda la GPU.
- `scripts/install_deps.py`: installa le dipendenze di `pyproject.toml` con yt-dlp per ultimo (lo usano `make install`, `make install-dev`, `make update` e il `Dockerfile`); accetta `--extra dev` e passa a pip le altre opzioni.
- Docker: `docker build -t driftbot .` costruisce l'immagine; il `Dockerfile` segue lo stesso ordine di installazione del
  `Makefile` (pip 24.0, PyTorch dall'indice scelto, poi le dipendenze). CI: `.github/workflows/tests.yml`.
- Ricerche e note di progetto (coerenza di ACE-Step, confronto dei modelli musicali open): cartella `reports/`.
