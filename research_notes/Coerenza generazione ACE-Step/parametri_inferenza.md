# ACE-Step 1.5: parametri di inferenza e LM che influenzano coerenza e aderenza al prompt (text2music)

Fonte primaria: repo locale `/home/drift/git/ACE-Step-1.5` (HEAD `ca1e85f`, 2026-08-29). Notazione: [DOC] = quanto dichiarano i documenti, [CODE] = cosa fa il codice, [COMM] = opinione/segnalazione di terzi. Hardware target: GPU AMD 8 GB, ROCm, backend LM PyTorch (`pt`).
Percorsi relativi a `/home/drift/git/ACE-Step-1.5/` (link file://).

## 1. Parametri DiT (inference_steps, guidance_scale, shift, infer_method, timesteps, use_adg, cfg_interval) su turbo / base / sft

### Takeaway
Su turbo contano solo `inference_steps` (default 8) e `shift` (3.0 raccomandato); guidance_scale, use_adg e cfg_interval sono ignorati dal codice. Su base/sft contano steps (32-64, default dei modelli 50), guidance_scale (docs 5-9, tipico 7), shift (3.0) e, secondario, use_adg/cfg_interval. I docs sono incoerenti sul `shift` per turbo: il codice dice che conta.

### Cited Findings
- [DOC] Turbo: 8 step, nessun CFG; base e sft: 50 step, CFG supportato (tabella model zoo e tabella "DiT Selection Summary"). — [README.md:258-262](file:///home/drift/git/ACE-Step-1.5/README.md), [docs/en/Tutorial.md:253-262](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC] `inference_steps`: turbo 1-20 (raccomandato 8), base 1-200 (raccomandato 32-64). `guidance_scale` 1.0-15.0, "only supported for non-turbo", tipico 5.0-9.0, default 7.0. — [docs/en/INFERENCE.md:366-367](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md)
- [DOC] Box "Turbo parameter handling": guidance_scale auto-corretto a 1.0 su turbo; shift NON auto-corretto, "set shift=3.0 for turbo"; "the only timestep/guidance parameter you need to set manually for turbo is shift=3.0". — [docs/en/INFERENCE.md:354-362](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md)
- [CODE] Il pipeline forza `guidance_scale=1.0` se `is_turbo_model()` (commento: evita doppia guida, rumore/NaN su fp16, issue #927). — [acestep/core/generation/handler/generate_music.py:309-319](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/generate_music.py)
- [CODE] `generate_audio` turbo logga "Turbo DiT ignores CFG params" se guidance_scale!=1, use_adg o cfg_interval non default: use_adg e cfg_interval_start/end sono inerti su turbo. — [acestep/models/turbo/modeling_acestep_v15_turbo.py:1907-1912](file:///home/drift/git/ACE-Step-1.5/acestep/models/turbo/modeling_acestep_v15_turbo.py)
- [CODE] Turbo: se `timesteps` non e' passato e `infer_steps>0` (sempre vero col default 8) lo schedule e' `linspace` con trasformazione shift `t'=shift*t/(1+(shift-1)t)`; quindi `shift` conta davvero (shift=3, 8 step = [1.0, .9545, .9, .833, .75, .643, .5, .3], identico a SHIFT_TIMESTEPS[3.0]). Gli schedule discreti 1/2/3 sono usati solo se infer_steps e' assente. Steps clampati a 20. — stesso file, blocco dopo `VALID_TIMESTEPS` (~1914-1990).
- [DOC contro CODE] `docs/en/API.md:~262` e `release_task_models.py:94` dicono che `shift` e' "Only effective for base models, not turbo"; il codice turbo sopra lo applica. Default HTTP `shift=3.0`, default Python `GenerationParams.shift=1.0` (non corretto per turbo). — [acestep/api/http/release_task_request_builder.py:83](file:///home/drift/git/ACE-Step-1.5/acestep/api/http/release_task_request_builder.py), [acestep/inference.py:151](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py), [acestep/api/http/release_task_models.py:92-94](file:///home/drift/git/ACE-Step-1.5/acestep/api/http/release_task_models.py)
- [DOC] Turbo distillato "joint on shift 1,2,3"; varianti `turbo-shift1` (dettagli ma semantica piu' debole), `turbo-shift3` (timbro piu' chiaro ma "dry"), `turbo-continuous` (sperimentale, shift 1-5). shift alto = piu' sforzo sui primi step = struttura/semantica piu' forte; shift basso = piu' dettaglio ma anche piu' rumore. — [docs/en/Tutorial.md:196-215](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [Paper] Distillazione "50 -> 8 step (Shift=3) without CFG", shift campionato da {1,2,3} durante la distillazione. — [arXiv 2602.00744](https://arxiv.org/html/2602.00744)
- [CODE] Base/sft: la guida e' APG, non CFG classico: `pred_cond + (gs-1)*diff_ortogonale`, momentum -0.75, `norm_threshold=2.5`, `eta=0` (componente parallela scartata). Con `use_adg=True` usa `adg_forward`. La guida e' attiva solo se `guidance_scale>1`. — [acestep/models/common/apg_guidance.py:33-56](file:///home/drift/git/ACE-Step-1.5/acestep/models/common/apg_guidance.py), [acestep/models/base/modeling_acestep_v15_base.py:1996,2054-2075](file:///home/drift/git/ACE-Step-1.5/acestep/models/base/modeling_acestep_v15_base.py)
- [CODE] `cfg_interval_start/end` confrontati direttamente con `t_curr` (1.0 -> 0.0): la guida e' applicata solo quando `start <= t <= end`; fuori intervallo usa `pred_cond` pura. Default 0-1 = guida su tutti gli step. Nessuna raccomandazione ufficiale diversa dal default. — [modeling_acestep_v15_base.py:2054-2075](file:///home/drift/git/ACE-Step-1.5/acestep/models/base/modeling_acestep_v15_base.py)
- [DOC] `use_adg`: "base model only. Improves quality at the cost of speed" (nessun dato quantitativo); "For best quality: base, steps 64+, use_adg=True, guidance 7-9, shift 3.0"; "speed: turbo, 8 step, ADG off, ode". — [docs/en/INFERENCE.md:374,1005-1025](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md)
- [DOC] `infer_method`: "ode" (Euler, deterministico, veloce, default) vs "sde" (stocastico, "may produce different results with variance"); Tutorial: sde "introduce randomness". [CODE] sde = predice x0 e re-inietta rumore a ogni step (aggiunge varianza, non c'e' evidenza che aumenti la coerenza). — [docs/en/INFERENCE.md:378](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md), [docs/en/Tutorial.md:884-888](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md), [turbo model:2150-2155](file:///home/drift/git/ACE-Step-1.5/acestep/models/turbo/modeling_acestep_v15_turbo.py)
- [DOC] `timesteps`: lista da 1.0 a 0.0, se presente sovrascrive `inference_steps` e `shift`. [CODE] su turbo ogni valore e' mappato al piu' vicino dei 20 timestep validi (max 20). — [docs/en/INFERENCE.md:379](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md), turbo model ~1930-1960
- [DOC] Sft: CFG + 50 step; "error accumulation, audio clarity may be slightly inferior to Turbo, but detail expression and semantic parsing will be better". Turbo = "Best balance of creativity and semantics, recommended first choice". — [docs/en/Tutorial.md:196-230](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC] Tabella README: turbo Quality "Very High"/Diversity Medium; sft Quality High/Diversity Medium; base Quality Medium/Diversity High; XL-sft/XL-turbo "Very High". — [README.md:258-272](file:///home/drift/git/ACE-Step-1.5/README.md)
- [DOC] Nota guida Tutorial: guidance "higher = more prompt adherence, but may overfit. Only Base model effective". — [docs/en/Tutorial.md:~845](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC, extra] DCW (correzione wavelet sampler-side, CVPR 2026): `dcw_enabled` default ON per turbo, OFF per non-turbo; default pure-DiT `double`, scaler 0.05 / high 0.02; con Think la Gradio usa 0.02 / 0.06 ("gain small"). Le route HTTP non espongono `dcw_*` e usano il default model-aware. Range usabile 0-0.1, sopra compaiono artefatti. — [docs/en/DCW.md:78-185](file:///home/drift/git/ACE-Step-1.5/docs/en/DCW.md)
- [COMM] Slide terze: guidance 1-15, valori bassi piu' creativi (non verificato). — [Google Slides](https://docs.google.com/presentation/d/1PjlqimpO2XUxUwTj8BbDNZV4y4hIRCow/htmlpresent)

### Inferences
- Per coerenza su turbo la leva reale e' `shift=3.0` + 8 step (match con la distillazione); cambiare steps oltre 8 o shift fuori {1,2,3} esce dal regime su cui turbo e' stato distillato (inferenza dal paper e dal codice, non provata da test).
- Chi non passa `shift` dal Python API su turbo ottiene 1.0 (schedule uniforme), cioe' piu' dettaglio/rumore e struttura piu' debole secondo la descrizione di shift dei docs. Va impostato esplicitamente se il client non usa HTTP.
- Il documento API/Pydantic che dice "shift ignorato su turbo" e' fuorviante; fidarsi del codice.
- Per aderenza al prompt su sft/base partire da guidance 7 (range 5-9); valori alti rischiano overfit (docs) e APG con norm_threshold limita comunque l'ampiezza.
- `use_adg`, `cfg_interval_*`, `sde`: nessun dato di coerenza; lasciare ai default.

### Gaps
- Nessun benchmark/ablation pubblico trovato su guidance_scale, shift, ADG, cfg_interval o ode/sde per coerenza strutturale; il paper non ha ablazioni CFG.
- Non verificato sperimentalmente se shift 3.0 vs 1.0 su turbo cambi la coerenza a 8 GB in pratica.
- Dettaglio righe turbo ~1914-1990 approssimato (non letto riga per riga).

## 2. LM 5Hz (0.6B/1.7B/4B): lm_temperature, lm_cfg_scale, top_p, top_k, repetition_penalty, use_cot_caption, use_cot_language, constrained_decoding, use_format

### Takeaway
Default ufficiali: temperature 0.85, cfg 2.0 (Python) o 2.5 (HTTP), top_p 0.9, top_k off. Per coerenza i docs suggeriscono solo temperatura piu' bassa (0.7-0.85). `lm_repetition_penalty` e' accettato dall'API HTTP ma, per il codice letto, non arriva al LM nel flusso text2music (resta 1.0).

### Cited Findings
- [CODE] Default Python: `lm_temperature=0.85, lm_cfg_scale=2.0, lm_top_k=0, lm_top_p=0.9, lm_negative_prompt="NO USER INPUT", use_cot_metas/caption/language=True, use_constrained_decoding=True`. — [acestep/inference.py:204-213](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py)
- [DOC/CODE] Default HTTP: `lm_cfg_scale=2.5`, temperature 0.85, top_p 0.9, `thinking` default **false** nell'API (true nella libreria Python). — [docs/en/API.md:142,226-231](file:///home/drift/git/ACE-Step-1.5/docs/en/API.md), [release_task_models.py:134-138](file:///home/drift/git/ACE-Step-1.5/acestep/api/http/release_task_models.py)
- [DOC] Tabella: temperature "higher = more random/creative, lower = more conservative/deterministic"; lm_cfg_scale "higher = more positive prompt adherence"; top_k 0 = off; top_p nucleus; constrained decoding "ensures correct output format"; use_cot_caption "let LM optimize your description"; use_cot_language "auto-detect vocal language". — [docs/en/Tutorial.md:854-866](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC] "For Consistency: use_random_seed=False, fixed seeds, keep lm_temperature lower (0.7-0.85)". Tipici: top_k 40-100, top_p 0.9-0.95. — [docs/en/INFERENCE.md:372-373,1026-1030](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md)
- [CODE] `lm_top_k` 0/None disabilita; `lm_top_p>=1.0` disabilita. — [acestep/inference.py:669-670](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py)
- [CODE] Due fasi: Fase 1 CoT (metadati, BPM/key/durata/caption/lingua) con **cfg_scale forzato a 1.0** (commento: cfg>1 distorce i logit durante il reasoning); Fase 2 genera i codici audio con `lm_cfg_scale` e prompt CoT incluso. Quindi lm_cfg_scale agisce solo sui codici (la struttura musicale), non sui metadati. Caption/lingua generati in fase 1 solo se `use_cot_caption`/`use_cot_language`; skip_genres sempre True. — [acestep/llm_inference.py:1383-1396,1480-1511](file:///home/drift/git/ACE-Step-1.5/acestep/llm_inference.py)
- [CODE] Fase 2: i codici sono limitati a `target_duration*5` (+10 token); il constrained decoder forza EOS alla lunghezza target; se duration non e' data usa la durata scelta dal CoT. Vocabolario codici vincolato a 0-63999. Constrained decoding = FSM che vincola formato metadati e lunghezza/EOS dei codici. — [llm_inference.py:279-282,1432-1445](file:///home/drift/git/ACE-Step-1.5/acestep/llm_inference.py), [acestep/constrained_logits_processor.py:13,515](file:///home/drift/git/ACE-Step-1.5/acestep/constrained_logits_processor.py)
- [CODE] Metadati forniti dall'utente (bpm, keyscale, timesignature, duration) vengono iniettati nel constrained decoding e vincono; l'LM riempie solo i mancanti. — [acestep/inference.py:668-708](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py), [docs/en/API.md:173-182](file:///home/drift/git/ACE-Step-1.5/docs/en/API.md)
- [CODE] `repetition_penalty`: `generate_with_stop_condition` ha il parametro (default 1.0) ma la chiamata in `generate_music` (inference.py:730-741) non lo passa; `lm_repetition_penalty` compare solo in `release_task_models.py:138` e nel builder (:92), non in `api/` oltre. Quindi nel flusso text2music e' di fatto 1.0. Verificato con grep; non ho eseguito la pipeline. — [acestep/inference.py:730-741](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py)
- [DOC/CODE] `use_format` (solo API): usa `format_sample()` per riscrivere/strutturare caption e lyrics prima della generazione, default false; forza l'uso dell'LM. — [docs/en/API.md:152](file:///home/drift/git/ACE-Step-1.5/docs/en/API.md), [acestep/api/llm_generation_inputs.py:70-87,149](file:///home/drift/git/ACE-Step-1.5/acestep/api/llm_generation_inputs.py)
- [DOC] Dimensione LM: stessi dati, differisce la capacita'. 0.6B memoria "Weak", composition "Medium", copy melody "Weak"; 1.7B Medium; 4B "Strong" su tutto. Raccomandazione: VRAM <8 GB -> No LM o 0.6B; 8-16 GB -> 1.7B (default); >16 GB -> 1.7B o 4B. — [README.md:277-283](file:///home/drift/git/ACE-Step-1.5/README.md), [docs/en/Tutorial.md:166-185](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC] Durata: 30-60 s e 2-4 min stabili; durate molto lunghe possono avere ripetizioni o problemi di struttura. BPM 60-180 stabile; chiavi comuni (C, G, D, Am, Em) stabili; 4/4 piu' affidabile; metadati che confliggono con la caption confondono il modello; non scrivere BPM/key nella caption ma nei campi dedicati. — [docs/en/Tutorial.md:658-700](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [Paper] LM = planner che emette CoT (BPM, key, durata, struttura) e poi codici 5 Hz; addestrato con GRPO a ricompensa PMI. SongEval Coherence 4.72 "tied-best". Nessuna discussione su temperatura/campionamento. — [arXiv 2602.00744](https://arxiv.org/html/2602.00744)
- [COMM] fal.ai (host terzo) usa `lm_cfg_scale` default 1 e avvisa che >1 attiva CFG lento (~10x), thinking = 2x costo. — [fal.ai llms.txt](https://fal.ai/models/fal-ai/ace-step-1.5/llms.txt) (risultato di ricerca, pagina non aperta in dettaglio)
- [COMM] Issue ComfyUI #12375: regressione di qualita' tra ComfyUI 0.12.2 e 0.12.3 con i default cfg 2, temp 0.85, top_p 0.9, top_k 0; riproducibile su piu' seed, peggiore su tracce minimali. Non specifica la causa. — [ComfyUI #12375](https://github.com/Comfy-Org/ComfyUI/issues/12375)

### Inferences
- Per coerenza: temperatura 0.7-0.85 (fascia dei docs), top_p 0.9, top_k 0 o 40-50, cfg 2.0-2.5 (default); alzare cfg oltre ~3 non e' supportato da alcuna evidenza e raddoppia il costo (CFG LM = batch condizionato + incondizionato; su backend pt piu' lento, non misurato).
- `lm_cfg_scale` non puo' correggere errori nei metadati (fase 1 a cfg 1.0): se BPM/key/durata sono sbagliati, fornirli esplicitamente (vincono sull'LM) e' piu' efficace.
- `use_cot_caption=True` riscrive la caption: puo' migliorare aderenza (LM ha world knowledge) ma puo' anche allontanarsi dall'intento; disattivarlo (con caption gia' precisa) e' coerente con "decide you" ma non e' testato. `use_cot_language` utile solo se vocal_language non e' dato.
- Tenere `use_constrained_decoding=True`: evita output malformato e garantisce lunghezza codici = durata.
- Repetition penalty: non toccare, tanto non e' collegata (da riverificare se il bot usa un percorso diverso).

### Gaps
- Nessun test ufficiale di temperatura/top_p/cfg sulla coerenza; nessun consiglio documentato per "coerenza vs creativita'" oltre 0.7-0.85.
- Non verificato che `lm_repetition_penalty` sia davvero inutilizzato in ogni percorso (solo grep).
- Costo reale di cfg>1 su backend pt con 8 GB non misurato.
- Non ho aperto pagina/issue di GitHub ACE-Step con segnalazioni di drift strutturale; la ricerca non ne ha restituite.

## 3. thinking=true (codici audio generati dall'LM) vs solo DiT

### Takeaway
I docs raccomandano `thinking=true` per qualita' migliore e aderenza al prompt, ma non c'e' confronto quantitativo (ne' nel paper ne' nei docs). Il costo e' tempo/VRAM; i trade-off documentati sono velocita' e controllo diretto.

### Cited Findings
- [DOC] `thinking=true`: l'LM genera `audio_code_string` e il DiT gira con i codici "for enhanced music quality"; `thinking=false`: il DiT gira in text2music puro e ignora qualunque codice fornito. L'LM e' saltato per cover/repaint/extract. — [docs/en/API.md:160-169](file:///home/drift/git/ACE-Step-1.5/docs/en/API.md)
- [DOC] Best practices: "Use thinking=true for best quality results"; troubleshooting "results don't match prompt -> make caption more specific, increase guidance_scale, enable LM refinement (thinking=True)". — [docs/en/API.md:862](file:///home/drift/git/ACE-Step-1.5/docs/en/API.md), [docs/en/INFERENCE.md:1130-1131](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md)
- [DOC] Tutorial: i codici semantici contengono "composition melody, orchestration, and some timbre information"; l'LM e' opzionale; thinking spento se sai gia' cosa vuoi (piu' veloce e controllo diretto). I codici LM funzionano anche con sft. — [docs/en/Tutorial.md:131-150](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md), [docs/en/ace_step_musicians_guide.md:564](file:///home/drift/git/ACE-Step-1.5/docs/en/ace_step_musicians_guide.md)
- [DOC] Benchmark: "With thinking (better quality, slower)"; "Thinking significantly increases LLM time but may improve generation quality" (formulazione hedged). — [docs/en/BENCHMARK.md:349-356,428](file:///home/drift/git/ACE-Step-1.5/docs/en/BENCHMARK.md)
- [Paper] Il codec/tokenizer 5 Hz (~64k codici) funge da "structural Source Latent"; nessuna ablazione LM-vs-DiT-only trovata. — [arXiv 2602.00744](https://arxiv.org/html/2602.00744)
- [CODE] DCW doc: con Think "l'overall DCW gain e' piccolo" (i codici LM riducono il margine di miglioramento del sampler): indizio indiretto che i codici gia' stabilizzano il risultato. — [docs/en/DCW.md:150-156](file:///home/drift/git/ACE-Step-1.5/docs/en/DCW.md)
- [DOC] HF model card: tabelle senza confronto qualita' con/senza LM. — [HF Ace-Step1.5](https://huggingface.co/ACE-Step/Ace-Step1.5)

### Inferences
- Il meccanismo (codici = piano compositivo a 5 Hz che il DiT segue) suggerisce piu' coerenza strutturale a lungo raggio con thinking=true, ma e' un'inferenza dall'architettura, non una misura.
- Trade-off: tempo LM, VRAM extra per il modello LM; con 8 GB la scelta pratica e' 0.6B (memoria/knowledge "Weak") oppure 1.7B se entra; offload necessario.

### Gaps
- Nessun dato quantitativo pubblico su coerenza con vs senza codici LM; nessuna segnalazione trovata di peggioramenti (es. sovra-vincolo) da thinking.

## 4. Seed e batch_size: candidati multipli e selezione

### Takeaway
Gli autori raccomandano esplicitamente di generare piu' candidati (batch 2/4/8) e scegliere, usando il punteggio automatico "DiT Lyrics Alignment" come filtro (test-time scaling); il seed fissa il rumore iniziale e serve a isolare l'effetto dei parametri.

### Cited Findings
- [DOC] "Tuning factors and random factors sometimes have comparable influence": per valutare parametri fissare `seed`; per esplorare lasciarlo variare. — [docs/en/Tutorial.md:868-874,918-921](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC] Workflow raccomandato: batch grande (2,4,8), scoring automatico, selezione dei migliori; "DiT Lyrics Alignment Score" e' lo score preferito dall'autore, correla con accuratezza dei testi; AutoGen genera batch successivi con nuovi seed. — [docs/en/Tutorial.md:925-951](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [DOC] Musicians guide: "Always generate 2-4 versions at once. Picking the best from several options...". Repaint per correggere solo la sezione difettosa. — [docs/en/ace_step_musicians_guide.md:555-562](file:///home/drift/git/ACE-Step-1.5/docs/en/ace_step_musicians_guide.md)
- [DOC] `batch_size` default 2 (1-8); HTTP max 8; `seeds` lista, completata con casuali; `use_random_seed=False` per riproducibilita'; `lm_batch_chunk_size` 8. — [docs/en/INFERENCE.md:~405-415](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md), [docs/en/API.md:203-204](file:///home/drift/git/ACE-Step-1.5/docs/en/API.md)
- [CODE] Il seed controlla il rumore DiT (`prepare_noise`) e viene passato per item anche all'LM (`chunk_seeds`). Con `lm_temperature>0` l'LM campiona comunque (varia per item). — [acestep/inference.py:~700-740](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py), [docs/en/Tutorial.md:880-888](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [CODE] In batch >1 con thinking il prompt incondizionato CFG dell'LM usa CoT vuoto (differisce dalla modalita' singola). — [acestep/llm_inference.py:383-390](file:///home/drift/git/ACE-Step-1.5/acestep/llm_inference.py)

### Inferences
- Il seed pesa quanto i parametri (dichiarazione degli autori): su 8 GB, batch 2-4 con selezione (anche solo ascolto) e' il modo piu' economico per scartare derive strutturali, piu' efficace del tuning fine.
- La metrica di allineamento testo-audio e' uno strumento di selezione, non di coerenza musicale in senso lato (non misura off-key).

### Gaps
- Non verificato dove sia esposto lo score di allineamento via API HTTP e se sia usabile dal bot senza Gradio.
- Nessun dato su quanti candidati servano per ridurre la probabilita' di una sezione incoerente.

## 5. dtype (bf16 / fp16 / fp32), in particolare ROCm

### Takeaway
Su ROCm il codice usa **float32 per default** per evitare segfault di kernel bf16/fp16 incompleti (es. Strix Halo); override con `ACESTEP_ROCM_DTYPE=bfloat16|float16`. Nessun dato di qualita' sonora per dtype; i soli rischi documentati sono NaN/overflow in fp16 e instabilita' dei kernel.

### Cited Findings
- [CODE] ROCm/HIP: `_resolve_rocm_dtype()` default `float32`; env `ACESTEP_ROCM_DTYPE` in {float32, float16, bfloat16}; valore sconosciuto -> float32. Commit `0685c29` "use float32 by default on ROCm to prevent segfault during model load (#771)". — [acestep/core/generation/handler/init_service_orchestrator.py:25-40,84-90](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/init_service_orchestrator.py)
- [CODE] CUDA non-ROCm: bf16 se compute capability >= 8, altrimenti fp16 con attention "eager" per evitare overflow softmax SDPA (NaN/Inf, issue #924/#927). — [init_service_orchestrator.py:91-99](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/init_service_orchestrator.py), [init_service_loader.py:146-155](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/init_service_loader.py)
- [CODE] Messaggio di errore in decode: "Float16 overflow on pre-Ampere GPU - set ACESTEP_DTYPE=float32" (nome variabile `ACESTEP_DTYPE` non trovato altrove nel codice: probabile testo obsoleto). — [generate_music_decode.py:79](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/generate_music_decode.py)
- [CODE] LM `pt`: dtype default bf16 su cuda/xpu (ROCm si presenta come "cuda"), float32 su CPU/MPS; override esplicito possibile (`llm_inference.py:570-583`). L'LM non segue `ACESTEP_ROCM_DTYPE` (verificato solo per il DiT). — [acestep/llm_inference.py:570-583](file:///home/drift/git/ACE-Step-1.5/acestep/llm_inference.py)
- [CODE] Turbo forza guidance 1.0 anche "to avoid NaN/Inf on float16". — [generate_music.py:309-312](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/generate_music.py)
- [DOC] Docs ROCm: richiedono `HSA_OVERRIDE_GFX_VERSION` per RX 6000/7000/9000; nessuna indicazione di dtype o qualita'. — [docs/en/GPU_TROUBLESHOOTING.md:17-52](file:///home/drift/git/ACE-Step-1.5/docs/en/GPU_TROUBLESHOOTING.md)
- [DOC] Pesi XL ~9 GB in bf16. — [README.md:266](file:///home/drift/git/ACE-Step-1.5/README.md)

### Inferences
- fp32 e' il riferimento numerico piu' sicuro ma il DiT 2B in fp32 occupa il doppio di VRAM (~9.4 GB stimati dai ~4.7 GB di bf16 citati in Tutorial.md:~175: non entra in 8 GB senza offload). Ipotesi: con 8 GB si usa bf16/fp16 via `ACESTEP_ROCM_DTYPE` + offload, a rischio segfault/NaN su alcune GPU; il rischio di degradazione di qualita' in bf16 non e' documentato. Da testare empiricamente.
- bf16 ha range dinamico come fp32 (meno overflow), fp16 e' il piu' a rischio di NaN (conoscenza generale, non fonte ACE-Step).

### Gaps
- Nessun confronto di qualita'/coerenza tra dtype per ACE-Step trovato (docs, paper, HF).
- Non so quale GPU AMD specifica e se bf16 sia stabile su quella architettura; non testato.
- Non verificato se la variabile ambiente influisce sul VAE e sul LM `pt` su ROCm.
