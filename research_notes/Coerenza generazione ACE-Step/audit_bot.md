# Audit: come DriftBot chiama ACE-Step e cosa cambiare per coerenza e aderenza al prompt

Fonti: solo file locali (nessun URL). Sigle: BOT = /home/drift/git/DriftBot, ACE = /home/drift/git/ACE-Step-1.5. Il "log" e' ACE/acestep-api.log (sessione 2026-11-19 11:36-11:46, letto, nessun server avviato).

## 1. Cosa invia esattamente AceStepClient.submit a /release_task, e quali sono i default di durata, lingua, formato?

### Takeaway
Il bot invia un body minimo con prompt grezzo dell'utente come caption, lyrics, `vocal_language`, `audio_duration`, `thinking=True`, `lm_temperature=0.7`, `inference_steps=8`, `use_cot_caption=False`. Defaults: durata 180 s (max 180 configurabile fino a 600), lingua `it`, formato `mp3`. Non invia bpm, key, time signature, ne' una caption "da stile".

### Cited Findings
- Body completo di `submit`: `prompt`, `lyrics` (o `[Instrumental]`), `vocal_language`, `audio_duration`, `batch_size=1`, `audio_format`, `use_random_seed=True`, `task_type=text2music`, `thinking=bool(lm_model)`, `lm_temperature=0.7`, `inference_steps=8`, `use_cot_caption=False` — BOT/src/cogs/ace_step_cog.py:218-235.
- `prompt` e' il testo libero scritto dall'utente nello slash command (`Range[str, 3, 500]`), passato senza trasformazioni — BOT/src/cogs/ace_step_cog.py:552, 558, 674. Nel log la caption ricevuta dal DiT era `fai una canzone su aldo moro in stile western` (frase italiana di richiesta, non un elenco di stili) — ACE/acestep-api.log (blocco `text_prompt: # Caption`, ~riga 414-420).
- Durata: se `durata` e' omessa si usa `max_seconds` (default 180), clamp a [10, max_seconds]; il server accetta 10-600 — BOT/src/cogs/ace_step_cog.py:105, 131, 570-571, 72-73; README BOT riga 52 e 108. Con max 180 default anche la durata *predefinita* e' 180.
- Lingua: default `it` (`ACESTEP_DEFAULT_LANGUAGE`), valori ammessi `it,en,es,fr,de,pt` — BOT/src/cogs/ace_step_cog.py:122-125, 572; BOT/src/lyrics_llm.py:21-29. Tutte sono in `VALID_LANGUAGES` del server — ACE/acestep/constants.py:13-20.
- Formato: `mp3` default, ammessi mp3/flac/opus/aac/wav — BOT/src/cogs/ace_step_cog.py:76, 118-121. Il server supporta anche `wav32` — ACE/docs/en/API.md:144.
- Il DiT ha davvero ricevuto `# Languages it` (la lingua dell'utente non e' sovrascritta dal CoT): nel log il LM ha prodotto `language: unknown` ma il prompt DiT riporta `it` — ACE/acestep-api.log (~riga 262 e ~424-428). Motivo: il LM scrive la chiave `language`, il codice legge `vocal_language` e ricade sull'input — ACE/acestep/inference.py:827-828, 381-382, ACE/acestep/llm_inference.py:2876-2877.
- Parametri server che il bot lascia ai default: `use_cot_language=True` (ACE/acestep/api/http/release_task_request_builder.py:97), `lm_cfg_scale=2.5` (riga 89 e release_task_models.py:135), `lm_top_p=0.9`, `lm_top_k` nullo->0, `lm_repetition_penalty=1.0`, `lm_negative_prompt="NO USER INPUT"`, `constrained_decoding=True` (stesso file, righe 90-97).
- Il bot avvia il server con `--init-llm --lm-model-path acestep-5Hz-lm-1.7B` e `ACESTEP_LM_BACKEND=pt`, `ACESTEP_ROCM_DTYPE=bfloat16`, `MIOPEN_FIND_MODE=FAST`, `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True` — BOT/src/cogs/ace_step_cog.py:395-410.
- Il testo fornito dall'utente (`testo`, max 2000 caratteri) passa senza pulizia ne' normalizzazione dei tag; solo il testo scritto da Claude passa da `clean_lyrics` — BOT/src/cogs/ace_step_cog.py:554, 598-602; BOT/src/lyrics_llm.py:106-162.

