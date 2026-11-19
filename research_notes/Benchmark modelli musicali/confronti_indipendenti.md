# Independent listening comparisons and community reports: open-weight song-generation models (as of 2026-11-19)

Scope note: after ~25 tool calls, genuinely independent by-ear comparisons are scarce. The only multi-model listening comparison found is the IT-JIM blog (n=3 clips/model). Everything else is benchmark tables (self-reported or automated), vendor-adjacent blogs, or GitHub issues. Search-engine summaries that I did not verify by opening the page are marked UNVERIFIED. Pages that could not be opened: vi-control.net thread (HTTP 403), civitai.com/models/2946237 (403), forum.tunee.ai HeartMuLa thread (DNS fail). No Reddit, Hacker News, YouTube, Gigazine or HF Space-vote content surfaced in any search; absence is reported as a gap, not as evidence.

## Who compared these models by ear, on what prompts, and what did they conclude per axis?

### Takeaway
Only one source (IT-JIM, 2026-05-21) ran a same-prompt listening comparison across several open models, and its sample is tiny (3 prompts x 1 seed). It found LeVo 2/SongGeneration the most natural-sounding, ACE-Step 1.5 afflicted by a metallic shimmer, HeartMuLa generic, YuE slow and unremarkable, DiffRhythm 2 artificial with unstable rhythm. No independent test of ACE-Step 1.5 XL, YuE2-3B or MiniMax Music 3 by ear was found.

### Cited Findings
- IT-JIM "Best Open-Source AI Music Generators 2026", dated May 21, 2026: 3 prompts (hard rock ~140 BPM, smooth jazz quartet ~95 BPM, modern pop ballad ~100 BPM) with lyrics, 1 seed each = 3 clips per model, "cheaper kind of cloud GPU", hardware unspecified. The listening-table cells were empty in the fetched text, so only prose verdicts are usable. IT-JIM is an ML consultancy, not a model author, but I did not check whether it sells services around any of these models. — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/)
  - ACE-Step 1.5: "metallic shimmer" on vocals and instruments, heard on sustained vowels and cymbal-heavy passages; cleanest on the hard-rock chorus. ACE-Step v1 had no shimmer but "weaker musicality".
  - LeVo 2 (SongGeneration): vocals avoid the metallic register; "the most organic and most natural-sounding clips of any model in the comparison" on all three prompts.
  - HeartMuLa: "generic pop in every case", averaged, smoothed, "AI-blurry"; authors allow it could be a weights/inference quirk on their side.
  - YuE (v1 per context): did not stand out on quality or musicality; roughly 12x slower than realtime on RTX 4090.
  - DiffRhythm 2: lightest style impact but different prompts did produce perceptibly different generations; audio more artificial, rhythm unstable; vocals behind ACE-Step and LeVo.
  - Khala: some flat vocals, a few natural; messy intros, run-to-run instability, simple arrangements.
  - Muse: better general audio quality than ACE-Step 1.5 in cells tested; English vocals have a "Chinese-leaning accent".
  - Not tested/not reported by IT-JIM: ACE-Step 1.5 XL, YuE2-3B, MiniMax Music 3, non-English, seed consistency.
