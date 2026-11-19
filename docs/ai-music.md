# `/ai-music`: modelli, installazione e prestazioni

Guida completa a `/ai-music`: come funziona, quali modelli offre, cosa installare e quanto è veloce.
Il riassunto e le istruzioni di setup del bot sono nel [README](../README.md).

> **In Docker** il bot gira in un container che **non contiene** ACE-Step né HeartMuLa: per `/ai-music` punta
> `ACESTEP_API_URL` a un ACE-Step che gira altrove (sull'host: `http://host.docker.internal:8001`, o un'altra macchina).
> Il livello `accurata` e HeartMuLa, che il bot avvia da solo da cartelle accanto al repository, non sono disponibili
> nel container: con una build Docker `/ai-music` offre solo ACE-Step veloce, tramite `ACESTEP_API_URL`.

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

## Modelli e livelli
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

## La catena (pensata per GPU da 8 GB)
Su 8 GB l'LLM e il modello musicale non entrano insieme in VRAM, quindi il bot li usa **uno dopo l'altro**:

1. **Un LLM prepara il brano** a partire dal prompt (non se hai scelto `strumentale`), con **una sola chiamata**: il testo (righe da 6-10 sillabe, tag `[Intro]`/`[Verse]`/`[Chorus - anthemic]`...), una **caption sonora in inglese** (genere, strumenti, voce, produzione) e **bpm, tonalità e metro** coerenti con lo stile. ACE-Step riceve questi campi al posto della frase grezza dell'utente e dei valori scelti dal suo piccolo LM. Se l'LLM non restituisce l'intestazione, il bot usa il prompt dell'utente e i metadati scelti dal server. **Se hai scritto tu il `testo`** l'LLM non lo riscrive: aggiunge solo caption, metadati e, dove mancano, i tag di sezione, e il bot controlla riga per riga che le parole siano identiche (maiuscole e spazi a parte). Se ne ha toccata anche una sola, tiene il tuo testo com'è e usa comunque caption e metadati; se l'LLM è spento o non risponde, il testo resta il tuo e la caption è il tuo prompt. Con `strumentale` non c'è LLM e la caption resta il tuo prompt: scrivilo come una descrizione sonora. È **Claude** se nel `.env` c'è `ANTHROPIC_API_KEY`, altrimenti un **LLM locale con Ollama**.
2. **Solo con Ollama: l'LLM viene scaricato dalla VRAM.** Il bot chiede a Ollama di liberarlo (`keep_alive: 0`) e **controlla** che non risulti più in memoria prima di andare avanti. Con Claude non c'è nulla da scaricare: il modello gira sui server Anthropic.
3. **ACE-Step compone il brano** con quel testo, e il bot lo riproduce nella vocale mostrando anche il testo. Se ACE-Step è spento e si trova accanto al repository del bot (o in `ACESTEP_DIR`) lo avvia da solo prima di generare.

ACE-Step lavora **un brano alla volta**: se più utenti usano il comando insieme, gli altri aspettano in coda (con un avviso). Con Claude il testo si scrive subito, anche mentre ACE-Step lavora per un altro; con Ollama anche la scrittura del testo aspetta il proprio turno, perché l'LLM locale occuperebbe la VRAM. Ogni utente può avere una sola richiesta attiva.
Se l'LLM non è disponibile (Ollama spento, key errata o credito finito, testo inutilizzabile) il brano viene generato **strumentale** e il bot lo segnala nella risposta. **Con la key presente il bot non ripiega mai in silenzio su Ollama**: sarebbe una sorpresa per la VRAM e nasconderebbe una key sbagliata.

## Cosa installare
Il bot non carica nessun modello nel proprio processo: parla con ACE-Step e con l'LLM (Claude via API, oppure Ollama) tramite rete. Così le dipendenze non entrano in conflitto con quelle di TTS/RVC e CUDA o ROCm si scelgono nell'installazione di ciascun server.

**1. ACE-Step** (istruzioni ufficiali nel repository del progetto):
```bash
git clone https://github.com/ACE-Step/ACE-Step-1.5.git
cd ACE-Step-1.5
uv sync
uv run acestep-api --init-llm --lm-model-path acestep-5Hz-lm-0.6B   # http://127.0.0.1:8001; i modelli si scaricano al primo avvio
```
Se cloni ACE-Step nella stessa cartella che contiene il repository del bot (es. `~/git/ACE-Step-1.5` accanto a `~/git/DriftBot`), **il bot lo avvia da solo** al primo `/ai-music` (log in `acestep-api.log` nella cartella di ACE-Step; si spegne quando il bot si ferma). Gli stessi parametri a mano sono nel comando sopra.

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

## Consigli per 8 GB
- **Con Claude** la VRAM è tutta per ACE-Step: è la configurazione più semplice per schede piccole.
- **ACE-Step:** il suo profilo per 8-12 GB tiene i modelli in RAM quando non servono (offload su CPU), ed è quello che permette all'LLM di usare la GPU mentre ACE-Step è fermo. Controlla con `nvidia-smi` (o `rocm-smi`) a server inattivo che la VRAM occupata sia poca; se non lo è, prova ad avviarlo con `MAX_CUDA_VRAM=8`.
- **TTS e ACE-Step si danno il turno sulla GPU.** Il modello di `/tts-ai` (~3,4 GB) e ACE-Step (~7 GB) insieme non entrano in 8 GB (era l'errore "La generazione è fallita": OOM). Quando parte `/ai-music` il bot scarica il modello TTS dalla VRAM; quando serve `/tts-ai` il bot spegne ACE-Step (se l'ha avviato lui) e ricarica il TTS. Ogni cambio costa qualche decina di secondi alla richiesta successiva dell'altro. AI cover usa la GPU a sua volta e non è coordinato: non usarlo insieme. Con una seconda GPU o un'altra macchina per ACE-Step (`ACESTEP_API_URL`; `HIP_VISIBLE_DEVICES=1` su AMD) i due modelli restano sempre caricati.
- Il supporto AMD ROCm di ACE-Step e di Ollama è dichiarato dai rispettivi progetti: controlla i requisiti nella loro documentazione.

Se un server non è raggiungibile, `/ai-music` risponde con un messaggio chiaro e il resto del bot funziona normalmente.