### Inferences
- La caption e' il fattore piu' importante secondo la doc (ACE/docs/en/Tutorial.md:339) ed e' proprio il campo meno curato dal bot: una richiesta in linguaggio naturale con tema ("una canzone su X") invece di stile/strumenti/mood/voce. Il tema e' gia' nei lyrics; la caption dovrebbe descrivere solo il suono.
- Con `thinking=True` il LM sceglie da solo bpm/key/time signature: nel log ha scelto `bpm 70, timesignature 2, G major` per un brano "western" (ACE/acestep-api.log ~righe 259-263, 419-422), cioe' scelte non ancorate al genere richiesto.

### Gaps
- Non ho verificato se i tag di sezione minuscoli (`[verse]`) vs maiuscoli (`[Verse]`, usati in doc) cambino il comportamento del modello: nessuna doc o codice letto lo dice.
- Nessuna prova su quanto una caption in italiano degradi rispetto a una in inglese: la doc dice solo che i formati di caption sono tutti supportati (Tutorial.md:341), non delle lingue della caption.

## 2. Come LyricsWriter costruisce il prompt e post-processa il testo (tag, lunghezza righe, sillabe vs durata, lingua)? La lunghezza combacia con la durata?

### Takeaway
Il prompt chiede "~una riga ogni 6 s" (8-40 righe), righe di 4-9 *parole*, tag minuscoli `[verse]/[chorus]/[bridge]/[outro]`, coro ripetuto identico. Per durate medie (180 s) il rapporto e' ragionevole, ma ai due estremi no, e il vincolo in parole equivale a 9-20 sillabe italiane contro le 6-10 raccomandate da ACE-Step.

### Cited Findings
- `target_lines(seconds) = max(8, min(40, round(seconds/6)))` — BOT/src/lyrics_llm.py:37-39. Tabella derivata dalla formula: 10 s -> 8 righe; 30 s -> 8 righe; 60 s -> 10; 180 s -> 30; 300 s -> 40 (tetto); 600 s -> 40 righe (un verso ogni 15 s).
- System prompt: lingua target, tag di sezione "in lowercase square brackets: [verse], [chorus], [bridge], [outro]", "Repeat the same [chorus] text each time", "Short singable lines (4 to 9 words), with rhythm and rhyme", niente titolo/markdown/accordi/stage directions — BOT/src/lyrics_llm.py:45-56. User prompt: `<description>{prompt}</description>` + "Write about N lines of lyrics, for a song of S seconds" — righe 57-60.
- Nessun `[intro]`, nessun tag combinato (`[Chorus - anthemic]`), nessun tag strumentale o di voce/energia richiesto; nessun cenno a sillabe, maiuscole per l'enfasi, parentesi per i cori — BOT/src/lyrics_llm.py:45-60 (assenza). La doc li raccomanda: tag base e combinati (ACE/docs/en/Tutorial.md:412-453), tag vocali/energia (Tutorial.md:483-507), MAIUSCOLO per intensita' e parentesi per background vocals (Tutorial.md:528-545).
- Doc ACE: "6-10 syllables per line usually works best"; righe di lunghezza molto diversa danno ritmo strano; similari a parita' di posizione (+-1-2) — ACE/docs/en/Tutorial.md:513-523; ripetuto in ACE/docs/en/ace_step_musicians_guide.md:332 ("6-10 syllables").
- Doc ACE: non impilare tanti tag in un solo tag, il modello puo' scambiare il testo del tag per testo da cantare — ACE/docs/en/Tutorial.md:446-460.
- Doc ACE: caption e lyrics devono raccontare la stessa storia; i conflitti degradano la qualita' — ACE/docs/en/Tutorial.md:464-481.
- Doc ACE sul testo: sezioni separate da riga vuota (Tutorial.md:560), evitare metafore miste e "AI-flavored" (righe 574-586).
- Post-processing `clean_lyrics`: rimuove `<think>`, markdown, intro; normalizza alias di sezione in 6 lingue in tag minuscoli (`_SECTION_ALIASES`), tiene altri tag tra quadre, tronca a 2000 caratteri su riga intera, toglie tag orfani finali, richiede almeno 2 righe cantabili e 20 caratteri, aggiunge `[verse]` iniziale se manca — BOT/src/lyrics_llm.py:71-162. Non conta ne' bilancia righe/sillabe; non controlla che il numero di righe sia vicino al target.
- Esempio reale (log): 30 righe in 7 sezioni (verse6/chorus4/verse6/chorus4/bridge4/chorus4/outro2) per 180 s, con righe italiane tipo "Era marzo e soffiava un vento strano" (~11-12 sillabe) — ACE/acestep-api.log (blocco `# Lyric`, ~righe 205-245). Quindi oltre la fascia 6-10 sillabe.
- La doc ACE per brani con testo raccomanda auto-detection della durata (`duration=-1`): "With Lyrics: Auto-detection recommended" — ACE/docs/en/INFERENCE.md:1040; `duration <= 0` fa scegliere al modello in base alla lunghezza del testo — ACE/docs/en/INFERENCE.md:350 e ACE/acestep/api/job_generation_setup.py:177 (`_AUTO_DURATION_SENTINEL = -1.0`, riga 14 di `job_generation_setup.py`).
- Il bot invece fissa sempre `audio_duration` (cog:222) e scrive il testo *dopo* aver scelto la durata (cog:570-571, 620).
- Il testo e' scritto con Claude `claude-opus-5-5` (default) con `max_tokens=8000`, senza temperature (non supportata), `effort=low` default — BOT/src/text_llm.py:45, 78, 244-252; README BOT righe 23-24.
- L'LLM riceve il prompt grezzo dell'utente (`<description>`) ma non la caption stile che vorremmo inviare ad ACE-Step, quindi i due testi non vengono co-progettati — BOT/src/lyrics_llm.py:57-60.

