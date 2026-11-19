# Open-weight song-generation models (lyrics + sung vocals) as of 2026-11-19

Method note: WebSearch/WebFetch only, ~25 calls. Many pages are secondary (blogs/aggregators); search-summary text was sometimes unreliable (fetch-model paraphrase). Items marked [UNVERIFIED] need a check on the primary page. GitHub "last commit" dates were NOT visible via fetch for any repo. No Reddit threads were retrievable.

## Which models exist and what are their latest versions?

### Takeaway
Credible open-weight lyric-to-song alternatives to ACE-Step 1.5 as of Nov 2026: MiniMax-Music3 (Aug 2026, non-commercial license, best raw fidelity per reviewers), Tencent SongGeneration 2 / LeVo 2 (Mar 2026), YuE2-3B (Sep 2026, CC BY-NC), HeartMuLa (Jan 2026, 3B shipped), Khala (May 2026, CC BY-NC, flagged quality bug), Muse (Jan 2026, small), DiffRhythm 2 (late 2025). ACE-Step itself has no announced successor; latest is 1.5 XL (2026-04-02). Qwen-Music, StepAudio 3 Music, Shao/FullDiT are announced in papers/APIs but NO verified open weights.

### Cited Findings

**ACE-Step 1.5 (baseline) and XL**
- ACE-Step 1.5 released ~Jan 28 2026 (GitHub release dated ~Feb 4 per a Japanese report); v1 (3.5B) open-sourced 2025-05-07 — [ComfyUI Wiki news](https://comfyui-wiki.com/en/news/2026-01-23-ace-step-1-5-music-generation), search summary of multiple sources (date discrepancy Jan 23/28/Feb 4 between sources).
- ACE-Step 1.5 XL (4B DiT; variants xl-base, xl-sft, xl-turbo) released 2026-04-02; 2B DiT variants base/sft/turbo; Qwen3-based LM 0.6B/1.7B/4B planner; 10 s to 10 min; lyrics 50+ languages; reference audio, repaint/edit, cover, LoRA (about 8 songs, ~1 h on a 3090), stem separation, Vocal2BGM, LRC; XL needs >=12 GB VRAM with offload, 20 GB recommended — [GitHub README](https://github.com/ACE-Step/ACE-Step-1.5), [release v0.1.6](https://github.com/ace-step/ACE-Step-1.5/releases/tag/v0.1.6).
- Repo: 15.0k stars, 2.0k forks, 101 open issues, 72 open PRs, 1,410 commits; no successor/v2 mentioned — [GitHub](https://github.com/ACE-Step/ACE-Step-1.5). A search for "ACE-Step 2" found only a Product Hunt page describing the existing project, no confirmed new model — [Product Hunt](https://www.producthunt.com/products/ace-step-2/launches).
- Tech report: [arXiv 2602.00744](https://arxiv.org/abs/2602.00744). License MIT per [soundgen.ai](https://soundgen.ai/ai-music-models) and Japanese press ([Gigazine](https://www.gigazine.net/gsc_news/en/20260409-ace-step-1-5-xl/)). Developers claim XL beats Suno v5 on benchmarks (self-claim) — [Techno-Edge](https://www.techno-edge.net/article/2026/04/13/4986.html).

**MiniMax-Music3** (MiniMax)
- Open weights on HF `MiniMaxAI/MiniMax-Music3`; release ~2026-08-13 per most sources (theopenweights lists Aug 7; MarkTechPost article dated 2026-08-17) — [HF](https://huggingface.co/MiniMaxAI/MiniMax-Music3), [The Open Weights](https://theopenweights.com/categories/music), [MarkTechPost](https://www.marktechpost.com/2026/08/17/minimax-releases-minimax-music3/) (page itself returned 403; content via search snippet).
- Architecture: hierarchical autoregressive "Hybrid-LM": 8B Global LLM (init Qwen3-8B) + 0.6B Local LLM + 2.4B flow-matching module + 123M Flow-VAE; 8-layer RVQ tokenizer (25 fps); about 11B total — [HF card](https://huggingface.co/MiniMaxAI/MiniMax-Music3), [Sogni](https://blog.sogni.ai/blogs/minimax-music3-vs-ace-step-15-xl/).
- Inputs: lyrics with [Verse]/[Chorus] tags + music description or structured caption (up to 5,000 tokens); output 32 kHz 16-bit stereo WAV (Sogni says 44.1 kHz — conflict); up to ~5 min; non-streaming only; CUDA required; ~57 GB download — [HF card](https://huggingface.co/MiniMaxAI/MiniMax-Music3), [mer.vin](https://mer.vin/news/minimax-music-3-is-open-weight-but-not-open-for-business/).
- No editing/inpainting noted by Sogni; no reference audio in HF card. No benchmarks on model card — [mer.vin](https://mer.vin/news/minimax-music-3-is-open-weight-but-not-open-for-business/).
- License CONFLICT: mer.vin says CC BY-NC 4.0 (commercial use forbidden); Sogni says "Apache-2.0 repack" for ComfyUI version; HF card links a LICENSE without naming it [UNVERIFIED]. (License is covered by another researcher.)
- Hardware conflict: README says 2 CUDA GPUs; HF says 24 GB+ (8 GB with offload).

**SongGeneration 2 / LeVo 2 (Tencent AI Lab)**
- v2-large released 2026-03-01 on HF `tencent/SongGeneration` and GitHub tencent-ailab/SongGeneration; hybrid LM + diffusion, ~4B; up to 4:30; Chinese, English, Spanish, Japanese + others; inputs: structured lyrics + optional text description (genre, gender, instruments, emotion, BPM) or ~10 s reference audio; outputs mix, BGM-only, vocal-only, separated tracks; v2-medium and v2-fast "coming soon" at time of the (secondary) pages; memory 10-28 GB — [gaga.art](https://gaga.art/blog/songgeneration-2/), [HF](https://huggingface.co/tencent/SongGeneration), [GGUF community conversion](https://huggingface.co/ckadirt/LeVo2-GGUF).
- Claimed PER 8.55% vs Mureka v8 9.96%, Suno v5 12.4% (secondary blog, methodology unknown) — [gaga.art](https://gaga.art/blog/songgeneration-2/).
- Original LeVo paper [arXiv 2506.07520](https://arxiv.org/html/2506.07520v2) (NeurIPS 2025). License: Tencent non-commercial per IT-JIM — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/); exact terms not read.

**YuE (v1) and YuE2** (HKUST / M-A-P)
- YuE v1: Jan 2025 (paper [arXiv 2503.08638](https://arxiv.org/pdf/2503.08638)), ~7B, Apache-2.0, about 12x slower than realtime on an RTX 4090 per IT-JIM — [soundgen.ai](https://soundgen.ai/ai-music-models), [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/).
- YuE2-3B: HF `m-a-p/YuE2-3B`, paper arXiv 2609.33757 (as cited by article), repo multimodal-art-projection/YuE; released ~Sep 9-10 2026 (theopenweights) with Neurohive article 2026-09-29; 3.58B Mixture-of-Transformers (28 layers): autoregressive ABC score + semantic tokens, then flow-matching acoustic latents; 48 kHz stereo VAE; 346k h training data (mostly CC0 + synthetic); lyrics with verse/chorus tags + style description; covers via SheetSage2 score transcription, ABC score editable; English and Chinese; 24 GB GPU (peak ~11-14 GiB); 3.6-min song in 71 s on RTX 4090; max duration not stated — [Neurohive](https://neurohive.io/en/state-of-the-art/yue2-open-source-ai-song-generator/), [The Open Weights](https://theopenweights.com/categories/music).
- License CC BY-NC 4.0; creators may sell their songs (added Sep 16), companies need separate license — [Neurohive](https://neurohive.io/en/state-of-the-art/yue2-open-source-ai-song-generator/).

**HeartMuLa** (heartlib)
- 2026-01-14 first release (HeartMuLa-oss-3B, HeartCodec-oss, HeartTranscriptor); 01-20 Apache 2.0; 01-23 RL-tuned 3B + new codec; 02-03 benchmark; 02-13 "happy-new-year" 3B; 04-10 demo spaces; 2026-09-16 MuLaCover (cover/remix repo). 7B NOT released; reference-audio conditioning still TODO; default max 4 min; RTF ~1.0; 3.8k stars, 480 forks, 72 commits; 48 kHz stereo codec at 12.5 Hz — [GitHub heartlib](https://github.com/HeartMuLa/heartlib), paper [arXiv 2601.10547](https://arxiv.org/abs/2601.10547).
- Soundgen.ai-derived search text mentioned a "v2.5 (Sep 2026)" with per-section prompts; NOT found on the GitHub page — [UNVERIFIED/likely unreliable].

**Khala** (Central Conservatory of Music + Tsinghua)
- arXiv 2605.01790 (2026-05-03, v2 2026-07-06); 64-layer RVQ acoustic-token LM, two stages (backbone + super-resolution, 62 fixed steps); ~3.7B total per IT-JIM; 1-10 min songs; weights ~52 GB, 24 GB+ GPU; CC BY-NC 4.0; lyrics + tags or free-text prompt; no inpainting/continuation/stems; README flagged (2026-05-07) a possible precision-related quality issue, still shown after 05-16 — [Lilting](https://lilting.ch/en/articles/khala-music-generation-gpu-notes), [GitHub](https://github.com/Khala-Music-AI/Khala), [HF](https://huggingface.co/liujiafeng/Khala-MusicGeneration-v1.0), [arXiv](https://arxiv.org/abs/2605.01790). (Note: my fetch of arXiv abs 2605.01790 returned a "Shao" label for the same paper; the Khala identification comes from the other sources. Searches also surfaced a "Shao" name for the same arXiv ID; treat as renamed/duplicate title.)

**Muse** (yuhui1038)
- arXiv 2601.03973 (2026-01-07, v3 01-12); Qwen-based LM + discrete audio tokens; abstract said weights "will be released"; IT-JIM lists 0.6B, MIT code, Apache-2.0 weights, MIT data, Chinese-leaning accent on English vocals; fully open training data — [arXiv](https://arxiv.org/abs/2601.03973), [GitHub](https://github.com/yuhui1038/Muse), [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/).

**DiffRhythm / DiffRhythm 2** (ASLP Lab, Xiaomi research)
- DiffRhythm v1 (LRC-timestamped lyrics, 1:35 or 4:45, v1.2 adds edit/continuation), Apache-2.0 — [soundgen.ai](https://soundgen.ai/ai-music-models).
- DiffRhythm 2: [arXiv 2510.22950](https://arxiv.org/pdf/2510.22950) (v3 Feb 2026), block flow matching, 5 Hz VAE, up to 210 s, Apache-2.0; authors admit gap vs Suno v4.5 musicality; baselines included ACE-Step and LeVo; repo github.com/xiaomi-research/diffrhythm2; HF `ASLP-lab/DiffRhythm2` — [HF](https://huggingface.co/ASLP-lab/DiffRhythm2/blob/main/README.md).

**SongBloom** (Tencent AILab)
- AR sketching + diffusion refinement; 150 s checkpoints (Jun 2025), DPO update (Sep 2025); a mirror states the official GitHub/HF repos were deleted by authors and code survives in forks; ecosyste.ms shows 682 stars, last push Dec 2025; no 2026 update found; probable abandoned/superseded by SongGeneration — [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Ftencent-ailab%2FSongBloom), [HF mirror](https://huggingface.co/rtikw/SongBloom). Conflicting evidence on repo status.

**Instrumental-only / non-song (not alternatives for vocals)**
- MusicGen/AudioCraft (2023, ~30 s, weights CC-BY-NC); Stable Audio Open 1.0 (47 s)/Small (11 s); Stable Audio 3.0 (May 2026): Small SFX/Small/Medium open weights (Community License), Medium up to ~6:20, vocals "not verified"; Stability "Demon" real-time engine (2026-05-27); Magenta RealTime MRT2 — [soundgen.ai](https://soundgen.ai/ai-music-models), [The Open Weights](https://theopenweights.com/categories/music).
- SoulX-Singer (2026-02-06): zero-shot singing voice cloning (not song generation) — [The Open Weights](https://theopenweights.com/categories/music).

**Announced but NO verified open weights**
- Qwen-Music (Alibaba): tech report [arXiv 2607.11699](https://arxiv.org/abs/2607.11699) (2026-07-13, v3 2026-09-16); 25 Hz semantic tokenizer + LLM with melody planning + renderer; SOTA on 13/16 metrics; beats Suno V5.5/V5/MiniMax Cover on melody preservation (self-reported); HF papers comments asking for weights; no HF model page found — [aiweekly](https://aiweekly.co/alerts/qwen-music-report-5m-training-hours-sota-on-13-of-16-metrics), [The Open Weights](https://theopenweights.com/news/qwen-music-66sf). The Open Weights lists it under "open" category with license "QWEN" but does not confirm download [UNVERIFIED].
- StepAudio 3 Music (StepFun, 2026-09-10): ABC-notation planning, up to 5:30, 48 kHz; described as hosted preview API (`stepaudio-3-music-preview`); open weights unconfirmed — [arXiv 2609.16034](https://huggingface.co/papers/2609.16034), [WaveSpeed](https://wavespeed.ai/blog/audio-and-voice-models/stepaudio-3-model-guide/).
- FullDiT ("Beyond Reconstruction", [arXiv 2608.08787](https://arxiv.org/abs/2608.08787), 2026-08-09): claims top-3 on Artificial Analysis Music with Vocals leaderboard; weights/params not stated.
- Open-Qwen-Music (independent reconstruction, [arXiv 2609.31652](https://arxiv.org/html/2609.31652v1)): authors say weights on GitHub; not examined [UNVERIFIED].
- Not found: any open-weights Seed-Music (ByteDance), Suno/Udio clone beyond the above.

### Inferences
- The open field consolidated around ACE-Step 1.5 XL (permissive, tooling-rich), MiniMax-Music3 and LeVo 2 (quality), YuE2 (claims near Suno v5, NC license).
- Nothing in the retrieved sources indicates an ACE-Step successor in 2026; XL (Apr) is the latest.

### Gaps
- GitHub last-commit dates and issue health unreadable for all repos. HF download counts/trending not retrieved. Reddit/LocalLLaMA/StableDiffusion threads not retrievable. SongGeneration v2-medium/v2-fast shipping status unverified. HeartMuLa "v2.5" unverified. Qwen-Music/StepAudio 3 Music weights unverified. Exact licenses (MiniMax, LeVo 2) unverified.

## Which are described as better than ACE-Step 1.5, and on what axes?

### Takeaway
No independent benchmark shows a clean win over ACE-Step 1.5. Reviewers rate MiniMax-Music3 and LeVo 2 higher on audio fidelity/mix, ACE-Step higher on speed, creativity, controls and tooling.

### Cited Findings
- MiniMax-Music3 vs ACE-Step 1.5 XL Turbo (Sogni, a hosting vendor): Music3 better mixing, instrument separation, drums/bass, polish; vocals mixed (smoother vs emotionally flatter); weaker on metal/rock/EDM/experimental; ACE-Step more creative structures, broader languages, finer control, editing; ~25 s vs ~4-5 min for 2.5-min song on RTX 5090; ~23x cost difference; quote "AceStep is ahead in creativity, MiniMax has better sound quality" — [Sogni](https://blog.sogni.ai/blogs/minimax-music3-vs-ace-step-15-xl/).
- IT-JIM hands-on (8 models): LeVo 2 best audio quality in all three prompts and avoids ACE-Step 1.5's "metallic shimmer"; Muse judged better than 1.5 on general audio in cells tested; ACE-Step 1.5 best for fine-tuning/remixing/tooling; ACE-Step v1 cleaner than 1.5 but weaker musicality; HeartMuLa generic smoothed pop; YuE slow; DiffRhythm 2 artificial audio, authors concede vocal gap vs ACE-Step and LeVo; Khala unstable — [IT-JIM](https://www.it-jim.com/blog/best-open-source-ai-music-generator/).
- YuE2 authors: best-of-8 beats Suno v4.5 57.3% vs 30.5%, ~ties Suno v5 (40.4 vs 39.9); SongBench 6.96 vs Suno v5 6.87 (not significant); lyric PER 0.0844, worse than Suno v4.5 (0.0580) and MiniMax Music 3 (0.0627); ACE-Step 1.5 appears only in a cover table — [Neurohive](https://neurohive.io/en/state-of-the-art/yue2-open-source-ai-song-generator/).
- LeVo 2 PER claim 8.55% (author-claimed via secondary blog) — [gaga.art](https://gaga.art/blog/songgeneration-2/).
- HeartMuLa: internal 7B (unreleased) claimed "comparable to Suno"; released 3B not compared to ACE-Step — [GitHub](https://github.com/HeartMuLa/heartlib).
- Search result claimed Shao/Khala paper reports arena where it ranks first among open models with ACE-Step 1.5 second on Elo; I could NOT verify in the fetched arXiv abstract — [UNVERIFIED], [arXiv](https://arxiv.org/abs/2605.01790).
- ACE-Step authors' own claim XL surpasses Suno v5 on metrics — [Techno-Edge](https://www.techno-edge.net/article/2026/04/13/4986.html).

### Inferences
- Fidelity/mix: MiniMax-Music3, LeVo 2. Speed/cost/controls/editing/duration (10 min): ACE-Step. Lyric intelligibility: MiniMax and LeVo 2 claim stronger than YuE2.

### Gaps
- No peer-reviewed or blind third-party head-to-head including all of ACE-Step 1.5 XL, MiniMax-Music3, LeVo 2, YuE2. Artificial Analysis open-model standings not retrieved.

## Which are actively maintained vs abandoned?

### Takeaway
Active in 2026: ACE-Step (Apr XL), HeartMuLa (updates to Sep 2026), MiniMax-Music3 (Aug), YuE2 (Sep), LeVo 2 (Mar; pending variants). Stale/risky: SongBloom (repos reportedly deleted; last activity Dec 2025), DiffRhythm 2 (no 2026 model update seen), Khala (quality bug notice), Muse (unclear release).

### Cited Findings
- ACE-Step: 1,410 commits, 101 open issues — [GitHub](https://github.com/ACE-Step/ACE-Step-1.5).
- HeartMuLa: dated releases Jan-Sep 2026; 7B and reference audio still pending — [GitHub](https://github.com/HeartMuLa/heartlib).
- SongBloom: see above conflicting status — [ecosyste.ms](https://awesome.ecosyste.ms/projects/github.com%2Ftencent-ailab%2FSongBloom).
- LeVo 2 TODOs (codec/VAE, finetune scripts, evaluator, v2-fast/medium) as of a May 2026 third-party tracker — [vllm-omni issue](https://goodfirstissue.org/vllm-project/vllm-omni/issues/3390).

### Inferences
- Abandonment assessments are inferred from release cadence only; commit dates not read.

### Gaps
- Real last-commit dates, issue response times not obtained.
