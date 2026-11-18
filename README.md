# DriftBot — Guida semplice e veloce

DriftBot è un bot Discord per Text‑to‑Speech (TTS), clonazione vocale, TTS con la voce di Giorgio per chi non può parlare, soundboard, musica e generazione di musica con l'AI.  
Questo README ti spiega come installarlo e come aggiungere modelli RVC e speaker in modo semplicissimo.

---

## Comandi musica

Il bot riproduce anche musica da URL o per nome (YouTube e tutti i siti supportati da `yt-dlp`), con coda per server.
Serve FFmpeg (già richiesto dal resto del bot).

| Comando | Descrizione |
|---|---|
| `/play <url o nome>` | Riproduce la canzone o la accoda se ne sta già suonando una |
| `/skip` | Salta alla prossima traccia in coda |
| `/pause` · `/resume` | Mette in pausa / riprende |
| `/stop` | Ferma la riproduzione, svuota la coda ed esce dalla vocale |
| `/setvolume <0-100>` | Imposta il volume |

Se la coda finisce il bot esce dalla vocale dopo 2 minuti. Di una playlist viene accodata solo la prima traccia.

---

## TTS con la voce di Giorgio (`/tts`)

`/tts testo:<cosa dire>` fa **leggere il testo dal bot nel tuo canale vocale** con la voce italiana **Giorgio** di [Amazon Polly](https://aws.amazon.com/polly/). È pensato per chi in quel momento non può parlare (si trova in un posto silenzioso, ha il microfono rotto, o non può proprio farlo): scrive e il bot parla al suo posto.

(Il TTS ad AI con le voci clonate è `/tts-ai`.)

- **Il testo compare anche nel canale**, così chi ascolta e chi scrive vedono la stessa cosa. Menzioni, link ed emoji personalizzate vengono resi leggibili (`@nome` → il nome, link → "link"). Fino a 300 caratteri.
- **A turno:** se più persone scrivono insieme il bot parla in coda, senza interrompere nessuno (max 3 messaggi in coda per persona e 10 per server; un messaggio ogni 3 secondi per utente).
- **Non interrompe la musica:** se il bot sta riproducendo altro audio (musica, AI cover...) lo dice e non legge nulla.
- `/tts-stop` interrompe la lettura e svuota la coda (solo da chi è nel canale vocale del bot).
- Esce dal canale vocale dopo un minuto di silenzio.

### Configurazione (Amazon Polly)
1. Nella console AWS crea un utente IAM con questo permesso minimo e generane una chiave di accesso:
```json
{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "polly:SynthesizeSpeech", "Resource": "*"}]}
```
2. Mettila nel file `.env`:
```env
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=eu-central-1
```
Se le credenziali mancano `/tts` risponde con un messaggio chiaro e il resto del bot funziona normalmente.

| Variabile | Default | Effetto |
|---|---|---|
| `AWS_REGION` | `eu-central-1` | Regione AWS (anche `AWS_DEFAULT_REGION`) |
| `POLLY_ENGINE` | `standard` | Motore Polly: `standard`, `neural`, `long-form` o `generative`. Se la voce non lo supporta il bot lo dice e indica questa variabile |
| `TTS_DAILY_CHARS` | `50000` | **Tetto giornaliero di caratteri** (0 = nessun tetto). Si azzera a mezzanotte UTC e al riavvio |

> ℹ️ **Polly è a pagamento (a carattere) e il testo viene inviato ad AWS.** Per contenere la spesa il bot ha il tetto giornaliero qui sopra, i limiti per utente, e una **cache** delle frasi già sintetizzate: ripetere "sì", "no", "ciao" non costa nulla ed è istantaneo. Il testo viene inviato come testo semplice, mai come SSML. Controlla i prezzi correnti di Polly e valuta un budget in AWS Budgets.

---

## Generare musica con l'AI (ACE-Step)

`/ace-step prompt:<descrizione> [durata] [testo] [lingua] [strumentale]` genera un brano originale con [ACE-Step 1.5](https://github.com/ACE-Step/ACE-Step-1.5) e lo allega alla risposta.

| Opzione | Descrizione |
|---|---|
| `prompt` | Genere, strumenti, mood. Es. `ballata malinconica sul mare, chitarra` (3-500 caratteri) |
| `durata` | Secondi, da 10 a `ACESTEP_MAX_SECONDS`. **Se omessa si usa il massimo (180)** |
| `testo` | Testo con sezioni `[verse]`, `[chorus]`... **Se omesso lo scrive un LLM** (Claude o Ollama) a partire dal prompt |
| `lingua` | Lingua del testo: italiano (default), English, Español, Français, Deutsch, Português |
| `strumentale` | Solo musica, senza testo (e senza passare dall'LLM) |

### La catena (pensata per GPU da 8 GB)
Su 8 GB l'LLM e il modello musicale non entrano insieme in VRAM, quindi il bot li usa **uno dopo l'altro**:

1. **Un LLM scrive il testo** a partire dal prompt (solo se non hai indicato `testo` e non hai scelto `strumentale`). È **Claude** se nel `.env` c'è `ANTHROPIC_API_KEY`, altrimenti un **LLM locale con Ollama**.
2. **Solo con Ollama: l'LLM viene scaricato dalla VRAM.** Il bot chiede a Ollama di liberarlo (`keep_alive: 0`) e **controlla** che non risulti più in memoria prima di andare avanti. Con Claude non c'è nulla da scaricare: il modello gira sui server Anthropic.
3. **ACE-Step compone il brano** con quel testo, e il bot lo allega mostrando anche il testo.

ACE-Step lavora **un brano alla volta**: se più utenti usano il comando insieme, gli altri aspettano in coda (con un avviso). Con Claude il testo si scrive subito, anche mentre ACE-Step lavora per un altro; con Ollama anche la scrittura del testo aspetta il proprio turno, perché l'LLM locale occuperebbe la VRAM. Ogni utente può avere una sola richiesta attiva.
Se l'LLM non è disponibile (Ollama spento, key errata o credito finito, testo inutilizzabile) il brano viene generato **strumentale** e il bot lo segnala nella risposta. **Con la key presente il bot non ripiega mai in silenzio su Ollama**: sarebbe una sorpresa per la VRAM e nasconderebbe una key sbagliata.

### Cosa installare
Il bot non carica nessun modello nel proprio processo: parla con ACE-Step e con l'LLM (Claude via API, oppure Ollama) tramite rete. Così le dipendenze non entrano in conflitto con quelle di TTS/RVC e CUDA o ROCm si scelgono nell'installazione di ciascun server.

**1. ACE-Step** (istruzioni ufficiali nel repository del progetto):
```bash
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync
uv run acestep-api          # in ascolto su http://127.0.0.1:8001; i modelli si scaricano al primo avvio
```
**2. L'LLM che scrive i testi: scegli una delle due strade.**

*A. Claude (API)*: metti la key nel `.env`. Non serve GPU né un modello da scaricare.
```env
ANTHROPIC_API_KEY=sk-ant-...
```
*B. Ollama (locale, gratis)*: se nel `.env` **non** c'è la key, il bot usa questo. Funziona con NVIDIA e AMD ([ollama.com](https://ollama.com)):
```bash
ollama pull qwen2.5:7b      # ~4.7 GB, entra in 8 GB. Alternative più leggere: llama3.2:3b, gemma3:4b
```
> ℹ️ **Claude è a pagamento e i dati escono dal tuo computer.** Con la key presente il prompt (e solo quello) viene inviato ad Anthropic. Il modello predefinito è `claude-opus-5-5`; per spendere molto meno imposta `CLAUDE_MODEL=claude-haiku-5-5`. Il costo per brano dipende dalla lunghezza del testo; il limite di richieste del bot (`ACESTEP_MAX_PENDING`, una per utente) ne contiene la spesa.
> Il bot abilita di default il **fallback lato server** di Anthropic: se i classificatori di sicurezza rifiutano una richiesta, viene ripetuta su un altro modello (disattivabile con `CLAUDE_REFUSAL_FALLBACK=false`; se il tuo account non lo supporta il bot lo disattiva da solo).

Poi il bot li trova da solo. Se i server sono altrove o protetti, imposta nel `.env`:

| Variabile | Default | Effetto |
|---|---|---|
| `ACESTEP_API_URL` | `http://127.0.0.1:8001` | Indirizzo del server ACE-Step |
| `ACESTEP_API_KEY` | vuota | API key del server ACE-Step (se l'hai attivata) |
| `ACESTEP_MAX_SECONDS` | `180` | Durata massima **e predefinita** (il server accetta fino a 600) |
| `ACESTEP_TIMEOUT` | `600` | Secondi massimi di attesa per un brano |
| `ACESTEP_MAX_PENDING` | `5` | Richieste accettate insieme (in coda + in corso) |
| `ACESTEP_AUDIO_FORMAT` | `mp3` | `mp3`, `flac`, `opus`, `aac` o `wav` |
| `ACESTEP_DEFAULT_LANGUAGE` | `it` | Lingua del testo se non indicata: `it`, `en`, `es`, `fr`, `de`, `pt` |
| `LYRICS_LLM_ENABLED` | `true` | `false` = senza `testo` il brano è sempre strumentale (nessun LLM, né Claude né Ollama) |
| `ANTHROPIC_API_KEY` | vuota | **Se presente si usa Claude**; se vuota/assente si usa Ollama |
| `CLAUDE_MODEL` | `claude-opus-5-5` | Modello Claude (es. `claude-haiku-5-5` per spendere molto meno) |
| `CLAUDE_EFFORT` | `low` | Quanto ragiona il modello: `low`, `medium`, `high`, `xhigh`, `max`. Vuoto = non inviarlo (serve con modelli più vecchi che non lo supportano) |
| `CLAUDE_TIMEOUT` | `120` | Secondi massimi per richiesta a Claude |
| `CLAUDE_REFUSAL_FALLBACK` | `true` | Fallback lato server sui rifiuti di sicurezza |
| `ANTHROPIC_BASE_URL` | vuota | Facoltativo: proxy o gateway verso l'API |
| `LYRICS_LLM_URL` | `http://127.0.0.1:11434` | Indirizzo di Ollama (solo senza key) |
| `LYRICS_LLM_MODEL` | `qwen2.5:7b` | Modello Ollama (meglio non usare modelli "thinking") |
| `LYRICS_LLM_TIMEOUT` | `180` | Ollama: secondi massimi per caricare il modello e scrivere il testo |

### Consigli per 8 GB
- **Con Claude** la VRAM è tutta per ACE-Step: è la configurazione più semplice per schede piccole.
- **ACE-Step:** il suo profilo per 8-12 GB tiene i modelli in RAM quando non servono (offload su CPU), ed è quello che permette all'LLM di usare la GPU mentre ACE-Step è fermo. Controlla con `nvidia-smi` (o `rocm-smi`) a server inattivo che la VRAM occupata sia poca; se non lo è, prova ad avviarlo con `MAX_CUDA_VRAM=8`.
- ⚠️ **Il modello TTS ad AI (`/tts-ai`) resta caricato in VRAM** per tutto il tempo in cui il bot è acceso, e AI cover usa la GPU a sua volta. Su una sola scheda da 8 GB non c'è spazio per tutto: usa una seconda GPU o un'altra macchina per ACE-Step/Ollama (`ACESTEP_API_URL`, `LYRICS_LLM_URL`; per scegliere la GPU `CUDA_VISIBLE_DEVICES=1` su NVIDIA, `HIP_VISIBLE_DEVICES=1` su AMD), oppure disattiva il cog TTS.
- Il supporto AMD ROCm di ACE-Step e di Ollama è dichiarato dai rispettivi progetti: controlla i requisiti nella loro documentazione.

Se un server non è raggiungibile, `/ace-step` risponde con un messaggio chiaro e il resto del bot funziona normalmente.

---

## GPU: NVIDIA, AMD (ROCm) o CPU

Il bot funziona su **NVIDIA (CUDA)**, **AMD (ROCm, solo Linux)** e CPU. Il backend viene rilevato da PyTorch:
nel codice il device si chiama sempre `cuda`, sia su NVIDIA che su AMD.

Installa PyTorch **dalla build giusta** (da fare prima delle altre dipendenze: `make install` lo fa da solo):
```bash
make install GPU=cuda    # NVIDIA
make install GPU=rocm    # AMD
make install GPU=cpu     # senza GPU
make install             # rilevamento automatico (nvidia-smi = cuda, /dev/kfd = rocm, altrimenti cpu)
```
Se la build di PyTorch non corrisponde alla tua GPU, il bot parte lo stesso ma gira su CPU.
Verifica con `make test-py`: mostra backend (CUDA/ROCm/CPU), nome della GPU e fa un test su tensore.

**Solo per AMD (ROCm):**
- L'utente deve stare nei gruppi `render` e `video` (`sudo usermod -aG render,video $USER`, poi riaccedi).
- GPU consumer non ufficialmente supportate: imposta `HSA_OVERRIDE_GFX_VERSION` (RDNA2 es. RX 6600: `10.3.0`; RDNA3 es. RX 7600: `11.0.0`) nel file `.env` o nella shell.
- L'indice dei wheel è `rocm6.2.4` (quello di torch 2.6.0). Per un altro: `make install-torch GPU=rocm TORCH_INDEX=https://download.pytorch.org/whl/<indice>`.

**Variabili opzionali** (nel file `.env`):

| Variabile | Effetto |
|---|---|
| `DRIFTBOT_DEVICE` | Forza il dispositivo, es. `cuda:1` per la seconda GPU, o `cpu` |
| `AI_COVER_MAX_SECONDS` | Durata massima di un video per `/ai-cover` (default `900`) |
| `AI_COVER_DEMUCS_TIMEOUT` | Timeout della separazione voce in secondi (default `1800`) |

Se la VRAM non basta per separare la voce, `/ai-cover` ripiega automaticamente sulla CPU per quel passaggio.

---

## Creare il bot su Discord

1. Nel [Discord Developer Portal](https://discord.com/developers/applications) crea una **New Application**, poi vai in **Bot** e copia il token nel file `.env` come `DISCORD_TOKEN`.
2. Sempre in **Bot → Privileged Gateway Intents** attiva **Message Content Intent**: il bot lo richiede all'avvio e, se non è attivo anche nel portale, parte con un errore che lo ricorda.
3. In **OAuth2 → URL Generator** scegli gli scope `bot` e `applications.commands` e questi permessi: *View Channels*, *Send Messages*, *Embed Links*, *Attach Files* (serve a `/ace-step` per allegare il brano), *Connect* e *Speak* (voce).
4. Apri l'URL generato per aggiungere il bot al tuo server. I comandi slash vengono sincronizzati all'avvio.

---

## In 3 passi (super semplice)
1. Scarica il progetto:
```bash
git clone https://github.com/DriftDeV/DriftBot.git
cd DriftBot
```
2. Crea l'ambiente Python e installa dipendenze:
- Linux / macOS (scegli la GPU, vedi sezione sopra):
```bash
python3.10 -m venv venv
source venv/bin/activate
make install GPU=rocm   # oppure GPU=cuda / GPU=cpu / niente per il rilevamento automatico
```
- Windows (PowerShell **come amministratore**):
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\setup-windows.ps1              # installa Chocolatey, Visual C++ build tools, Python 3.10, FFmpeg, Make e Git
.\setup-windows.ps1 -Dev         # con gli strumenti di sviluppo
.\setup-windows.ps1 -Gpu cpu     # forza la CPU (o -Gpu cuda; ROCm è solo Linux)
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
src/cogs/RVC/models/
```
2. Per ogni modello crea una cartella che contiene i file del modello (es. pesi, config). Esempio:
```
src/cogs/RVC/models/arianagrande/
src/cogs/RVC/models/billieeilishep/
```
3. Apri (o crea) il file `src/cogs/RVC/index.json` e mappa i nomi dei modelli così:
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
- Assicurati che i nomi delle cartelle dei modelli corrispondano a quelli in `src/cogs/RVC/index.json`.
- Se aggiungi o modifichi file JSON, riavvia il bot perché rilegga i dati.
- FFmpeg è richiesto per il lavoro con audio: se il bot dà errore "ffmpeg not found", installalo come indicato sopra.

---

## Risoluzione rapida problemi
- "Module not found" → attiva il venv e reinstalla: `make install` (oppure `pip install -e .`)
- "ffmpeg not found" → installa ffmpeg (vedi sopra)
- Controlla la versione Python: `python --version` (consigliato 3.10+)

---

## Comandi utili per sviluppatori
- `make help`: elenco dei comandi
- `make install` / `make install-dev`: installa (e crea il venv se serve); `GPU=cuda|rocm|cpu` sceglie la build di PyTorch
- `make run` (oppure `python src/main.py`): avvia il bot
- `make test`: esegue i test con la copertura (servono le dipendenze di sviluppo: `make install-dev`)
- `make lint`, `make format`, `make type-check`, `make pre-commit`: controlli di qualità del codice
- `make test-py`: verifica che PyTorch veda la GPU
- `make update`: aggiorna le dipendenze

---