### Inferences
- A 10-30 s il minimo di 8 righe e' troppo denso (8 righe in 10 s = ~0,8 righe/s): sezioni frettolose/mangiate. A 600 s il tetto di 40 righe e di 2000 caratteri lascia ~15 s per riga: il modello riempie con strumentale/ripetizioni e la doc stessa avverte di ripetizioni o problemi di struttura sui brani molto lunghi (Tutorial.md:677).
- Il vincolo "4-9 parole" in italiano supera facilmente le 10 sillabe; spostare il vincolo a "6-10 sillabe, righe omogenee" e' coerente con la doc e a basso costo.
- La corrispondenza durata/testo e' accettabile a 120-240 s, che e' esattamente la fascia indicata come stabile dalla doc (Tutorial.md:677).

### Gaps
- Non ho misurato quanti secondi cantati servono per riga con il DiT turbo; la formula "6 s per riga" e' una euristica del bot non validata da nessuna fonte letta.
- Non e' stato verificato se `[verse]` minuscolo e' trattato come `[Verse]` dal tokenizer/modello.

## 3. Quali parametri API supportati non sono esposti o sono settati male, e quali non servono con il turbo?

### Takeaway
Molti parametri "di qualita'" sono inutili sul turbo (CFG, shift, ADG, intervallo CFG). Quelli che contano e il bot non usa sono: caption stile, `bpm`/`key_scale`/`time_signature`, `use_cot_language=False`, e gli stessi parametri LM (`lm_cfg_scale`, `lm_top_k`, `lm_repetition_penalty`). DCW e' attivo di default per il turbo ma e' un no-op perche' manca `pytorch_wavelets`.

