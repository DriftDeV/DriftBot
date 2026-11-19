# Prompt (caption) e testi (lyrics) per ACE-Step 1.5

Local repo = /home/drift/git/ACE-Step-1.5 (abbrev. REPO). Label: [DOC] = documentazione ufficiale del repo, [PAPER] = arXiv, [CODE] = verificato nel sorgente, [EMP] = misura mia sugli esempi ufficiali, [COMM] = blog/community di terze parti (aneddotico).

## 1. Formato della caption: cosa funziona, cosa confonde

### Takeaway
La caption e' l'input piu' importante; accetta tag separati da virgola o prosa. Funziona meglio specifica e multi-dimensionale (genere + mood + strumenti + timbro + voce + produzione) e senza contraddizioni. BPM/key/tempo vanno nei campi dedicati, non nella caption. Gli esempi ufficiali sono prosa descrittiva (mediana ~220 caratteri, max ~720), senza BPM/key dentro.

### Cited Findings
- "Caption is the most important factor affecting generated music"; accetta stile semplice, tag a virgola o descrizioni complesse in linguaggio naturale; il training copre vari formati [DOC] — [REPO/docs/en/Tutorial.md](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- Dimensioni consigliate: genere, emozione, strumenti, texture timbrica (warm, crisp, airy, punchy), era (80s synth-pop), produzione (lo-fi, studio-polished), voce (female vocal, breathy, raspy, choir), velocita'/ritmo, hint di struttura (building intro, fade-out) [DOC] — [Tutorial.md](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md), [songwriting SKILL.md](file:///home/drift/git/ACE-Step-1.5/.claude/skills/acestep-songwriting/SKILL.md)
- Principi ufficiali: specifico > vago ("sad piano ballad with female breathy vocal" > "a sad song"); combinare piu' dimensioni; riferimenti stilistici; granularita' = liberta' (meno dettaglio = piu' casualita'); non cercare la perfezione, iterare [DOC] — Tutorial.md
- Evitare parole in conflitto (es. "classical strings" + "hardcore metal"): output degradato; con `thinking` attivo l'LM generalizza la caption peggio del DiT [DOC] — Tutorial.md
- Rimedi ufficiali ai conflitti: (a) ripetizione rinforzante degli elementi da privilegiare; (b) "conflitto -> evoluzione": trasformare lo scontro di stili in sequenza temporale ("start with soft strings, middle becomes noisy metal rock, end turns to hip-hop") [DOC] — Tutorial.md
- Raccomandazione esplicita: non scrivere tempo/BPM/key nella caption; usare `bpm`, `keyscale`, `timesignature` [DOC] — Tutorial.md, songwriting SKILL.md. Verificato negli esempi: 0/200 caption in `examples/text2music/*.json` citano bpm o tonalita' [EMP]
- Esempi ufficiali: caption in prosa, 1-4 frasi, tipicamente descrivono strumenti, timbro della voce, trattamento (es. "male vocal with noticeable auto-tune and spacious reverb"), evoluzione dell'arrangiamento (breakdown, outro filtrato) e mood finale — [REPO/examples/text2music/example_01.json, example_02.json, example_03.json](file:///home/drift/git/ACE-Step-1.5/examples/text2music/)
- Limite caption: "< 512 caratteri" nel docstring/API [DOC] — [REPO/docs/en/INFERENCE.md](file:///home/drift/git/ACE-Step-1.5/docs/en/INFERENCE.md) (riga ~338), [REPO/acestep/inference.py](file:///home/drift/git/ACE-Step-1.5/acestep/inference.py) riga 61. Ma il testo caption+metas e' tokenizzato con `max_length=256` token e troncato [CODE] — [conditioning_text.py](file:///home/drift/git/ACE-Step-1.5/acestep/core/generation/handler/conditioning_text.py). Alcuni esempi ufficiali superano i 512 caratteri (max ~724) [EMP]
- Struttura del prompt DiT: `# Instruction / # Caption / # Metas` (BPM, key, time sig, duration vanno nel blocco Metas), poi lyrics come `# Languages\n{lang}\n\n# Lyric\n{lyrics}` [CODE] — [constants.py](file:///home/drift/git/ACE-Step-1.5/acestep/constants.py) (SFT_GEN_PROMPT), conditioning_text.py (`_format_lyrics`)
- Vocabolario di generi usato dal sistema: `acestep/genres_vocab.txt` contiene voci come "80s Italian pop-rock", "80s Italian power ballad", "60s Italian pop", "Bossa Nova, Italian ballad, cinematic", "Italian rap, trap" [CODE] — [genres_vocab.txt](file:///home/drift/git/ACE-Step-1.5/acestep/genres_vocab.txt)
- Il formato `format`/CoT riscrive e espande la caption; LM usa istruzione "Expand/Format the user's input into a more detailed and specific musical description" [CODE] — constants.py; il paper dice che il training usa caption dense mentre gli utenti scrivono prompt scarni, colmato da query rewriting [PAPER] — [arXiv 2602.00744](https://arxiv.org/html/2602.00744v1)
- [COMM] Guida deAPI: lista di tag a virgola di ~5-12 voci, oltre 15 si diluiscono; ordine genere -> mood -> 2-3 strumenti concreti -> voce -> produzione; "grand piano" meglio di "piano"; massimo un genere primario + un modificatore; 5+ generi di nicchia = rumore. Lo stesso blog consiglia di mettere il BPM anche nei tag, in contrasto con la doc ufficiale — [deAPI blog](https://deapi.ai/blog/ace-step-1-5-prompting-guide-how-to-write-tags-structure-lyrics-and-generate-better-music); contraddetto da [Tutorial.md](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- [COMM] Lo stesso blog avverte che tag `no vocals` + testo nei lyrics puo' produrre vocalizzi senza parole — deAPI blog
- Modelli: turbo (8 step, no CFG, default), sft (50 step, CFG, migliore su dettaglio e parsing semantico), base (CFG, task extra). SFT/base permettono di regolare l'aderenza al prompt con CFG; turbo non usa CFG [DOC] — Tutorial.md

### Inferences
- Per un bot: costruire la caption in prosa breve o tag, 150-300 caratteri, una sola direzione di genere, voce esplicita (gender + timbro), 2-3 strumenti, produzione; niente numeri di BPM/key.
- Tenere i primi ~256 token utili: mettere genere/voce/strumenti all'inizio della caption, perche' il troncamento colpisce la coda (caption + metas insieme).
- Se servono due stili, esprimerli come evoluzione temporale e non come miscela.
- "Italian" e' presente nel vocabolario generi (es. "Italian pop-rock", "Italian ballad"): usarlo come modificatore del genere e' coerente con cio' che il sistema ha visto.

### Gaps
- Nessuna lista ufficiale di tag di produzione che il modello "riconosce"; la guida resta euristica. Nessun test controllato su quali frasi causano contraddizioni oltre agli esempi di conflitto stilistico.
- Non ho letto il contenuto dei thread GitHub Discussions/Issues (la ricerca non li ha indicizzati); nessuna evidenza da Reddit/Discord.

## 2. Struttura dei lyrics: tag, lunghezza righe, sezioni vs durata

### Takeaway
Lyrics = "copione temporale": testo + tag di sezione + hint vocali/energetici. Righe di 6-10 sillabe (ufficiale; community 4-8), sezioni separate da riga vuota, tag corti (un solo modificatore) coerenti con la caption. Dagli esempi ufficiali: mediana ~8,4 s di durata per riga cantata (quartili 6,9-10,0), durata 124-240 s con 4-8 righe per sezione tipica. Non esiste regola ufficiale sillabe/secondo ne' comportamento documentato per lyrics troppo lunghi/corti.

### Cited Findings
- Tag base ufficiali: `[Intro] [Verse]/[Verse 1] [Pre-Chorus] [Chorus] [Bridge] [Outro]`, dinamici `[Build] [Drop] [Breakdown]`, strumentali `[Instrumental] [Guitar Solo] [Piano Interlude]`, speciali `[Fade Out] [Silence]` [DOC] — [Tutorial.md](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md)
- Combinazione con trattino: `[Chorus - anthemic]`, `[Bridge - whispered]`; NON impilare molti modificatori (`[Chorus - anthemic - stacked harmonies - high energy - powerful - epic]`): rischio che il modello canti il testo del tag o si confonda. Regola: tag concisi, stile complesso nella caption [DOC] — Tutorial.md
- Tag vocali (`[raspy vocal] [whispered] [falsetto] [powerful belting] [spoken word] [harmonies] [call and response] [ad-lib]`) e di energia (`[high energy] [low energy] [building energy] [explosive] [melancholic] [euphoric] [dreamy] [aggressive]`) [DOC] — Tutorial.md
- Coerenza caption-lyrics: "Models are not good at resolving conflicts". Checklist: strumenti caption <-> tag strumentali; emozione <-> tag di energia; voce <-> tag vocali. Esempio negativo: caption "violin solo, classical, chamber" + `[Guitar Solo - electric - distorted]` [DOC] — Tutorial.md
- Sillabe: 6-10 per riga; righe nella stessa posizione con conteggio simile (±1-2); il modello allinea sillabe ai beat, una riga da 6 e una da 14 rendono il ritmo strano [DOC] — Tutorial.md, songwriting SKILL.md
- Maiuscolo = piu' intensita' ("WE ARE THE CHAMPIONS!"); parentesi = voci di sottofondo/cori ("We rise together (together)"); vocali allungate ("Feeeling") instabili; righe vuote tra sezioni [DOC] — Tutorial.md
- Segnali "AI-flavored" da evitare: accumulo di aggettivi, rime caotiche, confini di sezione sfumati (contenuto che "fluisce" nel chorus), righe troppo lunghe per un respiro, metafore miste; una metafora per canzone [DOC] — Tutorial.md
- Strumentale: `[Instrumental]` oppure solo tag di sezione descrittivi (`[Intro - ambient] [Main Theme - piano] ...`) [DOC] — Tutorial.md
- Il tokenizer dei lyrics tronca a `max_length=2048` token; limite documentato 4096 caratteri [CODE/DOC] — conditioning_text.py, INFERENCE.md/inference.py
- Fatto sugli esempi ufficiali (200 file `examples/text2music`, 195 con lyrics cantati, lingue: en 52, zh 51, ja 31, ko 21, fr 19, de 13, es 5, pl 3, hu 2, pt/he/ms 1; nessun italiano) [EMP]: durate 124-240 s (mediana 210); secondi per riga di testo cantato mediana 8,4 (Q1 6,9, Q3 10,0); sezioni piu' frequenti Chorus, Intro, Verse 1/2, Outro, Bridge, Pre-Chorus; tag con modificatore tipo `[Intro - Synth Brass Fanfare]`, `[Instrumental Break - Synth Brass Melody]`, `[Outro - Instrumental with Synth Brass Melody]`; Verse in blocchi di 4-10 righe, Chorus 4 righe; ogni esempio ha anche bpm, keyscale, timesignature, language, duration, think — [REPO/examples/text2music/](file:///home/drift/git/ACE-Step-1.5/examples/text2music/)
- Esempio completo ufficiale (caption "female vocal, piano ballad, emotional, intimate atmosphere, strings, building to powerful chorus"): Intro-piano, Verse 1 (4 righe), Pre-Chorus (2), Chorus-powerful (4), Verse 2 (4), Bridge-whispered (2), Final Chorus (con riga in maiuscolo), Outro-fade out — Tutorial.md
- Stime di durata del songwriting skill: intro/outro 5-10 s, sezioni strumentali 5-15 s; 2 strofe + 2 ritornelli = 120-150 s minimo; con bridge 180-240 s; canzone completa con intro/outro 210-270 s; BPM lento = serve piu' durata per gli stessi lyrics, veloce = piu' testo ma serve respiro; "in caso di dubbio stimare piu' lungo, una canzone troppo corta suona frettolosa" [DOC] — [songwriting SKILL.md](file:///home/drift/git/ACE-Step-1.5/.claude/skills/acestep-songwriting/SKILL.md)
- Lo skill dell'API: passare i lyrics COMPLETI, mai troncati, altrimenti "incomplete or incoherent songs" [DOC] — [REPO/.claude/skills/acestep/SKILL.md](file:///home/drift/git/ACE-Step-1.5/.claude/skills/acestep/SKILL.md)
- Con duration <=0 o None "the model chooses automatically based on lyrics length"; per canzoni con lyrics l'auto-detect e' raccomandato [DOC] — INFERENCE.md righe 350 e 1040
- [COMM] deAPI: marker minuscoli (`[intro] [verse] [pre-chorus] [chorus] [bridge] [inst] [build-up] [drop] [breakdown] [outro]`); marker senza testo = passaggio strumentale ma `[chorus]` vuoto produce silenzio non hook; righe 4-8 sillabe, 12+ rompono il ritmo; ripetere il chorus aiuta la melodia; rime AABB/ABAB non obbligatorie — [deAPI blog](https://deapi.ai/blog/ace-step-1-5-prompting-guide-how-to-write-tags-structure-lyrics-and-generate-better-music)
- Score ufficiale utile per filtrare: "DiT Lyrics Alignment Score" (allineamento testo/audio), consigliato con batch + AutoGen [DOC] — Tutorial.md; nel paper Lyric Align 26,3 vs 34,2 di Suno-v5 (tabella 1) e il lavoro futuro cita "refine precise lyric alignment" [PAPER] — [arXiv](https://arxiv.org/html/2602.00744v1)

### Inferences
- Regola pratica derivata dagli esempi [EMP]: righe cantate ~ durata / 8 (±2); con 180 s => ~18-26 righe, 210 s => ~22-30. Meno righe lascia spazio strumentale/ripetizioni, piu' righe costringe a cantare in fretta. Questa e' una mia stima empirica, non una regola ufficiale.
- Lyrics troppo lunghi per la durata: probabile compressione/ritmo affrettato o testo non cantato (dedotto da "estimate longer" e dalla alignment score), ma nessuna fonte lo descrive come comportamento garantito. Lyrics troppo corti: spazio riempito da strumentale/ripetizioni; per evitare buchi aggiungere tag strumentali espliciti.
- Sezioni vs durata (dagli esempi): 2-3 strofe + chorus ripetuto + bridge + intro/outro per 180-240 s; sotto i ~90 s limitarsi a un verse + chorus.
- Per la coerenza: ripetere il chorus identico (copia letterale), un solo modificatore per tag, nessun tag in conflitto con la caption.

### Gaps
- Nessuna documentazione sul comportamento con lyrics sovradimensionati o troppo brevi; nessun benchmark sillabe/secondo.
- Discrepanza sillabe: 6-10 (ufficiale) vs 4-8 (deAPI), non risolta.
- Se i tag lowercase/uppercase facciano differenza non e' documentato (la doc ufficiale usa Title Case, deAPI minuscolo).

## 3. Metadata espliciti (bpm, key, time signature, language): quando fissarli

### Takeaway
Sono guida, non comandi: ancoraggi da cui il modello campiona (120 puo' diventare 118-122). Di default l'LM (thinking) li inferisce; fissarli a mano quando serve tempo/tonalita'/metro specifico o per coerenza tra take. Evitare conflitti tra metadata manuali e caption.

### Cited Findings
- Con `thinking`/`use_cot_metas` l'LM inferisce BPM, key, time signature, durata e lingua da caption+lyrics; il CoT esce in YAML prima dei codici (include "BPM, key, duration, and structure") [DOC/PAPER] — Tutorial.md; [arXiv](https://arxiv.org/html/2602.00744v1)
- Range: BPM 30-300 (comuni 60-180 stabili, estremi instabili), lento 60-80, medio 90-120, veloce 130-180; key comuni (C, G, D, Am, Em) stabili, rare ignorate o spostate; time sig 4/4 piu' affidabile, 3/4 e 6/8 di solito ok, 5/4 e 7/8 variabili [DOC] — Tutorial.md
- "Il modello non esegue mecc. bpm=120 ma lo usa come punto di ancoraggio" [DOC] — Tutorial.md
- Quando impostare a mano: tempo preciso -> bpm; valzer -> timesignature=3/4; combaciare altro materiale -> bpm+duration; colore tonale -> keyscale; altrimenti lasciare all'LM [DOC] — Tutorial.md, songwriting SKILL.md
- Avvertenza: metadata manuali in conflitto con la caption (caption "slow ballad" + bpm=160) confondono il modello [DOC] — Tutorial.md
- Formato keyscale valido: nota A-G + accidentale ('', #, b, unicode) + "major"/"minor" (es. "F# minor", "B♭ major") [CODE] — [constants.py](file:///home/drift/git/ACE-Step-1.5/acestep/constants.py)
- `vocal_language`: codice ISO 639-1, "unknown" = auto-detect; la doc dice "LM usually auto-detects from lyrics" [DOC] — INFERENCE.md riga 349. La lingua entra nel prompt dei lyrics come `# Languages\n{lang}` [CODE] — conditioning_text.py. `it` e' in VALID_LANGUAGES; cli.py e api/server_utils.py mappano "italian"/"italiano" -> "it" [CODE]
- Le istruzioni per le lingue possono essere forzate: `format_sample` accetta `user_metadata` per vincolare bpm/duration/keyscale/timesignature/language [DOC] — INFERENCE.md riga 744
- Tutti gli esempi ufficiali (200/200) impostano bpm, keyscale, timesignature, duration e language insieme a `think: true` [EMP] — examples/text2music
- Task cover/repaint/extract saltano automaticamente l'LM [DOC] — INFERENCE.md
- Per la ripetibilita': seed fisso (use_random_seed=False), lm_temperature piu' bassa 0,7-0,85; per la diversita' 0,9-1,1 [DOC] — INFERENCE.md (sezione Best Practices, "For Consistency"). Default lm_temperature 0,85, lm_cfg_scale 2,0 [DOC] — Tutorial.md
- Il blog [COMM] okmiku: il selettore lingua non e' auto-rilevato nell'interfaccia analizzata, va impostato; picker non coerente con la scrittura dei lyrics = "gibberish"; modalita' "Instrumental / Auto" salta la pipeline vocale — [okmiku](https://okmiku.com/blog/ace-step-vocal-language)

### Inferences
- Per un bot Discord con output deterministico: impostare sempre `vocal_language="it"` per testi italiani invece di "unknown"; fissare `bpm`, `timesignature` (4/4) e `keyscale` quando la richiesta li implica, lasciare all'LM quando l'utente non specifica.
- Se si fissano i metadata, derivarli dalla stessa fonte della caption (stesso mood: ballata lenta -> bpm 60-80) per evitare il conflitto documentato.
- Fissare il seed solo per debug; per produzione generare batch di 2-4 e scegliere per Lyrics Alignment Score.

### Gaps
- Non c'e' misura di quanto il bpm manuale venga rispettato (deviazione tipica) ne' effetto sulla coerenza tra sezioni.
- Non verificato se l'LM sovrascrive i metadata manuali quando thinking e' attivo (la doc parla di "constrain" via user_metadata per format_sample, non per generate).

## 4. Durata migliore e cosa degrada all'aumentare

### Takeaway
Range supportato 10-600 s. Doc ufficiale: 30-60 s e 2-4 min stabili; durate molto lunghe possono avere ripetizioni o problemi di struttura. Esempi ufficiali con lyrics stanno a 124-240 s (mediana 210). Per qualita' e coerenza il target pratico e' 120-240 s.

### Cited Findings
- DURATION_MIN=10, DURATION_MAX=600 [CODE] — [constants.py](file:///home/drift/git/ACE-Step-1.5/acestep/constants.py)
- "Short songs (30-60s) and medium length (2-4min) are stable; very long generation may have repetition or structure issues" [DOC] — Tutorial.md
- Guideline: strumentale 30-180 s; con lyrics lasciare auto (duration=-1); clip brevi minimo 10-20 s; massimo 600 s [DOC] — INFERENCE.md sezione "Duration Guidelines"
- Il paper attribuisce la coerenza a lungo raggio ai layer DiT alterni sliding-window / global GQA "to maintain long-term rhythmic and melodic consistency"; 240 s generati in ~1 s su A100 [PAPER] — [arXiv](https://arxiv.org/html/2602.00744v1). Il riferimento timbrico usa finestre fisse di 30 s con loop padding [PAPER]
- Esempi ufficiali con lyrics: 124-240 s [EMP] — examples/text2music
- Estensione: tramite Repaint (3-90 s per operazione) si puo' continuare/estendere e correggere sezioni locali, "infinite duration" a segmenti [DOC] — Tutorial.md
- Dimensione LM: 0.6B memoria debole, 1.7B media, 4B forte; modelli piu' grandi meglio su stili coda lunga e memoria [DOC] — Tutorial.md
- [COMM] deAPI: i turbo piccoli tendono a perdere coerenza oltre ~3 min, XL turbo regge meglio i 200 s+ — [deAPI blog](https://deapi.ai/blog/ace-step-1-5-prompting-guide-how-to-write-tags-structure-lyrics-and-generate-better-music) (le sigle di parametri di quel blog non coincidono con la doc del repo: trattare con cautela)
- XL (4B DiT) stessa interfaccia, qualita' migliore, richiede piu' VRAM (min ~12 GB con offload) [DOC] — Tutorial.md

### Inferences
- Per massimizzare la coerenza con lyrics: 150-210 s, struttura intro/verse/chorus/verse/chorus/bridge/chorus/outro con lyrics ricalibrati (vedi sez. 2). Sopra ~4 min aumenta il rischio di ripetizioni; meglio generare 2-3 min e, se serve, estendere via repaint.
- Se i lyrics sono definiti, passare duration esplicita calcolata dalle sezioni oppure -1 e lasciare scegliere all'LM (doc raccomanda auto con lyrics).

### Gaps
- Nessun dato quantitativo su quale degrado compaia per durata (derive di tonalita', dimenticanza del testo, ripetizioni del chorus) ne' in che punto.
- Non ho trovato issue GitHub specifiche sulla durata.

## 5. Lyrics non inglesi e italiano: qualita' e mitigazioni

### Takeaway
Il repo e il paper dichiarano 50+ lingue; `it` e' una lingua valida. Non ci sono esempi ufficiali in italiano ne' benchmark per lingua. Fonti community collocano l'italiano in un tier "solido" (competente, fonetica riconoscibile, servono 1-2 accorgimenti). Mitigazioni: impostare esplicitamente la lingua, scrivere in alfabeto nativo (nessuna romanizzazione per l'italiano), righe corte, generare batch e filtrare per lyrics alignment.

### Cited Findings
- 50+ lingue, includendo l'italiano; "You can even mix languages within a single song" [DOC] — [REPO/docs/en/ace_step_musicians_guide.md](file:///home/drift/git/ACE-Step-1.5/docs/en/ace_step_musicians_guide.md) (sez. Languages), [README.md](file:///home/drift/git/ACE-Step-1.5/README.md); Diffusers docs listano l'italiano — [Diffusers docs](https://huggingface.co/docs/diffusers/v0.39.0/api/pipelines/ace_step)
- Codici validi in `VALID_LANGUAGES` includono `it`; l'API/CLI mappano "italian"/"italiano" a `it` [CODE] — constants.py, acestep/api/server_utils.py, cli.py
- Distribuzione lingue negli esempi ufficiali: nessun esempio `it`; lingue europee presenti: en, fr (19), de (13), es (5), pl, hu, pt [EMP]. Gli esempi francesi/spagnoli (es. [example_02.json](file:///home/drift/git/ACE-Step-1.5/examples/text2music/example_02.json), [example_03.json](file:///home/drift/git/ACE-Step-1.5/examples/text2music/example_03.json)) sono utili come modello di struttura per lingue romanze
- Paper: lyrics non latini romanizzati in rappresentazioni fonemiche per il 50% dei dati di training (condivide rappresentazioni fonologiche tra lingue); nessun risultato per lingua; futuro: "broader language support" e "refine precise lyric alignment" [PAPER] — [arXiv](https://arxiv.org/html/2602.00744v1)
- Il paper non descrive tag di lingua nei lyrics; il repo passa la lingua come header `# Languages` [CODE]
- [COMM] okmiku: italiano in "Solid tier (use with one or two prompt tweaks)" con coreano, francese, tedesco, portoghese, hindi: "competent results. Phonetics are recognizable"; consigli di tier: abbassare leggermente il BPM o aumentare gli step sul Base; impostare esplicitamente il language picker; scrivere nella scrittura nativa (la traslitterazione da' risultati scarsi); nessuna distinzione regionale; per lingue basse correggere in post o ri-registrare — [okmiku](https://okmiku.com/blog/ace-step-vocal-language). Una seconda recensione dello stesso sito: allineamento lyrics piu' debole di Suno in tutte le lingue — [okmiku review](https://okmiku.com/blog/ace-step-v1-5-review)
- [COMM] deAPI: mettere marker di lingua (`[en]`, `[ja]`) all'inizio della sezione e non a meta' riga; elenca `it` tra le lingue migliori; senza marker su testo non inglese si rischia fonetica inglese — [deAPI blog](https://deapi.ai/blog/ace-step-1-5-prompting-guide-how-to-write-tags-structure-lyrics-and-generate-better-music). Non confermato dalla doc ufficiale (che usa il campo `vocal_language`), quindi da testare prima di adottare
- Il repo include il vocabolario generi con diverse voci "Italian ..." [CODE] — genres_vocab.txt

### Inferences
- Applicabili all'italiano: (1) `vocal_language="it"` sempre esplicito; (2) caption che nomina genere italiano ("Italian pop ballad", "cantautorato" non verificato nel vocabolario) e voce; (3) righe da 6-10 sillabe contate in italiano reale, attenzione a elisioni e sinalefe (l'italiano canta "per-un-a-mo-re" in meno note di quante sillabe ortografiche ha: contare le sillabe fonetiche); (4) evitare parole straniere nel testo italiano e troncamenti/apostrofi insoliti che il tokenizer potrebbe spezzare; (5) evitare accenti ambigui, scrivere gli accenti (e', perche') come nel testo normale; (6) batch 2-4 e scegliere per Lyrics Alignment Score; (7) BPM leggermente piu' basso e, se disponibile, modello sft/base con piu' step per la chiarezza.
- Per mixare inglese e italiano nello stesso brano: la doc dice che e' possibile, ma e' una fonte di instabilita' per la fonetica; usarlo solo per hook brevi.
- Gli esempi ufficiali FR/ES sono il riferimento piu' vicino per lunghezza righe e struttura in una lingua romanza.

### Gaps
- Nessuna valutazione quantitativa dell'italiano (WER, lyric alignment per lingua); il giudizio "solid tier" e' di un solo blog.
- Nessuna fonte su gestione di elisioni/dialetti/accenti in italiano.
- Non verificato il comportamento dei marker `[it]` nei lyrics; non confermato dal repo.

## 6. Guide ufficiali/community e esempi che funzionano

### Takeaway
La guida ufficiale piu' completa e' `docs/en/Tutorial.md` del repo (scritta dallo sviluppatore) e lo skill `.claude/skills/acestep-songwriting/SKILL.md`; 200 coppie caption+lyrics+metadata funzionanti in `examples/text2music/`. Fuori dal repo le fonti sono blog di terze parti, di qualita' variabile.

### Cited Findings
- Guida ufficiale "ACE-Step 1.5 Ultimate Guide (Must Read)" — [REPO/docs/en/Tutorial.md](file:///home/drift/git/ACE-Step-1.5/docs/en/Tutorial.md) (mirror: [HF](https://huggingface.co/aTrapDeer/ace-step15-endpoint/blob/main/docs/Tutorial.md)). Filosofia: generazione "human-centered", non one-click; iterare; il caption e' il punto di partenza, nessuna "descrizione perfetta"
- 5 modi ufficiali per scrivere buone caption: random dice (UI), format auto-rewrite, CoT rewrite (LM), audio-to-caption, Simple Mode (descrizione breve -> caption+lyrics+metadata) [DOC] — Tutorial.md. Esempi di Simple Mode: `examples/simple_mode/example_*.json` con `description`, `instrumental`, `vocal_language` (es. "a soft Bengali love song for a quiet evening", vocal_language bn) — [REPO/examples/simple_mode/](file:///home/drift/git/ACE-Step-1.5/examples/simple_mode/)
- Guida per musicisti: [REPO/docs/en/ace_step_musicians_guide.md](file:///home/drift/git/ACE-Step-1.5/docs/en/ace_step_musicians_guide.md) (esempio di caption: "melancholic piano ballad with soft female vocals, gentle string accompaniment, slow tempo, intimate and heartbreaking atmosphere"; consiglio "Use structure tags": anche senza testo scrivere `[Intro][Verse][Chorus][Verse][Chorus][Bridge][Chorus][Outro]` da' una roadmap di energia)
- Workflow ufficiale per risultati migliori: batch size 2-8, AutoGen, scoring automatico, scelta per DiT Lyrics Alignment Score, rifinitura con Repaint [DOC] — Tutorial.md, musicians_guide.md
- Esempio ufficiale di caption + lyrics + metadata (anime pop-rock, zh, 160 s, bpm 100, B minor, 4/4): `[Intro - Synth Brass Fanfare]`, 2 Verse da 8 righe, Chorus da 4, `[Instrumental Break - Synth Brass Melody]`, Bridge, Chorus, `[Outro - Instrumental with Synth Brass Melody]` — [example_01.json](file:///home/drift/git/ACE-Step-1.5/examples/text2music/example_01.json)
- Esempio ufficiale FR trap, 142 s, bpm 100: Intro con interiezioni ("Ah / Eh, eh, eh"), Chorus prima del Verse, righe lunghe ~10-14 parole [EMP] — [example_03.json](file:///home/drift/git/ACE-Step-1.5/examples/text2music/example_03.json) (nota: il contenuto lessicale di alcuni esempi sembra generato da LM e a tratti incoerente: non usarlo come modello di scrittura, solo di formato)
- Community [COMM]: [deAPI prompting guide](https://deapi.ai/blog/ace-step-1-5-prompting-guide-how-to-write-tags-structure-lyrics-and-generate-better-music) (5 prompt completi di esempio: lo-fi boom bap, techno, chamber folk, orchestral trailer, dark ambient), [Scenario help](https://help.scenario.com/articles/8442039029-ace-step-1-5-edit-the-essentials), [aifilms tutorial](https://studio.aifilms.ai/blog/ace-step-1-5-lyrics-to-music-tutorial), [okmiku vocal-language](https://okmiku.com/blog/ace-step-vocal-language)
- Il repo ufficiale ha la voce "Query Rewriting: Auto LM expansion of tags and lyrics" e "LRC generation" [DOC] — [README.md](file:///home/drift/git/ACE-Step-1.5/README.md)

### Inferences
- Come template di lyrics ben formattati usare l'esempio completo di Tutorial.md (Intro-piano / Verse 1 / Pre-Chorus / Chorus-powerful / Verse 2 / Bridge-whispered / Final Chorus / Outro-fade out) adattato all'italiano, con caption coerente ai tag.
- Template minimo per il bot: caption (prosa o tag, ~200 car.), lyrics con sezioni separate da riga vuota, `vocal_language="it"`, `duration` 150-210, bpm/key/time sig opzionali coerenti con la caption.

### Gaps
- Non ho potuto accedere a Reddit, Discord, YouTube né ai thread GitHub Discussions/Issues (non restituiti dalla ricerca); nessun aneddoto da quelle fonti. I blog citati sono secondari e a volte in disaccordo con la doc ufficiale (BPM nei tag, sigle dei modelli).
- Non c'e' una lista pubblica di prompt "noti per funzionare" in italiano.
