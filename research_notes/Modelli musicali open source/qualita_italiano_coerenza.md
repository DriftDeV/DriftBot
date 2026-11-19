# Measured quality of open-weight song models: benchmarks, long-form coherence, Italian vocals (as of 2026-11-19)

Method note: ~13 tool calls. Tables below were read from arXiv HTML/PDF text. No independent Italian-specific or long-form measurement was found for any model.

## 1. Benchmarks, leaderboards, listening tests: who ranks highest among open weights, by how much vs ACE-Step 1.5

### Takeaway
ACE-Step 1.5 and HeartMuLa are the top two open models in nearly every table, and which one wins depends on who ran the test and the metric. HeartMuLa wins SongEval (also its training signal) and the ACE-Step paper's AudioBox CE. ACE-Step 1.5 wins style/text alignment and lowest PER among the older open models. YuE2 (Nov 2026, YuE team) claims to beat all public systems, but is author-run and its weight release status is unverified. No independent third-party arena data on Italian or on these open models was found.

### Cited Findings
**Author-run: ACE-Step 1.5 paper Table 1** (SongEval from ASLP-lab suite, AudioBox from Meta; Style/Lyric Align from the authors' own proprietary reward models; test prompts and lyrics from Gemini 3 Pro; unclear if baselines were recomputed). SongEval Coh/Mus/Mem/Cla/Nat; Style; Lyric:
- ACE-Step 1.5: 4.72/4.67/4.72/4.66/4.59; Style 39.1; Lyric 26.3; AudioBox CE 7.42, CU 8.09, PC 6.47, PQ 8.35
- HeartMuLa: 4.68/4.55/4.69/4.55/4.45; Style 31.7; Lyric 28.6; CE 7.66, PQ 8.25
- DiffRhythm 2: Coh 3.99, Nat 3.66; Style 32.1; Lyric 3.8
- LeVo (SongGeneration): Coh 3.55, Nat 3.20; Style 29.4; Lyric -1.2
- ACE-Step 1.0: Coh 3.99; Lyric 0.9. YuE: Coh 3.01; Style 26.8; Lyric -4.6
- Reference commercial: Suno-v5 Coh 4.72, Style 46.8, Lyric 34.2; Suno-v4.5 Coh 4.64
- Source: [ACE-Step 1.5 paper](https://arxiv.org/html/2602.00744). The StepFun team ran subjective evaluations (Music Arena) per the acknowledgements; the project page says XL (4B DiT) beats base slightly (AudioBox 7.76 vs 7.42, SongEval-type score 8.12 vs 8.09) — [project page](https://ace-step.github.io/ace-step-v1.5.github.io). A secondary search summary reported XL SongEval coherence 4.79; not verified against the paper.
- Conflict of interest: Style/Lyric align use ACE-Step's own reward models.

**Author-run: HeartMuLa paper** ([arXiv 2601.10547](https://arxiv.org/html/2601.10547v1)): PER (lower better) / SongEval avg:
- English: HeartMuLa 0.09 / 4.48; ACE-Step 0.21 / 3.25; DiffRhythm 2 0.28 / 3.87; YuE 0.65 / 2.64
- Chinese: HeartMuLa 0.12 / 4.48; ACE-Step 0.24 / 3.69; DiffRhythm 2 0.32 / 3.77; YuE 0.50 / 3.03
- Japanese PER: HeartMuLa 0.20, ACE-Step 0.33, YuE 0.62. Korean: 0.16 / 0.38 / 0.56. Spanish: 0.13 / 0.21 (no YuE/DR2)
- Subjective Structure score: HeartMuLa 73.44, ACE-Step 69.07, DiffRhythm 2 61.63
- Conflict of interest: SongEval and AudioBox were used to filter SFT data and build DPO pairs (margin >0.5), then SongEval is the evaluation metric. SongGeneration not evaluated. The ACE-Step version tested there is not stated in my extract (probably 1.0, scores far below ACE-Step's own 1.5 numbers); this explains the conflict with the ACE-Step 1.5 paper.

**More independent: SongBench** (Tsinghua/Tencent-linked authors, [arXiv 2604.25937](https://arxiv.org/pdf/2604.25937), code github.com/Tencent/SongBench). A learned multi-dimension quality predictor, validated on 352 out-of-distribution samples from DiffRhythm 2, HeartMuLa, ACE-Step 1.5, MiniMax, Mureka, Suno. Table 2 "Mean (Ours)" / SongEval:
- ACE-Step 1.5: 6.04 / 4.11 (Melody 6.11, Vocal 6.17, Structure 6.09, Mixing 6.12)
- HeartMuLa: 5.80 / 4.30 (Vocal 6.14, Structure 5.74)
- LeVo: 5.18 / 3.49. DiffRhythm 2: 4.93 / 3.71
- Commercial: Suno v5 6.86, Mureka V8 6.87, MiniMax 2.5 6.52
- Takeaway: on a non-SongEval-trained metric ACE-Step 1.5 beats HeartMuLa by ~0.24, while SongEval flips it. Supports the view that HeartMuLa is tuned to SongEval. The authors did not train any of the generators, so this is closer to independent, but the metric is itself a model (paper claims strong correlation with expert ratings; I could only read the tables).

**Author-run (YuE team, 2026): YuE2 report** ([arXiv 2609.33757](https://arxiv.org/pdf/2609.33757)). WildSongBench: 192 prompts, 94 Chinese + 98 English (no Italian); each model gets best of 2 candidates by lowest PER. Public systems, SongBench Avg / SongEval Avg / PER:
- YuE2 6.73 / 4.26 / 0.0844; YuE2 Bo8 6.96 / 4.30 / 0.0979
- LeVo 2 6.32 / 4.02 / 0.2612
- HeartMuLa 6.25 / 4.55 / 0.1071 (dagger: used SongEval/AudioBox in training)
- ACE-Step 1.5 6.01 / 3.85 / 0.0746
- MiniMax Music 3 6.28 / 4.10 / 0.0627
- Muse 6.03 / 3.79 / 0.3342; DiffRhythm 2 5.24 / 3.52 / 0.1841; YuE1 4.92 / 3.22 / 0.3638; SongBloom 4.24 / 3.21 / 0.1919
- ACE-Step 1.5 text alignment (Q3O 4.58, MuLan 0.437, AllMusicCaps 0.387) is the best of the older public models, above HeartMuLa (3.49 / 0.382 / 0.279). Its PER 0.0746 is the lowest among the open-weight systems in that table; only closed MiniMax Music 3 (0.0627) is lower.
- Expert listening (Arena: 351 participations, 4,439 pairs, 62 paid conservatory or audio-AI annotators): YuE2 Bo8 beat Suno v4.5 57% vs 31%, tied vs Suno v5 40% vs 40%, lost to Suno v6 32% vs 59%. These were vs proprietary systems only; I saw no listening-test row against ACE-Step 1.5.
- Caveat: authors compared their own model; unknown whether YuE2 weights are released (a search hit, [mer.vin](https://mer.vin/news/yue2-3b-claims-it-beats-suno-v6-on-open-music-generation/), mentions "3B", not checked). Treat YuE2 as unverified for use.

**Music Arena** ([paper](https://arxiv.org/html/2507.20900v2), 2025): live pairwise leaderboard (Bradley-Terry). Early paper listed ACE-Step (v1) and SongGen as open; I could not find a current leaderboard snapshot with ACE-Step 1.5, HeartMuLa or others. Check music-arena.org manually.

**Other**: SongEval may be biased toward female vocals (one paper noted, per search summary; not verified at source). A hosted-model leaderboard (AA-Music-Vocal, ACE Studio's commercial "ACE Music v1") exists and is unrelated to ACE-Step — do not conflate ([hermes-ai.net](https://hermes-ai.net/news/ace-studio-s-ace-music-v1-beats-suno-to-top-ai-music-leaderboard/), low-quality aggregator).

### Inferences
- Open-weight ranking on balanced evidence: ACE-Step 1.5 ≈ HeartMuLa > YuE2 (if released) ≈ LeVo 2 / SongGeneration 2 > DiffRhythm 2 > YuE1 / SongBloom. ACE-Step 1.5 beats HeartMuLa on text alignment, PER and SongBench; HeartMuLa wins SongEval and (in its own paper) PER.
- No evidence of any open model clearly and independently beating ACE-Step 1.5 overall on quality. The only models claimed to be better (YuE2, XL) are author-run or the same family.
- Metric blend: three papers disagree on PER for ACE-Step vs HeartMuLa (HeartMuLa paper 0.21 vs 0.09; YuE2 paper 0.0746 vs 0.1071; ACE-Step paper lyric align 26.3 vs 28.6). The disagreement is probably ACE-Step version and ASR choice; do not rely on it.

### Gaps
- No full-text read of SongBench correlation tables or per-model human MOS. No ACE-Step XL independent numbers. No SongBloom or SongGeneration 2 numbers beyond LeVo rows above. Music Arena current standings not found. No MusicEval, FAD or CLAP comparison found across these models.

## 2. Long-form structural coherence (2-4 min): key, tempo, structure drift and loops

### Takeaway
No published measurement of key or tempo stability at 2-4 minutes exists for any of these models in what I found. Only claims and a structure sub-score.

### Cited Findings
- ACE-Step 1.5 official limitations: "highly sensitive to random seeds and input duration, leading to varied 'gacha-style' results"; "coarse vocal synthesis lacking nuance"; unnatural transitions in repaint/extend — [project page](https://ace-step.github.io/ace-step-v1.5.github.io). Headline claim of up to 10-minute songs; no coherence score by duration. Paper reports 240 s tracks in about 1 s on A100.
- A Google Slides manual for XL claims up to 360 s, with 180-300 s "full songs" and 300-360 s "Good*" needing more steps (low-authority source, [slides](https://docs.google.com/presentation/d/1PjlqimpO2XUxUwTj8BbDNZV4y4hIRCow/htmlpresent)).
- HeartMuLa claims up to 6 minutes with structure control; its subjective Structure rating is 73.44 vs ACE-Step 69.07 vs DiffRhythm 2 61.63 (authors' own test) — [paper](https://arxiv.org/html/2601.10547v1).
- SongBench structure (learned metric, 352 OOD samples; durations unknown): ACE-Step 1.5 6.09, HeartMuLa 5.74, LeVo 5.08, DiffRhythm 2 4.72 — [SongBench](https://arxiv.org/pdf/2604.25937). Structure leaning ACE-Step 1.5 here contradicts the HeartMuLa paper's subjective Structure. Neither isolates duration.

### Inferences
- Structure scores are a tie between ACE-Step 1.5 and HeartMuLa with opposite winners per source. Practical risk for a bot: ACE-Step 1.5 seed variance (gacha) means generate-and-select helps; an LM-planned structure and 120-240 s targets sit inside its documented sweet spot.

### Gaps
- No Reddit/forum reports on loops or key drift found (search returned none). No measured tempo/key stability data. Nothing on SongBloom, YuE or SongGeneration long-form drift beyond their own papers (not read).

## 3. Prompt adherence and lyric intelligibility

### Takeaway
ACE-Step 1.5 leads open models on text/style prompt adherence in two separate tables, and has near-top intelligibility (PER 0.0746 on English/Chinese prompts). HeartMuLa is weaker on prompt adherence, stronger on audio-judged musicality.

### Cited Findings
- YuE2 report Table 2: Q3O prompt adherence ACE-Step 1.5 4.58 vs HeartMuLa 3.49, LeVo 2 3.95, DiffRhythm 2 4.09, Muse 4.40, YuE1 3.73, SongBloom 3.03; PER ACE-Step 0.0746, HeartMuLa 0.1071, DiffRhythm 2 0.1841, LeVo 2 0.2612, SongBloom 0.1919, YuE1 0.3638 — [YuE2](https://arxiv.org/pdf/2609.33757). Competitor-run but ACE-Step's number favours ACE-Step.
- ACE-Step paper Style Align 39.1 vs HeartMuLa 31.7 vs DiffRhythm 2 32.1 vs LeVo 29.4 (authors' own reward model) — [paper](https://arxiv.org/html/2602.00744).
- HeartMuLa paper PER (Section 1) shows HeartMuLa far better than ACE-Step in its own test.

### Inferences
- PER is measured on English/Chinese only in every paper found.

### Gaps
- No WER/PER for Italian from any source.

## 4. Multilingual support and Italian

### Takeaway
Only ACE-Step 1.5 names Italian (in a 50+ language list). All other candidates are evaluated on English/Chinese (YuE2, SongBench), English/Chinese/Japanese/Korean/Spanish (HeartMuLa), or zh/en/es/ja "etc." (SongGeneration v2). No measured Italian result exists for any model.

### Cited Findings
- ACE-Step 1.5: claims prompt adherence across 50+ languages, paper uses stochastic Romanization of 50% of non-Roman lyrics in training, no per-language results — [paper](https://arxiv.org/html/2602.00744). Diffusers docs list Italian among 50+ lyric languages — [Diffusers](https://huggingface.co/docs/diffusers/v0.39.0/api/pipelines/ace_step). Tunee page claims Italian "high phonetic accuracy" (marketing, [tunee](https://www.tunee.ai/models/ace-step-1-5)).
- Only independent-ish impression: a blog author (about 200 generations across 12 languages, qualitative, no scores) puts Italian in the "solid tier (needs a prompt tweak or two)" with Korean, French, German, Portuguese, Hindi, and says "roughly comparable" to MiniMax Music Cover for those — [okmiku](https://okmiku.com/blog/ace-step-vocal-language). The site also sells AI music; treat as soft evidence.
- HeartMuLa: English, Chinese, Japanese, Korean, Spanish evaluated; Italian not mentioned — [paper](https://arxiv.org/html/2601.10547v1).
- SongGeneration v2-large (released 2026-03-01): zh, en, es, ja, "etc."; v1 was zh/en only; Italian not named — [HF model card](https://huggingface.co/tencent/SongGeneration), [InsMelo](https://insmelo.com/blog/levo-2-song-generation).
- YuE: described as multilingual lyrics following with fine-tuning for tail languages; original paper focuses English/Chinese/Japanese/Korean (the latter list is my background knowledge, not verified this session). Italian unstated.
- DiffRhythm 2, SongBloom: no language list found in search; DiffRhythm 2 benchmarks English/Chinese in HeartMuLa paper; SongBloom same family evaluated on English/Chinese (background knowledge).
- YuE2 test prompts are 94 Chinese + 98 English "naturally code-switched" — [YuE2](https://arxiv.org/pdf/2609.33757).

### Inferences
- English/Chinese-only in practice: YuE1, SongBloom, DiffRhythm 2, probably LeVo/SongGeneration (Italian unlisted). HeartMuLa's Spanish is a related Romance language, but its Spanish PER (0.13) is a weak proxy for Italian.
- ACE-Step 1.5 has the only documented Italian claim, and the paper's own limitations say vocal synthesis is "coarse" and quality floor uneven outside major languages (okmiku).

### Gaps
- No Italian examples, user reports, or WER numbers found for any model. A local test (ASR on Italian output with a Whisper model) is the only way to settle this.

## 5. Vocal artifacts per model

### Cited Findings
- ACE-Step 1.5: "coarse vocal synthesis lacking nuance", slightly more produced vs Suno per one review ([okmiku review](https://okmiku.com/blog/ace-step-v1-5-review), summary only); Vocal score 6.17 in SongBench, tied with HeartMuLa 6.14 — [SongBench](https://arxiv.org/pdf/2604.25937).
- HeartMuLa: SongBench Vocal 6.14, Mixing 5.93; high SongEval but trained against it.
- LeVo/SongGeneration: lower Vocal (5.56) in SongBench; lyric alignment -1.2 in ACE-Step's table (authors-run by a competitor).
- YuE1: highest PER (0.36-0.65) = garbled lyrics; DiffRhythm 2 PER 0.18-0.32.
- No per-model robotic/off-pitch reports found from forums.

### Gaps
- No listening reports from Reddit/YouTube retrieved.

## 6. Ranking vs ACE-Step 1.5 turbo for Italian-prompt Discord bot (likelihood to beat it)

### Takeaway
Nothing has evidence of beating ACE-Step 1.5 for Italian. ACE-Step 1.5 is the only open model with a documented Italian claim, and leads on prompt adherence and PER. Best candidates to try: ACE-Step 1.5 XL (same family), HeartMuLa (better English polish, Spanish tested), YuE2 only if weights exist.

### Ranking (most to least likely to beat ACE-Step 1.5 turbo for Italian), with evidence
1. ACE-Step 1.5 XL: same pipeline, 4B DiT, small gains in author tables (AudioBox 7.76 vs 7.42; SongEval-type 8.12 vs 8.09); keeps the 50+ language claim. Author-run only. Turbo itself is a distilled variant; the paper's rows are for the non-turbo "dynamic distilled DiT" per caption, so turbo penalty is unmeasured.
2. HeartMuLa: best SongEval and strongest PER claim, tested on Spanish, Japanese, Korean. But Italian untested, weaker prompt adherence (Q3O 3.49), SongEval conflict of interest, 5.4B params (slower), SongBench slightly below ACE-Step.
3. YuE2: best claimed overall quality (author-run), but only English/Chinese tested; weights availability unverified; symbolic planning, 3.58B.
4. SongGeneration (LeVo) 2: lists zh/en/es/ja "etc."; mid scores; negative lyric alignment in ACE paper but 4.02 SongEval in YuE2 paper; Italian unknown.
5. DiffRhythm 2: older, lower scores, no language list.
6. YuE1: garbled lyrics (PER 0.36-0.65), weakest SongEval.
6. SongBloom: lowest SongBench and Q3O (3.03), needs audio prompt rather than text style.

### Gaps
- Ranking among 1-3 is an inference; no Italian-specific data. Recommend a 10-prompt Italian bake-off with Whisper-large Italian PER plus a native listener.