### Cited Findings
- Turbo ignora CFG: `guidance_scale` viene forzato a 1.0 (`Turbo model detected: overriding guidance_scale 7.0 -> 1.0`) — ACE/acestep/core/generation/handler/generate_music.py:309-318; nel log riga ~394. API.md:202 dice "Only effective for base model".
- `shift` "Only effective for base models, not turbo" — ACE/docs/en/API.md:211 e ACE/acestep/api/http/release_task_models.py:92-95. Contraddizione interna: Tutorial.md:836 riporta default 1.0 (la tabella API.md/builder ha 3.0). Per il turbo non cambia comunque nulla secondo l'API.
- `use_adg` "base model only" (API.md:214); `cfg_interval_start/end` agiscono sul CFG, quindi nulla sul turbo (stessa logica generate_music.py:312).
- `inference_steps`: turbo 1-20, raccomandato 8 — il bot usa 8 (ok) — ACE/docs/en/API.md:200; BOT/src/cogs/ace_step_cog.py:232.
- `infer_method`: `ode` default (API.md:212), il bot non lo invia; `sde` aggiunge casualita', non coerenza — ACE/docs/en/Tutorial.md:848, 889.
- `timesteps` (stringa custom) sovrascrive `inference_steps`/`shift` — ACE/docs/en/API.md:213. Non e' raccomandato cambiarlo senza A/B.
- DCW: `dcw_enabled=None` -> True per turbo; default `dcw_mode=double`, `dcw_scaler=0.05`, `dcw_high_scaler=0.02` — ACE/acestep/api/http/release_task_models.py:101-113; ACE/acestep/core/generation/handler/generate_music.py:181-193; ACE/docs/en/DCW.md:81. Nel log: `DCW is enabled but 'pytorch_wavelets' is not installed ... Falling back to no-op` — ACE/acestep-api.log riga 496 (`dcw_loader.py:39`). `ls venv_rocm/.../site-packages` non mostra `pytorch_wavelets` ne' `pywt`.
- `bpm` (30-300), `key_scale`, `time_signature` sono supportati e user-provided values "always win"; la doc dice che le impostazioni manuali sono anchor, non comandi, e di non mettere tempo/bpm/key nella caption — ACE/docs/en/API.md:186-189 e 175-180; ACE/docs/en/Tutorial.md:658-700. Il bot non li invia (cog:218-235).
- `use_cot_language` default True: il server chiama il LM anche per rilevare la lingua (API.md:238; builder riga 97). La lingua e' gia' nota (`vocal_language`) e il LM l'ha restituita come `unknown` nel log (acestep-api.log ~262). L'effetto sul DiT e' nullo (vedi domanda 1) ma consuma tempo/contesto LM. Non esiste flag per `use_cot_metas` (hardcoded `not sample_mode`) — ACE/acestep/api/job_generation_setup.py:211.
- Parametri LM esposti e non usati dal bot: `lm_cfg_scale` (default 2.5, "higher = more positive prompt adherence"), `lm_top_k`, `lm_top_p`, `lm_repetition_penalty`, `lm_negative_prompt` — ACE/docs/en/API.md:222-230; ACE/docs/en/Tutorial.md:855-863; ACE/docs/en/INFERENCE.md:399-404. Raccomandazione doc "For Consistency: keep lm_temperature 0.7-0.85" — ACE/docs/en/INFERENCE.md:1027-1030. Il bot e' a 0.7 (cog:231), in fascia.
- `use_format` / `sample_query`: il LM puo' riformattare caption/lyrics o generare da descrizione (API.md:149-153). `use_cot_caption=False` e' una scelta motivata dal bot (il LM riscriveva "lofi piano" in "folk-rock") — BOT/src/cogs/ace_step_cog.py:233-234; README BOT riga 79. Con 0.6B (vedi domanda 5) la capacita' di riscrittura e' ancora piu' limitata (tabella README ACE "Query rewrite" ✅, "Composition Capability: Medium").
- `batch_size=1` (cog:223): il server ha default 2 e permette fino a 8 (API.md:207). Piu' candidati + `DiT Lyrics Alignment Score` permetterebbero di scegliere la versione migliore (ACE/docs/en/Tutorial.md:935-952), ma l'API REST non risulta restituire un punteggio in `/query_result` (non trovato in API.md:395-418).
- Tutorial.md:216-220: SFT model supporta CFG e 50 passi, "detail expression and semantic parsing will be better"; non e' installato (domanda 5).

### Inferences
- Su turbo l'unica leva di aderenza al prompt lato DiT e' il contenuto della caption/lyrics; i parametri "guidance" sono inerti. Quindi migliorare caption e lyrics batte qualunque tuning di sampler.
- Ancorare bpm/key/time-signature per generi riconoscibili ridurrebbe la deriva vista nel log (western a 70 bpm in 2/4), ma il bot dovrebbe saperli ricavare (es. da Claude, vedi domanda 6) per non introdurre conflitti con la caption (Tutorial.md:698).
- Installare `pytorch_wavelets PyWavelets` in venv_rocm abiliterebbe il DCW che il server gia' considera il default del turbo (DCW.md:81); non ho prove di quanto migliori la coerenza su ROCm/bf16.

