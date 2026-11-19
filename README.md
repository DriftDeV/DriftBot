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
| `/skip` | Salta l'audio in corso e passa al prossimo, se c'è |
| `/pause` · `/resume` | Mette in pausa / riprende |
| `/stop` | Ferma tutto, svuota le code ed esce dalla vocale |
| `/setvolume <0-100>` | Imposta il volume del server (vale anche per le tracce successive) |

`/skip`, `/pause`, `/resume`, `/stop` e `/setvolume` sono **globali**: funzionano su qualunque audio lungo, cioè `/play`, `/ai-cover` e `/ai-music`. Vanno usati da chi è nel canale vocale del bot. `/stop` svuota la coda di `/play` e le richieste di `/ai-cover` in attesa del server (quella già in elaborazione non si può annullare).

Se la coda finisce il bot esce dalla vocale dopo 2 minuti. Di una playlist viene accodata solo la prima traccia.

---

## TTS con la voce di Giorgio (`/tts`)

`/tts testo:<cosa dire>` fa **leggere il testo dal bot nel tuo canale vocale** con la voce italiana **Giorgio** installata sul PC che ospita il bot (sintesi locale con [pyttsx3](https://pypi.org/project/pyttsx3/): nessun servizio esterno, nessun costo). È pensato per chi in quel momento non può parlare (si trova in un posto silenzioso, ha il microfono rotto, o non può proprio farlo): scrive e il bot parla al suo posto.

(Il TTS ad AI con le voci clonate è `/tts-ai`.)

- **Il testo compare anche nel canale**, così chi ascolta e chi scrive vedono la stessa cosa. Menzioni, link ed emoji personalizzate vengono resi leggibili (`@nome` → il nome, link → "link"). Fino a 300 caratteri.
- **A turno:** se più persone scrivono insieme il bot parla in coda, senza interrompere nessuno (max 3 messaggi in coda per persona e 10 per server; un messaggio ogni 3 secondi per utente).
- **Non interrompe la musica:** se il bot sta riproducendo altro audio (musica, AI cover...) lo dice e non legge nulla.
- `/tts-stop` interrompe la lettura e svuota la coda (solo da chi è nel canale vocale del bot).
- Esce dal canale vocale dopo un minuto di silenzio.

### Configurazione (voce locale)
Serve una voce di sistema con «Giorgio» nel nome: `/tts` la cerca tra quelle installate (SAPI5 su Windows, espeak-ng su Linux, NSSpeech su macOS) e ne usa la prima. Velocità 175 parole al minuto.

- **Linux:** `sudo dnf install espeak-ng espeak-ng-devel` (già in `fedora-deps.sh`).
- **Se la voce non c'è** `/tts` risponde "La voce Giorgio non è installata su questo PC" e nel log compare l'elenco delle voci disponibili, così sai cosa installare o come rinominare. Se manca la libreria `pyttsx3` risponde con un messaggio chiaro; il resto del bot funziona normalmente.

---

## Generare musica con l'AI (`/ai-music`)

`/ai-music prompt:<descrizione> modello:<ACE-Step|HeartMuLa> [livello] [durata] [testo] [lingua] [strumentale]` genera un brano originale con il modello che scegli e lo **riproduce nella tua vocale**: devi essere in un canale vocale, il bot entra, suona il brano e esce. Se la vocale non è utilizzabile (sei uscito, il bot sta suonando altro) allega il file.

| Opzione | Descrizione |
|---|---|
| `prompt` | Genere, strumenti, mood. Es. `ballata malinconica sul mare, chitarra` (3-500 caratteri) |
| `modello` | **Obbligatorio.** `ACE-Step` ([1.5](https://github.com/ACE-Step/ACE-Step-1.5), MIT) o `HeartMuLa` ([3B](https://github.com/HeartMuLa/heartlib), Apache-2.0). Ognuno ha il suo backend, avviato dal bot solo per quella generazione |
| `livello` | `veloce` (default, GPU) o `accurata` (più lenta, su CPU: **solo ACE-Step**) |
| `durata` | Secondi, da 10 a `ACESTEP_MAX_SECONDS` (300). **Se omessa: 100.** ACE-Step dichiara stabili i brani da 2 a 4 minuti; oltre, struttura e tema tendono a perdersi |
| `testo` | Testo con sezioni `[verse]`, `[chorus]`... **Se omesso lo scrive un LLM** (Claude o Ollama) a partire dal prompt |
| `lingua` | Lingua del testo: italiano (default), English, Español, Français, Deutsch, Português |
| `strumentale` | Solo musica, senza testo (e senza passare dall'LLM) |

### Modelli e livelli
| Modello | Veloce | Accurata |
|---|---|---|
| **ACE-Step** | `acestep-v15-turbo` su GPU (1-2 minuti) | `acestep-v15-xl-turbo` (DiT da 4B) **su CPU**: non entra negli 8 GB di VRAM. Misurato su Ryzen 9 5900X: **30 s di musica in ~4 minuti**, picco **20 GB di RAM** (il bot controlla che ce ne siano 21 libere) |
| **HeartMuLa** | HeartMuLa 3B su GPU, in un venv a parte: ~4 s di attesa per ogni secondo di musica, più ~30 s fissi; **il primo brano dopo l'avvio costa 2-3 minuti in più** (caricamento). Un brano da 6 s: 55 s a caldo. Durata di default 60 s, massimo 120 s | non esiste: un solo checkpoint |

- **HeartMuLa su 8 GB funziona solo con accorgimenti**, tutti nel wrapper `src/heartmula_server.py` e tutti misurati su RX 6600:
  - **fp16 invece di bf16** (`HEARTMULA_MULA_DTYPE`, `HEARTMULA_CODEC_DTYPE`): la RDNA2 non ha istruzioni bf16 native e l'81% del tempo di un passo era un solo kernel di matmul bf16. Con fp16 il LM va **3 volte più veloce** (75 passi in 24 s invece di 71). L'audio generato col codec in fp16 ha correlazione 0,993 con quello in bf16 e nessun NaN.
  - **pesi INT8** (torchao, ~4,4 GB in VRAM): in 16 bit il modello pesa ~7,5 GB e va in OOM (`HEARTMULA_INT8=0` per disattivarlo).
  - **niente `torch.compile`** (`HEARTMULA_COMPILE=1` per attivarlo): il primo passo costava ~60 s e il modello compilato resta referenziato, quindi la VRAM non si liberava e il secondo brano falliva.
  - **LM e codec restano in RAM tra un brano e l'altro** invece di essere riletti dal disco e quantizzati ogni volta (~30 s per brano; ~7 GB di RAM nel server finché è acceso).
  - la cache KV si dimensiona sulla durata (heartlib la alloca per 650 s: oltre 5 GiB) e la guida CFG si spegne da sola se la VRAM non basta; il salvataggio usa `soundfile` perché `torchaudio` 2.9 richiede `torchcodec`.
  - Provati e **scartati**: i grafi HIP (`hipErrorStreamCaptureUnsupported` su questa scheda) e `torch._weight_int8pack_mm` (6 volte più lento del percorso di torchao). Resta mezzo tempo di passo nella conversione INT8→fp16 dei pesi: senza un kernel fuso non c'è altro da guadagnare facilmente.
  - Il picco di RAM nel caricamento è ~14 GB. INT8 e fp16 possono cambiare la qualità: **non l'ho ascoltata**.
- HeartMuLa **canta sempre** (niente `strumentale`) e dichiara inglese, cinese, giapponese, coreano e spagnolo: con altre lingue il bot avvisa che la pronuncia può essere imprecisa.
- Il bot tiene **un solo backend alla volta**: prima di avviarne uno spegne gli altri che ha avviato (VRAM e RAM non bastano per due), e spegne tutto quando serve il TTS.
- Se un modello non è installato, `/ai-music` lo dice subito (in privato) invece di fallire dopo minuti.
- **Perché questi due:** nei benchmark pubblicati ACE-Step 1.5, LeVo 2 e YuE2 sono davanti, ma LeVo 2 ha licenza non commerciale e 12-22 GB di VRAM, e YuE2 24 GB su NVIDIA. HeartMuLa è il miglior modello rimasto che entra in 8 GB ed è Apache-2.0; non è provato su AMD RDNA2 dagli autori. Nessun confronto neutrale esiste e nessuno ha misurato l'italiano: dettagli in `reports/Benchmark modelli musicali.md`.

### La catena (pensata per GPU da 8 GB)
Su 8 GB l'LLM e il modello musicale non entrano insieme in VRAM, quindi il bot li usa **uno dopo l'altro**:

1. **Un LLM prepara il brano** a partire dal prompt (non se hai scelto `strumentale`), con **una sola chiamata**: il testo (righe da 6-10 sillabe, tag `[Intro]`/`[Verse]`/`[Chorus - anthemic]`...), una **caption sonora in inglese** (genere, strumenti, voce, produzione) e **bpm, tonalità e metro** coerenti con lo stile. ACE-Step riceve questi campi al posto della frase grezza dell'utente e dei valori scelti dal suo piccolo LM. Se l'LLM non restituisce l'intestazione, il bot usa il prompt dell'utente e i metadati scelti dal server. **Se hai scritto tu il `testo`** l'LLM non lo riscrive: aggiunge solo caption, metadati e, dove mancano, i tag di sezione, e il bot controlla riga per riga che le parole siano identiche (maiuscole e spazi a parte). Se ne ha toccata anche una sola, tiene il tuo testo com'è e usa comunque caption e metadati; se l'LLM è spento o non risponde, il testo resta il tuo e la caption è il tuo prompt. Con `strumentale` non c'è LLM e la caption resta il tuo prompt: scrivilo come una descrizione sonora. È **Claude** se nel `.env` c'è `ANTHROPIC_API_KEY`, altrimenti un **LLM locale con Ollama**.
2. **Solo con Ollama: l'LLM viene scaricato dalla VRAM.** Il bot chiede a Ollama di liberarlo (`keep_alive: 0`) e **controlla** che non risulti più in memoria prima di andare avanti. Con Claude non c'è nulla da scaricare: il modello gira sui server Anthropic.
3. **ACE-Step compone il brano** con quel testo, e il bot lo riproduce nella vocale mostrando anche il testo. Se ACE-Step è spento e si trova accanto al repository del bot (o in `ACESTEP_DIR`) lo avvia da solo prima di generare.

ACE-Step lavora **un brano alla volta**: se più utenti usano il comando insieme, gli altri aspettano in coda (con un avviso). Con Claude il testo si scrive subito, anche mentre ACE-Step lavora per un altro; con Ollama anche la scrittura del testo aspetta il proprio turno, perché l'LLM locale occuperebbe la VRAM. Ogni utente può avere una sola richiesta attiva.
Se l'LLM non è disponibile (Ollama spento, key errata o credito finito, testo inutilizzabile) il brano viene generato **strumentale** e il bot lo segnala nella risposta. **Con la key presente il bot non ripiega mai in silenzio su Ollama**: sarebbe una sorpresa per la VRAM e nasconderebbe una key sbagliata.

### Cosa installare
Il bot non carica nessun modello nel proprio processo: parla con ACE-Step e con l'LLM (Claude via API, oppure Ollama) tramite rete. Così le dipendenze non entrano in conflitto con quelle di TTS/RVC e CUDA o ROCm si scelgono nell'installazione di ciascun server.

**1. ACE-Step** (istruzioni ufficiali nel repository del progetto):
```bash
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync
uv run acestep-api --init-llm --lm-model-path acestep-5Hz-lm-0.6B   # http://127.0.0.1:8001; i modelli si scaricano al primo avvio
```
Se cloni ACE-Step nella stessa cartella che contiene il repository del bot (es. `~/git/ACE-Step-1.5` accanto a `~/git/DriftBot`), **il bot lo avvia da solo** al primo `/ace-step` (log in `acestep-api.log` nella cartella di ACE-Step; si spegne quando il bot si ferma). Gli stessi parametri a mano sono nel comando sopra.

**Brani coerenti:** il bot attiva il modello LM 5Hz di ACE-Step (`--init-llm`, `thinking`): pianifica struttura e codici audio prima del modello musicale, e senza di lui il brano tende a sfilacciarsi. Temperatura LM `0.7` e 8 passi (valore del modello turbo). Senza LM (`ACESTEP_LM_MODEL=`) è più leggero in VRAM ma meno coerente. Il LM **non** riscrive il prompt (`use_cot_caption: false`): provato, altrimenti "lofi piano" diventava "folk-rock con chitarre".

**Scheda AMD (ROCm): serve un venv a parte.** Il `.venv` creato da `uv sync` ha torch CUDA (NVIDIA): su AMD ACE-Step gira in silenzio su **CPU**. Crea `venv_rocm` nella cartella di ACE-Step (se esiste, il bot lo usa al posto di `uv run`):
```bash
cd ACE-Step-1.5
uv venv venv_rocm --python 3.11
uv pip install --python venv_rocm/bin/python torch torchaudio torchvision --index-url https://download.pytorch.org/whl/rocm6.4
uv pip install --python venv_rocm/bin/python -r requirements-rocm-linux.txt "torchao==0.14.1"   # torchao nuovo non va con torch 2.9
```
`requirements-rocm-linux.txt` di ACE-Step include `pytorch_wavelets`, `PyWavelets` e `setuptools<81` (l'ho aggiunto a mano): servono al DCW, la correzione del sampler attiva sul turbo, che altrimenti viene saltata in silenzio. Provato sulla GPU in float32 e bfloat16; l'effetto sul suono non è misurato.

Il bot lancia ACE-Step con `ACESTEP_LM_BACKEND=pt`, `ACESTEP_ROCM_DTYPE=bfloat16` (il default float32 va in OOM su 8 GB) e `HSA_OVERRIDE_GFX_VERSION` preso dal tuo `.env`. Misurato su RX 6600 (8 GB): picco VRAM ~7 GB, 20 s di musica in ~34 s a modello caldo (88 s col primo caricamento). `venv_rocm` pesa ~16 GB su disco.
**1b. Livello `accurata` di ACE-Step** (facoltativo): scarica il DiT XL (**~19 GB su disco**; il bot lo usa su CPU):
```bash
cd ACE-Step-1.5
venv_rocm/bin/python -c "from acestep.model_downloader import main; main()" --model acestep-v15-xl-turbo
```
**1c. HeartMuLa** (facoltativo): venv a parte accanto al repo del bot (le sue dipendenze sono incompatibili con quelle del bot), con torch ROCm installato **prima** del resto:
```bash
git clone https://github.com/HeartMuLa/heartlib.git && cd heartlib
uv venv venv --python 3.10
uv pip install --python venv/bin/python torch torchaudio torchvision --index-url https://download.pytorch.org/whl/rocm6.4
uv pip install --python venv/bin/python -e . huggingface_hub aiohttp "setuptools<81"
venv/bin/hf download --local-dir ./ckpt HeartMuLa/HeartMuLaGen
venv/bin/hf download --local-dir ./ckpt/HeartMuLa-oss-3B HeartMuLa/HeartMuLa-oss-3B-happy-new-year
venv/bin/hf download --local-dir ./ckpt/HeartCodec-oss HeartMuLa/HeartCodec-oss-20260123
```
Il bot lo trova da solo se la cartella si chiama `heartlib*` ed è accanto al repo (o con `HEARTMULA_DIR`) e la avvia tramite `src/heartmula_server.py`, un piccolo server che parla lo stesso protocollo di ACE-Step. I pesi (~GB) stanno in `heartlib/ckpt`.

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
| `ACESTEP_DEFAULT_SECONDS` | `100` | Durata se omessa |
| `ACESTEP_MAX_SECONDS` | `300` | Durata massima (il server accetta fino a 600) |
| `ACESTEP_TIMEOUT` | `600` | Secondi massimi di attesa per un brano |
| `ACESTEP_MAX_PENDING` | `5` | Richieste accettate insieme (in coda + in corso) |
| `ACESTEP_DIR` | prima `ACE-Step*` accanto al repo | Cartella di ACE-Step da avviare in automatico se il server è spento (solo con `ACESTEP_API_URL` locale) |
| `ACESTEP_STARTUP_TIMEOUT` | `300` | Secondi massimi per l'avvio (caricamento modelli) |
| `ACESTEP_LM_MODEL` | `acestep-5Hz-lm-0.6B` | Modello LM per brani coerenti; vuoto = senza LM. Su 8 GB il server usa comunque lo 0.6B; l'1.7B ha senso da 12 GB |
| `ACESTEP_XL_MODEL` | `acestep-v15-xl-turbo` | DiT del livello `accurata` |
| `ACESTEP_ACCURATE_PORT` | `8002` | Porta del server ACE-Step `accurata` |
| `ACESTEP_ACCURATE_TIMEOUT` | `3600` | Secondi massimi di attesa per un brano `accurata` (su CPU) |
| `HEARTMULA_DIR` | prima `heartlib*` accanto al repo | Cartella di heartlib (con `venv/` e `ckpt/`) |
| `HEARTMULA_PORT` | `8003` | Porta del wrapper HeartMuLa |
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
- **TTS e ACE-Step si danno il turno sulla GPU.** Il modello di `/tts-ai` (~3,4 GB) e ACE-Step (~7 GB) insieme non entrano in 8 GB (era l'errore "La generazione è fallita": OOM). Quando parte `/ace-step` il bot scarica il modello TTS dalla VRAM; quando serve `/tts-ai` il bot spegne ACE-Step (se l'ha avviato lui) e ricarica il TTS. Ogni cambio costa qualche decina di secondi alla richiesta successiva dell'altro. AI cover usa la GPU a sua volta e non è coordinato: non usarlo insieme. Con una seconda GPU o un'altra macchina per ACE-Step (`ACESTEP_API_URL`; `HIP_VISIBLE_DEVICES=1` su AMD) i due modelli restano sempre caricati.
- Il supporto AMD ROCm di ACE-Step e di Ollama è dichiarato dai rispettivi progetti: controlla i requisiti nella loro documentazione.

Se un server non è raggiungibile, `/ai-music` risponde con un messaggio chiaro e il resto del bot funziona normalmente.

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
2. Sempre in **Bot → Privileged Gateway Intents** attiva **Message Content Intent** e **Server Members Intent** (serve a `/new-speaker` per vedere chi è in vocale): il bot lo richiede all'avvio e, se non è attivo anche nel portale, parte con un errore che lo ricorda.
3. In **OAuth2 → URL Generator** scegli gli scope `bot` e `applications.commands` e questi permessi: *View Channels*, *Send Messages*, *Embed Links*, *Attach Files* (`/ace-step` allega il brano solo se non può suonarlo in vocale), *Connect* e *Speak* (voce).
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

## Dashboard: gestire soundboard, voci clonate e modelli RVC dal browser

Niente più file JSON da modificare a mano: tutto ciò che il bot "ricorda" (suoni, voci clonate, modelli RVC,
quali modelli sono disponibili in quali server) sta in un database SQLite e si gestisce da una pagina web.

### Attivarla
1. Nel file `.env` imposta una password (almeno 8 caratteri):
```
DASHBOARD_PASSWORD=una-password-lunga-e-tua
```
2. Avvia il bot (`make run`): nel terminale compare `🖥️  Dashboard: http://127.0.0.1:8080`. Aprila nel browser e accedi.

Senza `DASHBOARD_PASSWORD` la dashboard resta **spenta** (il bot funziona uguale).

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
| `DRIFTBOT_DB` | `src/cogs/data/driftbot.sqlite3` | Percorso del database |

### Cosa puoi fare
- **Panoramica** — stato del bot, numeri, stato del database e della coda di scrittura.
- **Soundboard** — aggiungi, ascolta, rinomina, sposta ed elimina i suoni. Ogni suono è di un server **oppure globale**
  (🌐: disponibile in tutti i server). Nel comando `/soundboard` i suoni globali compaiono con il 🌐 davanti.
- **Voci clonate** — le voci usate da `/tts-ai`, una lista per server: ascolta, rinomina, elimina, oppure carica un campione
  (le voci si creano anche dal bot con `/new-speaker`).
- **Modelli RVC** — carica uno `.zip` (con il `.pth` ed eventualmente l'`.index`) o un singolo `.pth`; attiva/disattiva un modello
  con un interruttore, scegli se è disponibile in **tutti** i server o solo in alcuni, elimina. «Cerca nuovi modelli» registra
  le cartelle che hai copiato a mano in `src/cogs/RVC/models/`.
- **Server** — i server in cui il bot è presente e cosa hanno salvato. **Registro** — chi ha cambiato cosa e quando.

### Sicurezza
La dashboard può caricare ed eliminare file, quindi è protetta come un pannello di amministrazione:
password obbligatoria, in ascolto solo su `127.0.0.1`, sessione in cookie `HttpOnly` + `SameSite=Strict`, token CSRF su ogni
modifica, blocco dopo 5 password sbagliate, controllo del formato audio dal contenuto (non dall'estensione), nomi dei file
generati dal server (nessun percorso scelto dall'utente) e intestazioni di sicurezza (CSP, `nosniff`).

**Se la apri alla rete** (`DASHBOARD_HOST=0.0.0.0`) mettila dietro un reverse proxy **HTTPS** (Caddy, nginx...) e imposta
`DASHBOARD_COOKIE_SECURE=1`: senza HTTPS la password viaggerebbe in chiaro (il bot lo segnala nei log).
Per accedere a una dashboard che gira su un altro computer senza esporla, puoi usare un tunnel SSH:
`ssh -L 8080:127.0.0.1:8080 utente@server`.

### Dashboard in un processo separato (facoltativo)
Per tenere la dashboard attiva anche a bot fermo: metti `DASHBOARD_IN_BOT=0` nel `.env` e avviala con `make dashboard`.
I due processi usano lo stesso database senza problemi (vedi sotto).

---

## Dove stanno i dati

- **Database**: `src/cogs/data/driftbot.sqlite3` (suoni, voci, modelli, server, registro). Fai il backup di questo file
  (con il bot fermo, oppure copiando insieme anche `-wal` e `-shm`).
- **File dei server**: `src/cogs/data/<id-server>/soundboard/` e `.../speakers/`; i suoni globali in `src/cogs/data/global/soundboard/`.
  I nomi dei file sono generati dal bot: gestisci tutto dalla dashboard o dai comandi, non rinominare i file a mano.
- **Modelli RVC**: `src/cogs/RVC/models/<cartella>/`.

### Scritture contemporanee
SQLite accetta una sola scrittura alla volta. Per questo ogni modifica (da un comando del bot, dalla dashboard, da un
caricamento) passa da una **coda di scrittura**: un solo thread le esegue in ordine e le raggruppa in un'unica transazione,
mentre le letture (autocomplete, liste) vanno in parallelo grazie alla modalità WAL e non aspettano mai la coda. Se la dashboard
gira in un altro processo, SQLite stesso arbitra i due processi (attesa di fino a 10 secondi e nuovi tentativi). Se due persone
creano nello stesso momento un suono con lo stesso nome ne vince uno solo, l'altro riceve un messaggio chiaro e non resta nessun file orfano.

### Se hai già dei vecchi file JSON
Al primo avvio il bot importa da solo `data/<server>/soundboard/index.json`, `data/<server>/speakers/index.json` (+ `alias.json`)
e `RVC/index.json` nel database, poi rinomina i file in `*.json.migrated` (non li cancella). Le voci che puntano a file
inesistenti vengono saltate e segnalate nei log. Dopo l'import i JSON non servono più.

---

## Note importanti
- FFmpeg è richiesto per il lavoro con audio: se il bot dà errore "ffmpeg not found", installalo come indicato sopra.
- Nei comandi `/soundboard`, `/tts-ai`, `/rename-speaker` e `/ai-cover` scegli sempre dall'elenco che compare mentre scrivi:
  il bot usa l'identificativo dell'elemento, non il testo digitato.
- Un modello RVC disattivato (o limitato ad altri server) non compare in `/ai-cover`; se lo disattivi mentre una richiesta è
  già in coda, l'utente riceve un avviso e la coda prosegue.

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
- `make dashboard`: avvia solo la dashboard, in un processo separato dal bot
- `make test`: esegue i test con la copertura (servono le dipendenze di sviluppo: `make install-dev`)
- `make lint`, `make format`, `make type-check`, `make pre-commit`: controlli di qualità del codice
- `make test-py`: verifica che PyTorch veda la GPU
- `make update`: aggiorna le dipendenze

---