- HeartMuLa GitHub issues contain two user opinions favouring it: issue #116 (2026-06-19) ranks it above DiffRhythm and ACE-Step and shares a sample album; issue #80 (2026-01-28) praises quality and long-span coherence. Single users, no method. Issue #50 (2026-01-21) criticizes the README's style-consistency and Suno-comparison claims as misleading. — [#116](https://github.com/HeartMuLa/heartlib/issues/116), [#80](https://github.com/HeartMuLa/heartlib/issues/80), [#50](https://github.com/HeartMuLa/heartlib/issues/50)
- A Tunee forum post titled "HeartMuLa 3B - Don't waste your time!" exists, but I could not open it (DNS failure); the only description is from a search summary, which said it was short and negative with no technical detail. UNVERIFIED. — [forum.tunee.ai](https://forum.tunee.ai/t/heartmula-3b-dont-waste-your-time/2656)
- A vi-control.net thread "Ace-Step 1.5 - Do we now have an ethically trained Suno at home?" surfaced; could not open (403). A search summary said one forum user judged HeartMuLa possibly better-sounding than ACE-Step 1.5 but much slower. UNVERIFIED. — [vi-control](https://vi-control.net/community/threads/ace-step-1-5-do-we-now-have-an-ethically-trained-suno-at-home.170009/)
- YuE2 coverage (creativeainews, 2026-09-09) reports only M-A-P model-card numbers, no authors' listening: SongBench average on WildSongBench (192 prompts) YuE2 best-of-8 6.9632, standard best-of-2 6.7316, Suno v5 6.8721, Mureka 9 6.9377, ACE-Step 1.5 6.0118. Musicality: YuE2 best-of-8 6.2666, ACE-Step 5.1588 (or 5.9075 in another setting as quoted). Suno v5 leads text alignment. Caveats stated: the headline win needs best-of-8, selection by musicality worsens PER, weights CC BY-NC 4.0, legacy VAE produced benchmark numbers while the default VAE "sounds better". These are developer numbers relayed by a news site. — [creativeainews](https://www.creativeainews.com/articles/yue2-vs-suno-v5-open-music-model-2026/)
- A search summary relayed a Civitai post claiming YuE2 sounds better than Suno V6 Pro "twofold" but falls short on musical ideas; page could not be opened (403). UNVERIFIED single opinion. — [Civitai](https://civitai.com/models/2946237)
- localai.co.kr guide (undated; cites benchmark evaluated 2026-09-12) explicitly says WildSongBench scores are automated and "not a ranking of human listening preferences". Numbers: ACE-Step 1.5 SongBench 6.0118, PER 7.46%; HeartMuLa 3B 6.2483, PER 10.71%; YuE2 6.7316, PER 8.44%; YuE 1 4.9165, PER 36.38%. — [localai.co.kr](https://localai.co.kr/en/guides/local-music-model-comparison)
- Techno-Edge (Japanese, 2026-04-13) on ACE-Step 1.5 XL reports only the vendor benchmark table (tops Suno v5), no listening impressions (via search summary; not opened). UNVERIFIED. — [Techno-Edge](https://www.techno-edge.net/article/2026/04/13/4986.html)
- LeVo 2 / SongGeneration 2: only vendor claims found (20-expert evaluation of 100 songs per model in the Tencent repo, per cnb.cool mirror; paper abstract says it "approaches leading commercial systems") plus blogs (insmelo.com, gaga.art) of unknown independence; one reports PER 8.55%. All UNVERIFIED search-summary items. — [cnb.cool](https://cnb.cool/ai-models/tencent/SongGeneration), [gaga.art](https://gaga.art/blog/songgeneration-2/), [insmelo](https://insmelo.com/blog/levo-2-song-generation)
- GitHub issues reporting ACE-Step quality problems (user reports, single reporters):
  - #1147 (2026-04-25, closed completed): human voice in ComfyUI XL workflow "always carries a distinct electronic/metallic sound"; CFG/sampler changes didn't help. — [#1147](https://github.com/ace-step/ACE-Step-1.5/issues/1147)
  - #1387 (2026-11-17, open): 90s R&B and Southern rap come out too jazz-heavy; custom LoRAs didn't help (genre-range/adherence). — [#1387](https://github.com/ace-step/ACE-Step-1.5/issues/1387)
  - #1375 (2026-11-10, open): Lego stems flanged/garbled, not aligned to source timing. — [#1375](https://github.com/ace-step/ACE-Step-1.5/issues/1375)
  - #494 (2026-02-12, closed): clipping artifacts in dense metal/hard-rock songs. — [#494](https://github.com/ace-step/ACE-Step-1.5/issues/494)
  - #1098 (2026-04-13, closed completed): vocals roll back to an earlier line, skip lines, repeat, or jump ahead (English and French examples from official text2music samples) i.e. lyric-structure drift. — [#1098](https://github.com/ace-step/ACE-Step-1.5/issues/1098)
  - #450 (2026-02-11, open): small lyric edits to fix one mispronounced word change the whole generation. — [#450](https://github.com/ace-step/ACE-Step-1.5/issues/450)
  - #677 (2026-02-22, open): "Enhance Caption" rewrote genre, vocal gender and instrumentation. — [#677](https://github.com/ace-step/ACE-Step-1.5/issues/677)
- MiniMax Music 3: RuntimeWire (2026-08-13) says official weights "remained unavailable at verification"; no licensing, hardware or listening data. Its inclusion in the PER table above (6.27%) is as a closed/API comparator from M-A-P's table, not evidence it is open-weight. — [RuntimeWire](https://runtimewire.com/article/minimax-music-3-open-weights-five-minute-songs)

### Inferences
- The only by-ear evidence puts LeVo 2 first on vocal naturalness and ACE-Step 1.5 behind on shimmer, but n=3 clips and one seed cannot support a ranking; treat as a hypothesis.
- Benchmark and listening signals disagree: ACE-Step 1.5 has the best PER (7.46%) yet is the one with reported shimmer; YuE2 leads automated musicality yet its PER is worse. Automated scores are not listening results (as the localai.co.kr guide itself says).
- "Open-weight MiniMax Music 3" is not supported by anything I could open; don't count it as a deployable contender.

### Gaps
- No Reddit (r/StableDiffusion, r/LocalLLaMA, r/SunoAI), Hacker News, YouTube, Discord or HF Space vote data surfaced; search returned none. Direct browsing of these (not available via the tools used) is the next step.
- No independent by-ear test of ACE-Step 1.5 XL vs others, of YuE2-3B, SongGeneration 2 vs HeartMuLa on matched prompts, or DiffRhythm 2 beyond IT-JIM.
- No per-axis data for 2-4 minute structure, or seed consistency, beyond IT-JIM's remarks (Khala run-to-run instability; ACE-Step v1.5 issue #1098 drift).
- No arena/ELO data found for open models.

## Evidence on non-English and Italian output

### Takeaway
No source tested Italian singing quality by ear in a verifiable way. The only tier list placing Italian ("Solid, needs one or two prompt tweaks") comes from a vendor blog with an unspecified language set; GitHub shows real mispronunciation reports for Dutch, Danish, Arabic, Bengali and French-line skipping, but none for Italian.

### Cited Findings
- okmiku.com (MikuTools, bylined Z.Tools, 2026-05-08) hosts an AI cover tool, so it is vendor-adjacent. It claims "roughly 200 generations split across 12 languages" (languages unnamed, ACE-Step version and settings not given, no rubric). Tiers: Strong = English, Mandarin, Japanese, Spanish; Solid = Korean, French, German, Italian, Portuguese, Hindi ("one or two prompt tweaks"); Acceptable = Russian, Arabic, Turkish, Polish, Dutch, Indonesian, Thai, Vietnamese. Tiers cover 18 languages but only 12 were tested, so some placements are untested. Italian has no Italian-specific finding; French nasal vowels "can sound slightly off when the BPM is high". — [okmiku](https://okmiku.com/blog/ace-step-vocal-language)
- localai.co.kr: ACE-Step card lists 50+ languages but this "does not guarantee pronunciation quality in each language". — [localai.co.kr](https://localai.co.kr/en/guides/local-music-model-comparison)
- ACE-Step GitHub: #484 Dutch pronunciation regression after update ("mixed-language artifacts, dialect-like phonetics, reduced intelligibility", RTX 3060 12GB, 0.6B LM, open, 2026-02-12); #817 Danish single-word mispronunciation, IPA inline request closed not planned (2026-03-12; reporter says model seems to understand IPA but it disrupts flow); #1146 Arabic and #1084 Bengali: reporters say the model "was never designed" for them; training on local voices did not fix it, both closed not planned. — [#484](https://github.com/ace-step/ACE-Step-1.5/issues/484), [#817](https://github.com/ace-step/ACE-Step-1.5/issues/817), [#1146](https://github.com/ace-step/ACE-Step-1.5/issues/1146), [#1084](https://github.com/ace-step/ACE-Step-1.5/issues/1084)
- ACE-Step PR #1365 (2026-10-23, open) adds Italian Gradio UI translation only (UI, not vocals). — [#1365](https://github.com/ace-step/ACE-Step-1.5/pull/1365)
- IT-JIM: no non-English test; Muse's English vocals have a Chinese-leaning accent. — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/)
- HeartMuLa: a search summary says the model card lists multilingual lyrics (English, Chinese, Japanese, Korean, Spanish), Italian not listed. UNVERIFIED (model card not opened). HeartMuLa's own paper uses a multilingual benchmark per another summary. UNVERIFIED.

### Inferences
- Italian is plausible but unproven on ACE-Step; for HeartMuLa it is not an advertised language. Expect to need a self-run A/B with Italian lyrics, with attention to double consonants, open vowels and line skipping (#1098 shows skipping also happens in French).

### Gaps
- No Italian-specific user report for any model; no Spanish/French by-ear comparison between models; nothing for LeVo 2, YuE2 or DiffRhythm 2 on non-English.

## Speed and cost in practice

### Takeaway
Hard numbers exist mainly for YuE2 on RTX 4090 (vendor-derived, relayed). ACE-Step real-world timings are scattered in issues (some very slow cases tied to bugs); HeartMuLa about RTF 1.0 per community summaries; no CPU/offload timing for a 2-3 minute song found for any model.

### Cited Findings
- YuE2 on RTX 4090 24GB: one 3.6-minute song ~286 s end to end (71 s generation + 215 s audio decode); peak VRAM 11.18 GiB (14.08 GiB at max context); standard best-of-2 ~9.5 min per song, best-of-8 ~38 min; needs Linux, Python 3.12, BF16 NVIDIA GPU with 24GB, 24GB host RAM. Source is M-A-P card numbers via a news site. — [creativeainews](https://www.creativeainews.com/articles/yue2-vs-suno-v5-open-music-model-2026/)
- YuE (v1 context) ~12x slower than realtime on RTX 4090 (IT-JIM, small-sample but a direct measurement in their run; hardware spec otherwise vague). — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/)
- ACE-Step 1.5 official claim: under 2 s per full song on A100, under 10 s on RTX 3090 (developer paper, relayed by search summary; UNVERIFIED by me). — [arXiv 2602.00744](https://arxiv.org/abs/2602.00744)
- ACE-Step user timings: #333 (2026-02-08) batch 16 at about 160x realtime on RTX 5090 with SFT 4B (patched multi-batch bug); #457 (2026-02-11) 30 s generations taking up to 2 hours on RTX 5060 Ti 16GB after LoRA load, "0.00 GB free VRAM", CPU VAE decode 327 s/step. — [#333](https://github.com/ace-step/ACE-Step-1.5/issues/333), [#457](https://github.com/ace-step/ACE-Step-1.5/issues/457)
- ACE-Step VRAM: #428 4B LM runs OOM on 16GB; 1.7B LM + SFT DiT fails in VAE decode ~44 MB short; localai.co.kr cites vendor table: XL (4B) needs CPU offload at 16-20 GB, 24GB+ with the 4B LM. PR #1359 (2026-10-15) makes 8GB cards offload the DiT by tier. — [#428](https://github.com/ace-step/ACE-Step-1.5/issues/428), [localai.co.kr](https://localai.co.kr/en/guides/local-music-model-comparison), [#1359](https://github.com/ace-step/ACE-Step-1.5/pull/1359)
- HeartMuLa: repository reports roughly RTF 1.0 (localai.co.kr, spec-based). HeartLib PR #76 (2026-01-27, open, not merged) claims FP8 dynamic quantization gets it onto 8GB VRAM and cut generation from ~2 hours to ~10 min (author's claim, possible quality loss). HeartMuLa Studio reports a 30 s clip in ~48 s on RTX 3060 12GB (search summary, UNVERIFIED). — [localai.co.kr](https://localai.co.kr/en/guides/local-music-model-comparison), [PR #76](https://github.com/HeartMuLa/heartlib/pull/76), [HeartMuLa Studio](https://github.com/fspecii/HeartMuLa-Studio)
- Khala: 24GB+ NVIDIA recommended, weights ~52GB, fixed 62 steps regardless of length, 1-10 min songs; no wall-clock timings in the lilting article. — [Lilting](https://lilting.ch/en/articles/khala-music-generation-gpu-notes)
- LeVo 2: README VRAM tiers 10/22/28 GB, max 4:30 (as relayed by IT-JIM, not measured by them). — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/)

### Inferences
- A 2-3 minute song: YuE2 ~5 min on a 4090 at best-of-1/2 settings; HeartMuLa ~2-3 min if RTF 1.0 holds; ACE-Step turbo likely seconds on a decent GPU, SFT/XL slower (50 steps). Only the YuE2 figure is concrete.
- Most "speed" figures are developer claims; independent ones are anecdotal.

### Gaps
- No CPU-only or offload timings for a 2-3 minute song for any model; no independent ACE-Step XL timings on consumer GPUs; no cost-per-song data.

## Reliability, failure rates, known bugs (incl. Khala precision, ROCm)

### Takeaway
No failure-rate-per-N-generations data exists. The issue trackers show recurring precision/NaN problems (fp16 lyric encoder, ROCm VAE decode), SFT/XL checkpoints producing garbled noise on certain backends, and Khala's unresolved quality warning.

### Cited Findings
- Khala: README News 2026-05-07 says an issue under investigation "may significantly affect inference quality", numerical precision suspected; still present after the 2026-05-16 demo release and as of Lilting's update on 2026-06-05; I found no later fix. — [Lilting](https://lilting.ch/en/articles/khala-music-generation-gpu-notes). IT-JIM repeats the repo disclaimer "Until this notice is removed, please treat current generation quality as unstable." — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/)
- ACE-Step NaN/precision: PRs #1352 (2026-10-08) and #1377 (2026-11-13) upcast the lyric encoder to fp32 on fp16 GPUs (Volta/Turing/Pascal) to stop NaN latents when lyrics are non-empty; #1389 (2026-11-18, open, 0 comments): RX 9060 XT 16GB gfx1200, Ubuntu 26.04, ROCm 10.1, torch 2.15 ROCm, bf16 + CPU offload: item 0 of every batch decodes to DC constant (NaN in VAE decode), item 1 fine; workaround generate two and discard first. Single reporter. — [#1352](https://github.com/ace-step/ACE-Step-1.5/pull/1352), [#1377](https://github.com/ace-step/ACE-Step-1.5/pull/1377), [#1389](https://github.com/ace-step/ACE-Step-1.5/issues/1389)
- ACE-Step ROCm: #658 hardcoded HSA_OVERRIDE_GFX_VERSION crashes desktop on RX 6700 XT; #644 import error torch.distributed on RX 9060 XT Windows; #665 repaint fails (torchcodec); PR #1053 AMD R9700 torch.distributed crash; PR #1242 torchcodec fallback. Search summary notes default `uv run` may install CUDA wheels and overwrite a ROCm setup (UNVERIFIED). — [#658](https://github.com/ace-step/ACE-Step-1.5/issues/658), [#644](https://github.com/ace-step/ACE-Step-1.5/issues/644), [#665](https://github.com/ace-step/ACE-Step-1.5/issues/665)
- ACE-Step XL/SFT garbled output: #1299 "Why does the SFT XL sound like garbled noise?" (2026-08-23, closed not planned, no cause in issue summary); #1259 xl-base/xl-sft garbled on Apple Silicon MLX and MPS, turbo fine (closed completed 2026-08-16); #1288 SFT checkpoints (2B and XL) output noise via Python pipeline while identical weights work in ComfyUI, turbo unaffected (closed completed 2026-08-28); #1329 cover_noise_strength > 0 collapses XL SFT output to near-silence (closed not planned). #434 LoRA gave garbled audio after relaunch on RTX 3060. — [#1299](https://github.com/ace-step/ACE-Step-1.5/issues/1299), [#1259](https://github.com/ace-step/ACE-Step-1.5/issues/1259), [#1288](https://github.com/ace-step/ACE-Step-1.5/issues/1288), [#1329](https://github.com/ace-step/ACE-Step-1.5/issues/1329), [#434](https://github.com/ace-step/ACE-Step-1.5/issues/434)
- ACE-Step OOM/crash: #371 RTX 5090 torchao AffineQuantizedTensor load failure; #245 bool-sort error on RTX 3090/A4000; #218 full songs OOM in VAE encode on RTX 3060 12GB for LoRA prep; #1378 5Hz LM VRAM not freed (needed for XL remix). — [#371](https://github.com/ace-step/ACE-Step-1.5/issues/371), [#1378](https://github.com/ace-step/ACE-Step-1.5/issues/1378)
- HeartMuLa/heartlib: #106 (2026-03-29) device mismatch errors in fp16 inference on RTX 4090; #133 (2026-09-08) working Linux ROCm 7.1 / RX 9070 XT recipe with six patches, codec on CPU on 16GB cards; PR #86 clamp VQ indices to avoid CUDA assertions; tags may be ignored (issue #90 per search summary, UNVERIFIED); requests for tag lists (#39, #17). — [#106](https://github.com/HeartMuLa/heartlib/issues/106), [#133](https://github.com/HeartMuLa/heartlib/issues/133), [#86](https://github.com/HeartMuLa/heartlib/pull/86)
- YuE2 requires BF16-capable NVIDIA GPU, Linux, 24GB VRAM per card; no AMD path documented in what I read. — [creativeainews](https://www.creativeainews.com/articles/yue2-vs-suno-v5-open-music-model-2026/)
- SongGeneration repo issues could not be retrieved (GitHub search API returned HTTP 422 for the repo path I guessed; the repo path may be different). No data.

### Inferences
- ROCm is workable for ACE-Step and HeartMuLa with patches and per-GPU quirks (RDNA3/4 reports), but newest stacks (ROCm 10.x, gfx1200) show VAE-decode NaN. For the user's likely ROCm setup, ACE-Step turbo/ComfyUI path has the most community patching; SFT/XL via the Python pipeline is the riskiest by issue count.
- The turbo checkpoint is repeatedly reported as unaffected when SFT/xl-base break (#1259, #1288), a consistent pattern across 2 independent reporters.

### Gaps
- No failure rate per N generations anywhere. Issue counts are not rates (ACE-Step is simply the most-used and most-reported).
- SongGeneration, DiffRhythm 2 and MiniMax issue trackers not reviewed.
- Khala is not in the user's model list but its precision warning is the benchmark for "numerical precision" problems; no resolution found after 2026-06-05.

## Vendor/hosting vs independent sources, and a defensible ranking

### Takeaway
Independent by-ear evidence is thin enough that any ranking is low confidence. Best-supported tentative ordering for open-weight vocal songs: LeVo 2 and ACE-Step 1.5 (turbo/SFT/XL) as the practical leaders, YuE2-3B strongest on automated musicality but NC-licensed and 24GB-bound, HeartMuLa 3B contested, DiffRhythm 2 and YuE v1 behind.

### Cited Findings
- Source classification:
  - Independent-ish, by ear: IT-JIM (n=3 clips/model). Individual GitHub users (HeartMuLa #116, #80; ACE-Step bug reports). Anecdotes only.
  - Developer self-reports: ACE-Step 1.5 paper/page, HeartMuLa paper, LeVo 2 paper (20 experts x 100 songs), YuE2 M-A-P card (WildSongBench; PER, SongBench, MuLan).
  - Automated benchmark relayed by third parties: localai.co.kr, creativeainews, Techno-Edge. Not human preference.
  - Vendor/hosting-adjacent: okmiku.com (hosts cover tool), gaga.art, insmelo.com, heart-mula.com ("ACE-Step Review & Comparison", a HeartMuLa-promoting domain; only a search-summary view, UNVERIFIED), tunee.ai pages (marketing copy on ACE-Step 1.5 claiming high phonetic accuracy, per search summary, UNVERIFIED). No Sogni/WaveSpeed reviews surfaced.
- Lyric intelligibility (PER, lower better, WildSongBench, relayed): Suno v4.5 5.80%, Suno v5.5 5.96%, MiniMax Music 3 6.27% (closed API), ACE-Step 1.5 7.46%, Suno v5 8.10%, YuE2 8.44% (9.79% best-of-8), LeVo 2 8.55% (blog-sourced, UNVERIFIED), HeartMuLa 10.71%, YuE1 36.38%. — [creativeainews](https://www.creativeainews.com/articles/yue2-vs-suno-v5-open-music-model-2026/), [localai.co.kr](https://localai.co.kr/en/guides/local-music-model-comparison)
- ACE-Step's own project page lists limitations of output inconsistency and coarse vocal synthesis (via search summary, UNVERIFIED). — [ACE-Step 1.5 page](https://ace-step.github.io/ace-step-v1.5.github.io/)

### Inferences (ranking, with confidence)
1. LeVo 2 / SongGeneration 2: top on the single by-ear test (vocal naturalness), PER mid-pack. Confidence low (one test, n=3, plus vendor claims).
2. ACE-Step 1.5 (turbo/SFT, XL): best PER among open models, widest tooling and community, fastest; shimmer reported by IT-JIM and issue #1147; XL/SFT backend fragility. Confidence moderate on usability/lyrics, low on vocal naturalness. XL by ear: no independent data.
3. YuE2-3B: best automated musicality and SongBench, but best-of-8 dependent, NC licence, 24GB NVIDIA, minutes per song. Confidence low (no independent listening).
4. HeartMuLa 3B: conflicting; IT-JIM "generic pop", a negative forum post (UNVERIFIED) vs users on GitHub preferring it over ACE-Step. PER worst of the modern set (10.71%). Confidence low.
5. DiffRhythm 2, YuE v1, Khala: behind in the one test; Khala flagged unstable by its own maintainers.
- MiniMax Music 3: unrankable (weights unavailable per the only source opened).
- Overall confidence in this ranking: low. Differences in the SongBench numbers (6.0 vs 6.7) come from automated metrics that do not necessarily track listening.

### Gaps
- No Sogni/WaveSpeed/Replicate-style hosting reviews found; no head-to-head HF Space votes or arenas.
- DiffRhythm 2 and LeVo 2 independent reports essentially absent.
- Recommended follow-up (outside my tools): browse r/StableDiffusion, r/SunoAI, r/LocalLLaMA, YouTube comparisons, and run a blind in-house A/B with Italian lyrics, 5+ seeds per model.