### Gaps
- Non ho trovato in `/query_result` un campo di punteggio per scegliere tra batch (grep su API.md).
- Non verificato se `pytorch_wavelets` si installa/funziona su ROCm 6.4 (non ho eseguito nulla).
- Nessuna evidenza quantitativa che `lm_cfg_scale` maggiore o `lm_repetition_penalty` >1 migliorino la coerenza del 0.6B.

## 4. Il default di 180 s (fino a 600 s) rischia di degradare la coerenza? Cosa dicono codice e doc?

### Takeaway
180 s sta nella fascia "medio" che la doc definisce stabile (2-4 min), ma e' vicino al limite alto; oltre i ~240 s la doc avverte di ripetizioni e problemi di struttura. Il limite di 600 s e' un limite di memoria/server, non di qualita'. Sul tuo hardware il LM tier3 e' capped a 480 s.

### Cited Findings
- "Short songs (30-60s) and medium length (2-4min) are stable; very long generation may have repetition or structure issues" — ACE/docs/en/Tutorial.md:677.
- INFERENCE.md: "Instrumental: 30-180 s works well; With Lyrics: auto-detection recommended; Short clips: 10-20 s minimum; Long form up to 600 s" — ACE/docs/en/INFERENCE.md:1037-1042.
- Limiti GPU: tier3 (6-8 GB) max 480 s con LM / 600 s senza LM — ACE/docs/en/GPU_COMPATIBILITY.md:11; ACE/acestep/gpu_config.py:354-372. Il log conferma `Max Duration (with LM): 480s` e `constrained decoding max_duration 480s` — ACE/acestep-api.log righe ~19-21, 65.
- Il LM lavora a 5 Hz: 180 s = 900 codici audio (`Generated 900 audio codes`), il che richiede 129,8 s (Phase 2) con backend pt — ACE/acestep-api.log riga 393; il DiT 26,4 s e il VAE ~33 s (decode tiled con `offload_wav_to_cpu=True`) — acestep-api.log righe 506, 518-531. I 600 s richiederebbero ~3,3x i codici LM.
- Il LM nel log ha prodotto `duration: 180` come CoT, coerente con la durata richiesta (user_metadata): `user_metadata['duration']` e' passato al LM — ACE/acestep/inference.py:696-702.
- Il bot imposta il default = massimo = 180 (README BOT riga 52); `ACESTEP_TIMEOUT=600` s per generazione (cog:106, 132).
- Il bot ha gia' avuto un OOM sulla prima richiesta della sessione (LM load, `GPU 0 ... 158 MiB free`, 4,46 GiB allocati) — ACE/acestep-api.log righe 131, 163-187; la richiesta successiva e' andata a buon fine.

### Inferences
- Portare il default a ~120-150 s (o a una durata derivata dal testo, `duration=-1`) resta nella fascia stabile e riduce il carico LM (-30/-20% codici) e di VAE. 180 s non e' un difetto, ma non c'e' alcun vantaggio di coerenza a stare su 180.
- Esporre fino a 600 s agli utenti nello slash command (`ACESTEP_MAX_SECONDS` max 600, cog:131-143) invita a brani oltre la fascia stabile; consigliabile un tetto di 240-300 s.
- Brani corti (<30 s) con 8 righe minime (lyrics_llm.py:39) sono troppo densi.

### Gaps
- Nessun benchmark nella doc su coerenza vs durata oltre l'affermazione qualitativa di Tutorial.md:677; `docs/en/BENCHMARK.md` non e' stato letto in dettaglio per questa domanda.
- La causa del primo OOM (stato iniziale di VRAM, TTS ancora residente?) non e' dimostrata dal log.

## 5. Quali modelli sono installati in ACE/checkpoints e quali env ACESTEP_* influenzano la qualita'?

### Takeaway
Installati: DiT `acestep-v15-turbo`, LM `acestep-5Hz-lm-0.6B` e `acestep-5Hz-lm-1.7B`, `vae`, `Qwen3-Embedding-0.6B`. Ma il server su 8 GB (tier3) *scarta* il 1.7B e carica il 0.6B: la configurazione "1.7B" che README e commenti del bot dichiarano non e' quella in uso.

