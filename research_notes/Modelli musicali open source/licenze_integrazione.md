# Open-weight song models: licenses, maturity, integration effort (self-hosted Discord bot)

Date of research: 2026-11-19. Not legal advice; terms are reported as found. Source quality: GitHub/HF APIs and READMEs (primary) vs blogs (secondary, marked).

## 1. License of code and weights, and whether hobby Discord use is allowed

### Takeaway
ACE-Step 1.5 / XL (MIT), HeartMuLa (Apache-2.0, code and weights), DiffRhythm 1 and 2 (Apache-2.0) and YuE v1 (Apache-2.0) are permissive. YuE2 weights are CC BY-NC 4.0 with a creator carve-out for individuals (a hobby bot looks fine, per the README text). SongGeneration/LeVo and SongBloom licenses are custom/"other" and I could NOT read the license text: unverified.

### Cited Findings
- ACE-Step 1.5 code: "MIT License" (SPDX MIT) per GitHub API; repo pushed 2026-11-08 — [GitHub API](https://api.github.com/repos/ace-step/ACE-Step-1.5)
- ACE-Step weights (1.5 and XL turbo): HF metadata `license: mit` — [Ace-Step1.5](https://huggingface.co/api/models/ACE-Step/Ace-Step1.5), [xl-turbo](https://huggingface.co/api/models/ACE-Step/acestep-v15-xl-turbo)
- ACE-Step XL SFT model card: "Trained on legally compliant datasets" (licensed music, royalty-free/public-domain music, synthetic MIDI-to-audio); says generated music "can be used for commercial purposes"; no extra restrictions stated beyond MIT tag; no watermark requirement found on the page — [XL SFT card](https://huggingface.co/ACE-Step/acestep-v15-xl-sft)
- ACE-Step bundled text encoder Qwen3-Embedding-0.6B is Apache-2.0; LM models are Qwen3-based (their licence not separately checked) — [diffusers card via search](https://huggingface.co/ACE-Step/acestep-v15-xl-sft-diffusers); [README](https://github.com/ace-step/ACE-Step-1.5)
- HeartMuLa: code "licensed under the Apache 2.0 License"; a 20 Jan 2026 update moved the repo AND related weights to Apache 2.0 — [heartlib README](https://github.com/HeartMuLa/heartlib); HF metadata for HeartMuLa-oss-3B `apache-2.0` — [HF API](https://huggingface.co/api/models/HeartMuLa/HeartMuLa-oss-3B)
- YuE v1: code Apache License 2.0 (LICENSE file starts "Apache License Version 2.0, January 2004"); HF weights YuE-s1-7B `apache-2.0` — [LICENSE](https://raw.githubusercontent.com/multimodal-art-projection/YuE/main/LICENSE), [HF API](https://huggingface.co/api/models/m-a-p/YuE-s1-7B-anneal-en-cot)
- YuE2 (Sept 2026): code/docs Apache 2.0; weights "CC BY-NC 4.0 with additional creator permission". README: personal users, creators and musicians may use YuE2 and monetize outputs with no fees/royalties; academic use free; "Companies must contact the authors for a commercial weights license" — [YuE README](https://github.com/multimodal-art-projection/YuE); HF metadata `cc-by-nc-4.0` — [m-a-p/YuE2-3B](https://huggingface.co/api/models/m-a-p/YuE2-3B). (The exact carve-out wording is from a README summary, not the license file; read it before relying on it.)
- DiffRhythm 1: "code and DiT weights are released under the Apache License 2.0"; VAE weights license not stated on the page — [DiffRhythm README](https://github.com/ASLP-lab/DiffRhythm)
- DiffRhythm 2: "released under the Apache License 2.0" (code and weights), model card `apache-2.0` — [HF ASLP-lab/DiffRhythm2](https://huggingface.co/ASLP-lab/DiffRhythm2); GitHub API Apache-2.0 — [API](https://api.github.com/repos/ASLP-lab/DiffRhythm2)
- SongGeneration/LeVo (Tencent): GitHub-mirror page lists "Other license"; a third-party blog says only "Review the LICENSE file in the official GitHub repository before commercial use" and does not name a license — [gaga.art](https://gaga.art/blog/songgeneration-2/). HF metadata for lglg666/SongGeneration-base: license `unknown` — [HF API](https://huggingface.co/api/models/lglg666/SongGeneration-base). Official tencent/SongGeneration HF page returned 401 and github.com/tencent-ailab/SongGeneration returned 404 from my tools (API too), so UNVERIFIED.
- SongBloom: HF CypressYang/SongBloom_long license `other`, gated "manual" — [HF API](https://huggingface.co/api/models/CypressYang/SongBloom_long). A mirror (rtikw) claims Apache-2.0 but says the official repos were deleted by the authors; conflicting and unverified — [rtikw mirror](https://huggingface.co/rtikw/SongBloom). github.com/Cypress-Yang/SongBloom and tencent-ailab/SongBloom returned 404 to me.
- Roundup (secondary, checked 2026-10-28): lists ACE-Step 1.5 MIT, YuE v1 Apache-2.0, YuE2 CC BY-NC 4.0 with carve-out, HeartMuLa Apache-2.0, DiffRhythm Apache-2.0; says it could not find SongGeneration/SongBloom licenses either — [soundgen.ai](https://soundgen.ai/ai-music-models)

### Inferences
- Hobby bot for a small community: clearly fine for ACE-Step, HeartMuLa, DiffRhythm 1/2, YuE v1. YuE2 probably fine (individual use allowed) but a Discord bot run for others is a grey zone for "NC"; ask authors if it ever monetizes.
- Apache-2.0/MIT carry attribution/notice duties only on redistribution of the code; nothing found about audio watermark requirements for any model (not exhaustively checked).
- Avoid SongGeneration and SongBloom until the LICENSE text is read directly in a browser.

### Gaps
- Exact text of SongGeneration/LeVo and SongBloom licenses (repos/pages inaccessible to my tools).
- Whether any model has a watermark requirement: not found, not verified in each license.
- YuE2 carve-out verbatim text.

## 2. API / CLI / UI and ease of calling from the bot

### Takeaway
Only ACE-Step ships an async REST server that matches the bot today. HeartMuLa, YuE/YuE2, DiffRhythm, SongGeneration are CLI/Python-pipeline projects: integration means a subprocess or a small self-written wrapper service.

### Cited Findings
- ACE-Step: HTTP async API `uv run acestep-api` on port 8001; flow POST /release_task -> POST /query_result (status 0 running, 1 ok, 2 fail) -> GET /v1/audio?path=; optional auth via `ACESTEP_API_KEY` / Bearer; also /v1/init (model switching) and /v1/training/* — [API.md summary](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/docs/en/API.md), [README](https://github.com/ace-step/ACE-Step-1.5)
- ACE-Step also has Gradio UI, Docker (Dockerfile, compose, Jetson), ROCm/XPU requirement files and launch scripts, community ComfyUI nodes, VST3 plugin — [README](https://github.com/ace-step/ACE-Step-1.5)
- Local bot already uses this REST flow (`/release_task`, `/query_result`, `/v1/audio`), starts `acestep-api` itself with `--init-llm --lm-model-path`, sends `prompt`, `lyrics`, `audio_duration`, `audio_format`, `use_random_seed`, `task_type=text2music`, `thinking`, `use_cot_caption=False` — local file /home/drift/git/DriftBot/src/cogs/ace_step_cog.py
- HeartMuLa: CLI `python ./examples/run_music_generation.py --model_path=./ckpt --version="3B"`; no documented programmatic API; HF demo spaces; community ComfyUI node; "pip install -e ." — [heartlib](https://github.com/HeartMuLa/heartlib)
- YuE2: Python `YuE2Pipeline.from_pretrained("m-a-p/YuE2-3B", device="cuda")` then `pipe(**request)`, staged API (plan/generate_semantic/synthesize/decode), CLI `examples/generate.py`, native ComfyUI nodes; no Gradio mentioned — [YuE README](https://github.com/multimodal-art-projection/YuE)
- DiffRhythm: bash CLI scripts, Docker folder, HF Space; Gradio listed as unchecked TODO; needs espeak-ng — [DiffRhythm README](https://github.com/ASLP-lab/DiffRhythm). DiffRhythm 2: `bash inference.sh`, espeak-ng, weights auto-download — [HF card](https://huggingface.co/ASLP-lab/DiffRhythm2)
- SongGeneration: local run by cloning repo, installing requirements, downloading weights + runtime folder, writing a .jsonl input and running a generate script; HF Space demo (secondary source) — [gaga.art](https://gaga.art/blog/songgeneration-2/)
- SongBloom: HF card only says "use the `songbloom` library"; no usage details retrievable — [HF card](https://huggingface.co/CypressYang/SongBloom_long/blob/main/README.md)

### Inferences
- Swapping to a non-ACE model = new wrapper (FastAPI around a Python pipeline, or `asyncio.create_subprocess_exec` on the CLI). HeartMuLa and YuE2 are the easiest because they have importable Python entry points; model load time makes a resident wrapper service preferable to per-request subprocess.
- ComfyUI could act as an HTTP backend for HeartMuLa/YuE2/ACE-Step via its API, but that was not researched.

### Gaps
- Whether any non-ACE project has an OpenAI/REST-style server (none found in the pages read).

## 3. Inputs and outputs (lyrics tags, style prompt, reference audio, duration, format, seeds)

### Takeaway
All candidates take lyrics + a style description; ACE-Step is the most controllable (seed, formats, reference/cover/repaint, up to 10 min). Others top out at 2.5 to 4.75 minutes.

### Cited Findings
- ACE-Step: `prompt`/`caption`, `lyrics`, `vocal_language`, `task_type` (text2music, cover, repaint, extract, lego/complete on XL base), `audio_format` flac/mp3/opus/aac/wav/wav32, `inference_steps` default 8, `guidance_scale` (base only), `batch_size` max 8, `use_random_seed`/`seed`, reference audio via `reference_audio_path` or multipart upload, `audio_cover_strength`; duration 10 s to 10 min; sample rate not stated in the pages read — [API.md](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/docs/en/API.md), [README](https://github.com/ace-step/ACE-Step-1.5)
- HeartMuLa: lyrics text file with [Verse]/[Chorus] markers, comma-separated tags file; default max 240000 ms (4 min); MP3 output by default; 48 kHz stereo via HeartCodec; defaults top-k 50, temp 1.0, CFG 1.5; RTF about 1.0; only 3B released, 7B not yet; no reference-audio input documented (MuLaCover released 2026-09-16 for covers) — [heartlib](https://github.com/HeartMuLa/heartlib)
- YuE2: lyrics + style prompt, optional ABC score, `cot` full/melody/off, seed, cover from reference recording; 48 kHz stereo output; duration not stated — [YuE README](https://github.com/multimodal-art-projection/YuE)
- DiffRhythm: LRC lyrics with timestamps, text style prompt or reference WAV, instrumental mode; base 1m35s, full 4m45s (285 s); output format/sample rate not stated — [DiffRhythm README](https://github.com/ASLP-lab/DiffRhythm)
- DiffRhythm 2: lyrics files + reference WAV, "full-length songs", no limit stated — [HF card](https://huggingface.co/ASLP-lab/DiffRhythm2)
- SongGeneration variants: base 2m30s (Chinese only), base-new 2m30s (zh/en), base-full / large / v2-large 4m30s; v2 multilingual; inputs: section-tagged lyrics in .jsonl, optional keyword description (gender, timbre, genre, emotion, instruments, BPM), optional 10 s audio prompt; flags for instrumental, vocals-only, separated tracks — [gaga.art](https://gaga.art/blog/songgeneration-2/) (secondary)
- Seeds: ACE-Step documented; YuE2 lists seed; HeartMuLa/DiffRhythm/SongGeneration seed control not documented on pages read.

### Inferences
- The bot's lyrics+section-tag LLM pipeline maps directly to ACE-Step, HeartMuLa, SongGeneration and YuE; DiffRhythm would need LRC timestamps generated.

### Gaps
- Output sample rate for ACE-Step, DiffRhythm, SongGeneration (not stated in pages read).
- SongBloom I/O details (page unreadable); from memory its design uses a 10 s prompt, but that is NOT verified here.

## 4. Maturity (activity, issues, docs, Docker, dependency pins vs PyTorch 2.9 ROCm 6.4)

### Takeaway
ACE-Step and HeartMuLa are actively maintained (pushes 2026-11-08 and 2026-11-19). DiffRhythm 1/2 are stale since Nov 2025. YuE is active (2026-11-01). ACE-Step pins CUDA wheels, so ROCm needs its separate ROCm requirements path.

### Cited Findings
- Last push / open issues+PRs / stars (GitHub API, 2026-11-19): ACE-Step-1.5 2026-11-08, 173, 14,961; YuE 2026-11-01, 47, 13,600; HeartMuLa/heartlib 2026-11-19, 100, 3,807; DiffRhythm 2025-11-27, 61, 2,369; DiffRhythm2 2025-11-09, 0, 184 — [ACE-Step](https://api.github.com/repos/ace-step/ACE-Step-1.5), [YuE](https://api.github.com/repos/multimodal-art-projection/YuE), [heartlib](https://api.github.com/repos/HeartMuLa/heartlib), [DiffRhythm](https://api.github.com/repos/ASLP-lab/DiffRhythm), [DiffRhythm2](https://api.github.com/repos/ASLP-lab/DiffRhythm2). (open_issues_count includes PRs.)
- SongGeneration and SongBloom GitHub repos returned 404 via API; SongBloom mirror says official repos were deleted — status unverified — [rtikw mirror](https://huggingface.co/rtikw/SongBloom)
- ACE-Step: about 1,410 commits at fetch time; no GitHub Releases entries on the page (tag v0.1.6 appeared in search); Python >=3.11,<3.13; pyproject pins `torch==2.10.0+cu128` on linux x86_64 (cu128 index), `transformers>=4.51.0,<4.58.0`, `diffusers>=0.37.0`, `torchao>=0.16.0,<0.17.0`; separate ROCm requirements file and launch scripts exist; Dockerfile and compose present — [pyproject.toml](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/main/pyproject.toml), [README](https://github.com/ace-step/ACE-Step-1.5)
- ACE-Step paper arXiv 2602.00744 — [README](https://github.com/ace-step/ACE-Step-1.5)
- ACE-Step VRAM: under 4 GB claimed for small tiers; 6 GB tier uses turbo, no LM, INT8, CPU offload; XL needs >=12 GB with offload/INT8, >=20 GB without; 24 GB for XL + 4B LM — [README](https://github.com/ace-step/ACE-Step-1.5), [XL SFT card](https://huggingface.co/ACE-Step/acestep-v15-xl-sft)
- HeartMuLa: 72 commits at fetch, Python 3.10 recommended, torch/transformers pins not shown, ROCm not mentioned; use `--lazy_load` or two GPUs for memory — [heartlib](https://github.com/HeartMuLa/heartlib)
- YuE2: Linux, Python 3.12, NVIDIA GPU with BF16, 24 GB VRAM stated; 229 commits — [YuE README](https://github.com/multimodal-art-projection/YuE)
- DiffRhythm: Python 3.10, espeak-ng, base needs min 8 GB VRAM with `--chunked`; 62 commits — [README](https://github.com/ASLP-lab/DiffRhythm)
- SongGeneration VRAM: base/base-new 10 GB (16 GB with audio prompt), base-full 12/18, large and v2-large 22/28, v2-medium 12/18; Linux, NVIDIA, CUDA 11.8+ — [gaga.art](https://gaga.art/blog/songgeneration-2/) (secondary)

### Inferences
- Bot environment (PyTorch 2.9 ROCm 6.4, 8 GB VRAM per the cog comments): ACE-Step is the only one with documented ROCm support; its cu128 pins are bypassed via the ROCm path (already working in this bot). YuE2 (24 GB, BF16 NVIDIA stated) and SongGeneration large (22 GB) are out of reach on 8 GB. HeartMuLa 3B at fp16 is plausible on small GPUs only with lazy_load, but ROCm untested here.
- Upstream pins I did not read: HeartMuLa/YuE/DiffRhythm requirements.txt; clash risk with torch 2.9 / transformers is unknown.

### Gaps
- Contributor counts (pages did not render them), issue responsiveness, requirements.txt contents of non-ACE projects, ROCm compatibility of any non-ACE model.

## 5. Newer ACE-Step versions and other 2026 releases

### Takeaway
ACE-Step 1.5 XL (4B DiT; xl-base, xl-sft, xl-turbo) was released 2026-04-02 under MIT. No "ACE-Step 2" found. New 2026 competitors: HeartMuLa (Jan), SongGeneration v2 (Mar), YuE2 (Sept), MuLaCover (Sept).

### Cited Findings
- ACE-Step 1.5 XL released 2026-04-02: xl-base (50 steps, adds extract/lego/complete), xl-sft (50 steps), xl-turbo (8 steps); LM sizes 0.6B/1.7B/4B (Qwen3-based) — [README](https://github.com/ace-step/ACE-Step-1.5); date also in [Gigazine](https://www.gigazine.net/gsc_news/en/20260409-ace-step-1-5-xl/); [ComfyUI blog](https://blog.comfy.org/p/ace-step-15-xl-commercial-grade-music) (secondary, states MIT)
- Other DiT variants: base, sft, turbo (8 steps) — [README](https://github.com/ace-step/ACE-Step-1.5)
- HeartMuLa timeline: 2026-01-14 first release, 01-20 Apache change, 01-23 RL model, 02-13 happy-new-year model, 09-16 MuLaCover — [heartlib](https://github.com/HeartMuLa/heartlib)
- SongGeneration-v2-large public release 2026-03-01; v2-medium / v2-fast "coming soon" — [gaga.art](https://gaga.art/blog/songgeneration-2/) (secondary)
- YuE2-3B: tech report 2026-09-26, HF last modified 2026-10-06 — [YuE README](https://github.com/multimodal-art-projection/YuE), [HF API](https://huggingface.co/api/models/m-a-p/YuE2-3B)
- Other open-weight music models in 2026 listed by a roundup (licenses secondary/unverified): Stable Audio 3.0 Small/Medium (Stability Community License, free under $1M revenue), MiniMax Music 3 (license not verified), Magenta RealTime (instrumental) — [soundgen.ai](https://soundgen.ai/ai-music-models)

### Inferences
- XL (4B) needs much more VRAM than the bot's 8 GB target; keep 1.5 turbo + 0.6B LM for the bot, XL only if hardware changes.

### Gaps
- No search surfaced an ACE-Step 2.x announcement; absence is not proof. Did not verify Stable Audio 3 / MiniMax Music 3 first-hand (not song-with-vocals models in the verified sense).

## 6. Overall: practical vs research-only

### Takeaway
Practical today: ACE-Step 1.5 (already integrated, REST, ROCm, MIT). Realistic second backend: HeartMuLa 3B (Apache-2.0, 4 min, 48 kHz, CLI only). Others are demos/hard for this setup.

### Cited Findings (summary table from sources above)
| Model | Code / weights license | Interface | Fit for 8 GB ROCm bot |
|---|---|---|---|
| ACE-Step 1.5 / XL | MIT / MIT | REST server, Gradio, Docker | Yes (1.5 turbo); XL no |
| HeartMuLa 3B | Apache-2.0 / Apache-2.0 | CLI, ComfyUI (community) | Maybe, untested; needs wrapper |
| YuE v1 | Apache-2.0 / Apache-2.0 | CLI | Heavy (7B), not checked |
| YuE2 3B | Apache-2.0 / CC BY-NC 4.0 + creator permission | Python pipeline, CLI, ComfyUI | No (24 GB, NVIDIA BF16) |
| DiffRhythm 1/2 | Apache-2.0 / Apache-2.0 | CLI scripts, Docker | Possible (8 GB min base) but stale, lower quality unverified |
| SongGeneration / LeVo | "Other" / unknown (unverified) | CLI + jsonl | No (10-22 GB, CUDA) |
| SongBloom | "other", gated (unverified) | library | Unclear, repos possibly removed |

### Inferences
- Recommendation: keep ACE-Step as the backend; if a second engine is wanted, prototype HeartMuLa behind a tiny FastAPI wrapper exposing the same 3-call shape, after testing ROCm and VRAM.

### Gaps
- Quality comparisons between models were out of scope and not researched.