### Cited Findings
- Contenuto di `ACE/checkpoints`: `acestep-5Hz-lm-0.6B`, `acestep-5Hz-lm-1.7B`, `acestep-v15-turbo` (con `config.json` `"is_turbo": true`, `"model_version": "turbo"`), `vae`, `Qwen3-Embedding-0.6B` — `ls ACE/checkpoints` e ACE/checkpoints/acestep-v15-turbo/config.json. Non ci sono SFT, base, XL, turbo-shift1/shift3.
- Log di avvio: `Using user-specified LM model: acestep-5Hz-lm-1.7B` -> `LM model acestep-5Hz-lm-1.7B (1.7B) is not supported for your GPU (8.0GB). Available models: acestep-5Hz-lm-0.6B` -> `Falling back to supported LM model: acestep-5Hz-lm-0.6B` — ACE/acestep-api.log righe ~49-53; logica in ACE/acestep/api/startup_llm_init.py:52-72 e ACE/acestep/gpu_config.py:1388-1413. Il VRAM e' 7,98 GB -> `tier3` (<=8 GB) — gpu_config.py:743-760; tier3 permette solo `acestep-5Hz-lm-0.6B` (gpu_config.py:354-372; GPU_COMPATIBILITY.md:11, 78).
- Il fallback e' incondizionato; l'unico modo di aggirarlo documentato nel codice e' simulare piu' VRAM con `MAX_CUDA_VRAM` (gpu_config.py:481-495), che sul tier5 (>12 GB) abiliterebbe 1.7B ma su una scheda reale da 8 GB e' rischioso (OOM gia' visto con 0.6B). README BOT riga 129 suggerisce `MAX_CUDA_VRAM=8`, che non cambia tier.
- Differenza tra LM: 0.6B "Copy Melody: Weak", 1.7B "Medium", 4B "Strong"; composizione "Medium" per 0.6B e 1.7B — ACE/README.md:276-280. Quindi il guadagno atteso 0.6B->1.7B sulla composizione e' limitato per la tabella ufficiale.
- XL (4B) DiT: richiede >=12 GB con offload+quantizzazione — ACE/docs/en/Tutorial.md:255-257; GPU_COMPATIBILITY.md:11 (colonna XL ❌ per tier3).
- Env lato server che incidono sulla qualita' o sulla scelta modelli (da `.env.example`, API.md e codice): `ACESTEP_CONFIG_PATH` (DiT, default turbo) e `_PATH2/_PATH3` per modelli aggiuntivi selezionabili con il campo `model` — ACE/.env.example:14, ACE/docs/en/API.md:158, 745, 872; `ACESTEP_LM_MODEL_PATH` (ACE/.env.example:18; startup_llm_init.py:52); `ACESTEP_LM_BACKEND` (pt su ROCm, il bot lo imposta, cog:406); `ACESTEP_INIT_LLM`; `ACESTEP_DEVICE`; `ACESTEP_OFFLOAD_TO_CPU`, `ACESTEP_OFFLOAD_DIT_TO_CPU`, `ACESTEP_LM_OFFLOAD_TO_CPU` (API.md:740-760); `ACESTEP_USE_FLASH_ATTENTION` (nel log flash attention non disponibile -> SDPA, righe 39 e 65-68); `ACESTEP_ROCM_DTYPE` (default float32, il bot usa bfloat16) — ACE/acestep/core/generation/handler/init_service_orchestrator.py:28-40; BOT/src/cogs/ace_step_cog.py:409.
- Il dtype del DiT nel log e' bfloat16 (`pred_latents ... dtype=torch.bfloat16`) — ACE/acestep-api.log riga 505.
- Env che non incidono sulla qualita' (solo operativi): `ACESTEP_QUEUE_*`, `ACESTEP_AVG_*`, `ACESTEP_TMPDIR`, cache dirs, `ACESTEP_API_KEY` — API.md:762-780.
- Non esiste una variabile ACESTEP_* per cambiare `lm_temperature`, `use_cot_*`, `lm_cfg_scale` (sono campi di richiesta; il default LM temperature e' hardcoded 0.85 in ACE/acestep/api_server.py:117); i default si cambiano solo nel body della richiesta.

### Inferences
- Il 1.7B sul tuo 8 GB non e' raggiungibile senza hack; allineare README/commenti/`lm_model` del bot a `acestep-5Hz-lm-0.6B` eviterebbe l'aspettativa errata. Un 0.6B e' meno affidabile come pianificatore (bpm/key/time signature "western a 70 bpm 2/4" visti nel log), il che rafforza l'idea di ancorare i metadati lato bot.
- Il passaggio da bfloat16 a float32 migliorerebbe in teoria la precisione, ma il README del bot (riga 88) riporta che float32 va in OOM su 8 GB. Nessuna misura sull'impatto qualita' di bf16.

### Gaps
- Non e' chiaro se la quantizzazione INT8 di default del tier3 (GPU_COMPATIBILITY.md:11) sia attiva: nel log non compaiono righe `quantiz|int8|compile` (grep), quindi non confermabile.
- Non verificato se la scelta SFT/turbo-shift3/continuous sia tecnicamente possibile con 8 GB (non installati; i checkpoint andrebbero scaricati).

## 6. Elenco ordinato di modifiche minime (file:riga) per migliorare la coerenza

### Takeaway
Le modifiche con piu' effetto atteso sono (1) separare la caption di stile dal tema e farla scrivere a Claude in inglese, (2) rendere testo e durata coerenti (sillabe 6-10, tag ricchi, numero di righe per durata), (3) ancorare bpm/key/time-signature, (4) togliere sprechi/ambiguita' lato server (use_cot_language, DCW, 1.7B non realmente in uso). Tutte sono modifiche di poche righe; nessuna e' misurata ad orecchio: andrebbero A/B con `seed` fisso (Tutorial.md:873 consiglia di fissare il seed per il tuning).

### Cited Findings
Ordine = effetto atteso / costo (le motivazioni sono nelle sezioni sopra; il livello di prova e' indicato).

1. **Caption di stile separata dal tema (alta; supporto doc forte).** Oggi `prompt` utente grezzo e' la caption (BOT/src/cogs/ace_step_cog.py:219, 674; log: caption "fai una canzone su aldo moro in stile western"). Cambiare: far produrre a Claude, oltre al testo, una riga di caption in inglese con genere, strumenti, mood, timbro/voce (es. `western ballad, acoustic guitar, harmonica, male baritone vocal, dusty, cinematic`), e inviarla come `prompt`; tenere il tema solo nei lyrics. Punti: BOT/src/lyrics_llm.py:45-61 (prompt Claude e formato di output), BOT/src/lyrics_llm.py:106-162 (parsing), BOT/src/cogs/ace_step_cog.py:620 e 674 (passare la caption), con fallback alla caption attuale se Claude non la restituisce. Doc: Tutorial.md:339, 464-481, 700. Se l'utente passa `testo`, usare l'LLM solo per la caption.
2. **Righe in sillabe, non in parole; omogeneita' (alta; doc).** BOT/src/lyrics_llm.py:51 "Short singable lines (4 to 9 words)" -> "6 to 10 syllables per line, similar length for matching lines in each section". Doc: Tutorial.md:513-523.
3. **Tag di sezione piu' ricchi e coerenti con la caption (media-alta; doc).** BOT/src/lyrics_llm.py:49-50: aggiungere `[intro]` (instrumentale o breve), tag singolo combinato (`[Chorus - anthemic]`) al massimo uno per sezione, righe vuote tra sezioni, MAIUSCOLO sulle parole forti nel coro, parentesi per cori; i tag strumentali devono usare solo strumenti presenti nella caption. Aggiornare `_SECTION_ALIASES`/`clean_lyrics` (BOT/src/lyrics_llm.py:71-103) per non appiattire a minuscolo i tag combinati (`_normalize_tag` oggi ritorna `[candidate.lower()]` e perde la capitalizzazione: righe 101-102). Doc: Tutorial.md:412-460.
4. **Righe vs durata (media; ragionamento sul codice).** BOT/src/lyrics_llm.py:37-39: `max(8, ...)` troppo denso sotto ~50 s, `min(40, ...)` troppo rado sopra ~240 s. Proposta: minimo 4-6 righe sotto 30 s, tetto 40 e *tetto di durata coerente* (punto 5). Doc: Tutorial.md:677.
5. **Durata default/tetto (media; doc qualitativa).** BOT/src/cogs/ace_step_cog.py:105 e 131 (`max_seconds` 180) e :570 (default = massimo): separare default (~120-150 s) dal massimo, e fissare il massimo a 240-300 invece di permettere 600 (cog:73, 131). Alternativa documentata: lasciare `audio_duration` a None/-1 quando c'e' testo (INFERENCE.md:350, 1040; job_generation_setup.py:177), ma il bot oggi calcola il numero di righe dalla durata (lyrics_llm.py:59), quindi richiederebbe di invertire l'ordine.
6. **Ancorare bpm / key_scale / time_signature (media; doc + log).** Aggiungere a `submit` (BOT/src/cogs/ace_step_cog.py:218-235) i tre campi (API.md:186-189) ricavati da Claude insieme alla caption (come al punto 1); non scriverli nella caption (Tutorial.md:700). Il log mostra bpm 70 / 2/4 per un western scelti dal 0.6B (acestep-api.log ~259-263). Evitare valori estremi (Tutorial.md:677-690). Costo: parsing di 3 campi.
7. **`use_cot_language=False` (bassa-media; codice).** BOT/src/cogs/ace_step_cog.py:233-234 accanto a `use_cot_caption`: la lingua e' gia' fornita e il LM ha risposto `unknown` (log ~262); evita lavoro CoT inutile. Nessun effetto sul DiT dimostrato (inference.py:827-828).
8. **Allineare la configurazione LM alla realta' (bassa su qualita', alta su onesta'/aspettative).** BOT/src/cogs/ace_step_cog.py:112, 137, 396-397 e README BOT righe 75, 79, 113: indicare `acestep-5Hz-lm-0.6B` (il server fa fallback automatico, log ~49-53). Evita la falsa aspettativa del 1.7B e il tempo di verifica del fallback.
9. **Installare `pytorch_wavelets PyWavelets` in venv_rocm per abilitare il DCW del turbo (da testare).** ACE/venv_rocm (nessuna modifica al bot); log riga 496; DCW.md:81. Non ho prove sull'impatto in coerenza; A/B con seed fisso consigliato.
10. **Tuning LM (bassa; non provato).** BOT/src/cogs/ace_step_cog.py:231: `lm_temperature` 0.7 e' gia' in fascia (INFERENCE.md:1027-1030); opzionale testare `lm_cfg_scale` piu' alto (default 2.5; API.md:227) e `lm_repetition_penalty` leggermente >1 solo se si osservano loop. Nessuna evidenza nel materiale letto.
11. **Candidati multipli (bassa; richiede selezione).** `batch_size` 2-4 (cog:223) solo se si implementa una scelta (non c'e' un punteggio in `/query_result`); su tier3 `Max Batch Size (with LM) = 2` (log riga ~21; GPU_COMPATIBILITY.md:11) e raddoppierebbe tempo/VRAM. Non consigliato su 8 GB.
12. **Ignorare:** `guidance_scale`, `shift`, `use_adg`, `cfg_interval_*` (inerti sul turbo: generate_music.py:312; API.md:202, 211, 214), `infer_method=sde` (aggiunge casualita'), `timesteps` custom (rischio senza A/B).

### Inferences
- Le modifiche 1, 2, 3, 6 insieme rispondono al problema piu' probabile dei risultati "poco coerenti": caption incoerente con i testi + deriva dei metadati scelti dal LM piccolo.
- Le modifiche 4 e 5 riducono i casi estremi (brani molto corti/lunghi). Le 7-9 sono igiene/aspettative; l'effetto va misurato.
- Un singolo cambio di prompt a Claude (ritorno strutturato: caption + bpm + key + time sig + lyrics) copre 1, 3 e 6, e il suo costo e' ~una chiamata invariata.

### Gaps
- Nessuna delle modifiche proposte e' stata provata: la coerenza e' soggettiva e il bot non puo' essere eseguito in questo task (GPU/server vietati). Serve A/B con seed fisso (`use_random_seed=False`, `seed`) e stesso prompt prima/dopo.
- Non ho trovato nella doc una verifica che Claude possa produrre caption/metadati in un singolo output senza degradare il testo: e' una scelta di design da testare.
