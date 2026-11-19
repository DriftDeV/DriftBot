# Running open-weight song-generation models as on-demand local services for DriftBot (research date 2026-11-19)

Machine facts used throughout (read locally): GPU is AMD Navi 23 / RX 6600 (`lspci`, 8 GB class, RDNA2 gfx1032); bot `.env` sets `HSA_OVERRIDE_GFX_VERSION=10.3.0` (/home/drift/git/DriftBot/.env:2); 31 GB RAM; /home has 336 GB free. Bot torch pins in /home/drift/git/DriftBot/pyproject.toml:51 (`torch>=2.6.0`) and :87 (`torch==2.6.0`, ROCm 6.2.4 wheel comment at :84); the task brief says the live env is PyTorch 2.9 ROCm 6.4 (not verified here, nothing was run). Nothing was installed or executed; all findings are from source/README reading.

## 1. ACE-Step 1.5 XL: selecting xl-turbo / xl-sft / xl-base and registering several DiT models

### Takeaway
Same server, no new service. Pick the primary DiT with `ACESTEP_CONFIG_PATH=acestep-v15-xl-turbo` (or `-xl-sft` / `-xl-base`), optionally register two more with `ACESTEP_CONFIG_PATH2/3`, and choose per request with the `model` field of `/release_task`. XL is a 4B DiT (about 9 GB of bf16 weights), so it does not fit the 8 GB RX 6600 in practice (project's own tier table marks 6-8 GB as XL unsupported).

### Cited Findings
- Local checkpoints dir currently has only `acestep-v15-turbo`, `acestep-5Hz-lm-0.6B`, `acestep-5Hz-lm-1.7B`, `Qwen3-Embedding-0.6B`, `vae`; no XL downloaded — `ls /home/drift/git/ACE-Step-1.5/checkpoints`.
- XL release 2026-04-02, three variants xl-base / xl-sft / xl-turbo; needs >=12 GB VRAM with offload, >=20 GB recommended; weights ~9 GB bf16 vs ~4.7 GB for 2B — /home/drift/git/ACE-Step-1.5/README.md:26, :140, :266.
- Variant matrix: xl-base 50 steps (supports extract/lego/complete), xl-sft 50 steps, xl-turbo 8 steps; quality "Very High" for sft/turbo — README.md:270-272.
- Model-to-code map and HF repos: `acestep-v15-xl-{base,sft,turbo}` -> `ACE-Step/acestep-v15-xl-{base,sft,turbo}`; XL has its own model code under `acestep/models/xl_*/` — /home/drift/git/ACE-Step-1.5/acestep/model_downloader.py:39-42 and :300-303.
- Primary model env var: `ACESTEP_CONFIG_PATH` default `acestep-v15-turbo` — acestep/api/startup_model_init.py:49; docs/en/API.md:744-746 lists `ACESTEP_CONFIG_PATH`, `ACESTEP_CONFIG_PATH2`, `ACESTEP_CONFIG_PATH3`.
- Multi-DiT registration: each of PATH2 / PATH3 that is set creates an extra handler (`handler2`, `handler3`) at startup — acestep/api/lifespan_runtime.py:100-113. Slots 2/3 are initialised on demand via `POST /v1/init {"model": "...", "slot": 2}`; unset slot returns an error "Restart the API with ACESTEP_CONFIG_PATH2" — acestep/api/http/model_init_service.py:38-45; docs/en/API.md:575-632 (section 9).
- Per-request selection: `/release_task` accepts `model` (aliases `model_name`, `modelName`, `dit_model`, `ditModel`) — acestep/api/http/release_task_param_parser.py:19. `select_generation_handler` returns handler2/3 only if `_initialized2/3` is true and the name matches — acestep/api/job_model_selection.py:120-175. If it matches none, it falls back to the primary and logs.
- Optional hot-swap: with `ACESTEP_ON_DEMAND_MODEL_LOAD=true` (and single `ACESTEP_QUEUE_WORKERS` / `ACESTEP_API_WORKERS`) an unknown requested model is downloaded and swapped into the primary handler at request time — acestep/api/job_model_selection.py:30-47, :49-74, :175-190.
- Tier table: 6-8 GB = Tier 3, XL not supported (❌), 0.6B LM max; 12-16 GB XL marginal; 16-20 GB XL with offload; >=20 GB XL fits — docs/en/GPU_COMPATIBILITY.md:5-18. VRAM profile constants `dit_xl_turbo: 9.0` GB — acestep/gpu_config.py:151-152.
- Download of a sub-model: `SUBMODEL_REGISTRY` maps names to HF repos and the server auto-fetches via `ensure_model_downloaded` — acestep/model_downloader.py:285-303 (exact CLI command for manual download not verified).
- Offload knobs: `ACESTEP_OFFLOAD_TO_CPU`, `ACESTEP_OFFLOAD_DIT_TO_CPU` — docs/en/API.md:749-750. ROCm dtype override `ACESTEP_ROCM_DTYPE` (default float32) — acestep/core/generation/handler/init_service_orchestrator.py:30-34.
- Current bot integration launches `venv_rocm/bin/python -c "from acestep.api_server import main; main()" --host 127.0.0.1 --port N [--init-llm --lm-model-path ...]` with env `ACESTEP_LM_BACKEND=pt`, `MIOPEN_FIND_MODE=FAST`, `ACESTEP_ROCM_DTYPE=bfloat16`, `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True`; request body keys `prompt, lyrics, vocal_language, audio_duration, batch_size, audio_format, use_random_seed, task_type, thinking, lm_temperature, inference_steps(8), use_cot_*`, optional `bpm, key_scale, time_signature` — /home/drift/git/DriftBot/src/cogs/ace_step_cog.py:218-256, :396-440. Bot has no `model` key today.

### Inferences
- To try XL through the existing cog: add env `ACESTEP_CONFIG_PATH=acestep-v15-xl-turbo` in the Popen env (ace_step_cog.py ~:413) and keep `inference_steps: 8`; for xl-sft/xl-base set `inference_steps` ~50 and likely different guidance (unverified), so quality tiers map to: fast = turbo (8), standard = xl-turbo (8), high = xl-sft (50). Slot 2 = `ACESTEP_CONFIG_PATH2=acestep-v15-xl-sft` plus `POST /v1/init {"model":"acestep-v15-xl-sft","slot":2}` before use, or `ACESTEP_ON_DEMAND_MODEL_LOAD=true` and pass `"model"` in `/release_task` (swap cost = full reload).
- On the 8 GB RX 6600, XL needs CPU offload plus INT8 quantisation, which the project itself marks unsupported below 12 GB; expect OOM or very slow runs. Realistic path: keep 2B turbo locally; run XL only on a >=16 GB card.
- No XL-specific dependency beyond existing ACE-Step venv (code lives inside the repo), so XL coexists with the current `venv_rocm`.

### Gaps
- Exact disk size of the three XL repos and exact `inference_steps`/`guidance` recommended defaults for sft/base not read (README says 50 steps; guidance scale not checked).
- No measured XL cold-start or RTF on RDNA2; no issue search for XL on ROCm done.

## 2. HeartMuLa 3B (heartlib)

### Takeaway
Cleanest candidate to wrap: a small pure-Python pipeline with a callable class, Apache-2.0, 8 GB-friendly in principle via `lazy_load`, but it pins several packages (numpy 2.0.2, transformers 4.57.0, torchao 0.9.0, torchtune 0.4.0, bitsandbytes 0.49.0) so use an isolated venv with the ROCm torch wheel. No seed argument and `ref_audio` raises `NotImplementedError`.

### Cited Findings
- Repo https://github.com/HeartMuLa/heartlib ; install `pip install -e .`, recommended Python 3.10 — [README](https://github.com/HeartMuLa/heartlib).
- Dependency pins: `numpy==2.0.2`, `torch>=2.4,<2.11`, `torchaudio>=2.4,<2.11`, `torchtune==0.4.0`, `torchao==0.9.0`, `torchvision>=0.19,<0.26`, `transformers==4.57.0`, `tokenizers==0.22.1`, `accelerate==1.12.0`, `bitsandbytes==0.49.0`, `vector-quantize-pytorch==1.27.15`, `modelscope==1.33.0`, `einops==0.8.1`, `soundfile`; requires-python >=3.9 — [pyproject.toml](https://raw.githubusercontent.com/HeartMuLa/heartlib/main/pyproject.toml). No triton, flash-attn or vLLM pin.
- Downloads: `hf download --local-dir './ckpt' 'HeartMuLa/HeartMuLaGen'`, `hf download --local-dir './ckpt/HeartMuLa-oss-3B' 'HeartMuLa/HeartMuLa-oss-3B-happy-new-year'`, `hf download --local-dir './ckpt/HeartCodec-oss' HeartMuLa/HeartCodec-oss-20260123`; expected layout `ckpt/{HeartMuLa-oss-3B,HeartCodec-oss,config.json,gen_config.json,tokenizer.json}` — [README](https://github.com/HeartMuLa/heartlib). Pipeline asserts these paths — music_generation.py:15-39 (file fetched from [source](https://raw.githubusercontent.com/HeartMuLa/heartlib/main/src/heartlib/pipelines/music_generation.py), line numbers refer to that file).
- CLI: `python ./examples/run_music_generation.py --model_path=./ckpt --version="3B"`; flags `--lyrics` (file), `--tags` (file), `--save_path`, `--max_audio_length_ms` (240000), `--topk 50`, `--temperature 1.0`, `--cfg_scale` (README says 1.5, script default is 3.0 — conflict, the script is authoritative), `--mula_device/--codec_device`, `--mula_dtype` bf16, `--codec_dtype` fp32, `--lazy_load` — [run_music_generation.py](https://raw.githubusercontent.com/HeartMuLa/heartlib/main/examples/run_music_generation.py):34-51.
- Python API: `HeartMuLaGenPipeline.from_pretrained(pretrained_path, device={"mula":..., "codec":...}|torch.device, dtype={...}|torch.dtype, version="3B", lazy_load=False)`, then `pipe({"lyrics": str_or_path, "tags": str_or_path}, max_audio_length_ms=, save_path=, topk=, temperature=, cfg_scale=)` inside `torch.no_grad()` — music_generation.py:361-400 and run_music_generation.py:54-80. Strings are accepted directly (if not a file path): music_generation.py:217-220, :244-249. Tags are lower-cased and wrapped in `<tag>…</tag>`; lyrics are lower-cased (:222-227, :250).
- Output: `torchaudio.save(save_path, wav, 48000)` — format follows the extension (mp3 default) — music_generation.py:355-359 (mp3/flac backend availability in torchaudio not checked).
- No `seed` parameter anywhere in `_sanitize_parameters` (music_generation.py:200-211); sampling uses torch RNG so `torch.manual_seed()` before the call is the only control (inference).
- `ref_audio` is not supported: `raise NotImplementedError("ref_audio is not supported yet.")` — music_generation.py:235-238. README roadmap lists reference-audio conditioning as future; a separate MuLaCover release (2026-09-16) handles covers — [README](https://github.com/HeartMuLa/heartlib).
- Residency: `lazy_load=False` keeps HeartMuLa and HeartCodec loaded (music_generation.py:116-130); `lazy_load=True` loads on first use and deletes + `empty_cache()` after generation and again after decode (:148-198, :352, :358). Splitting on two devices forces lazy_load off (:60-65). `torch.compile(dynamic=True)` is applied to backbone and decoder on every (re)load, with try/except fallback (:133-146) — adds compile time on each lazy load.
- Length: 80 ms per frame (`max_audio_frames = max_audio_length_ms // 80`, :331); loop breaks on EOS (:348). README speed note: RTF about 1.0 — [README](https://github.com/HeartMuLa/heartlib).
- License Apache-2.0 for repo and weights (2026-01-20 note) — [README](https://github.com/HeartMuLa/heartlib).
- Existing community ComfyUI node mentioned in release notes (no URL/details read) — [README](https://github.com/HeartMuLa/heartlib).
- No HTTP server, Gradio app in the file listing (listing: examples/run_lyrics_transcription.py, run_music_generation.py, run_music_reconstruction.py) — [GitHub tree API](https://api.github.com/repos/HeartMuLa/heartlib/git/trees/main?recursive=1).

### Inferences
- Wrapper: in the bot's venv-isolated service, hold one `HeartMuLaGenPipeline` (lazy_load=True on 8 GB) and expose `/generate`. Tag string = caption keywords comma-separated with no spaces; lyrics = `[verse]`/`[chorus]` etc. blocks (section names per README sample, exact vocabulary not read).
- `mula_dtype=bfloat16` on gfx1032 via HSA override probably works but is unverified; `bitsandbytes==0.49.0` is imported by the package only if code paths use it (import sites not checked); it has ROCm wheels only for some arches — risk of import failure on RDNA2 (unverified).
- `torchao==0.9.0` / `torchtune==0.4.0` pins may conflict with torch 2.9 ROCm 6.4 (torchao builds are version-matched to torch) — install in a dedicated venv and test import before anything else.
- VRAM unknown: README gives no figure; a 3B LM in bf16 is about 6 GB + KV caches + CFG batch 2, so 8 GB is tight; lazy_load helps only by separating codec from LM.

### Gaps
- Download size on disk and VRAM figures are not stated; no ROCm/AMD mention; no issue search done for AMD. Valid section-tag vocabulary beyond intro/verse/chorus/bridge/outro not verified in code (tokenizer treats it as plain text).

## 3. SongGeneration 2 / LeVo 2 (Tencent)

### Takeaway
Repo moved: `https://github.com/tencent-ailab/SongGeneration` now returns 404; the live code is `https://github.com/levo-demo/LeVo`. It is the best quality claim but the heaviest: v2-large needs 22 GB (28 GB with audio prompt), v2-medium 12 GB, so nothing fits the RX 6600 natively; hard-pinned to torch 2.6.0 / transformers 4.37.2, CUDA-oriented, non-commercial licence. Batch CLI only; a Python class exists in the Gradio tooling.

### Cited Findings
- Repo and README: [levo-demo/LeVo](https://github.com/levo-demo/LeVo) (HTTP 200; `tencent-ailab/SongGeneration` was 404 on 2026-11-19; third-party pages still cite the old URL, e.g. [gaga.art](https://gaga.art/blog/songgeneration-2/)). GitHub reports licence `NOASSERTION`; last push 2026-06-29 — [GitHub API](https://api.github.com/repos/levo-demo/LeVo).
- Variants/VRAM table: v2-large 4m30s, zh/en/es/ja etc., 22G/28G (no prompt / with prompt), RTF 0.82 on H20; v2-medium 12G/18G RTF 0.69; base-new 10G/16G; base-full 12G/18G — [README](https://raw.githubusercontent.com/levo-demo/LeVo/main/README.md) "Model Versions". (Earlier third-party blog listed v2-medium as "coming soon"; the README now has a download link, so it is released.)
- Python/CUDA: README says Python>=3.8.12, CUDA>=11.8 — README "Installation". Pins from [requirements.txt](https://raw.githubusercontent.com/levo-demo/LeVo/main/requirements.txt): `torch==2.6.0`, `torchaudio==2.6.0`, `torchvision==0.21.0`, `transformers==4.37.2`, `diffusers==0.27.2`, `peft==0.10.0`, `huggingface-hub==0.25.2`, `k-diffusion==0.1.1`, plus unpinned librosa, lightning, ninja, etc.; [requirements_nodeps.txt](https://raw.githubusercontent.com/levo-demo/LeVo/main/requirements_nodeps.txt) (installed with `--no-deps`): `antlr4-python3-runtime==4.8`, `hydra-core==1.0.7`, `omegaconf==2.2.0`, `sacrebleu`, `cython==3.1.2`, etc. No numpy, triton or vLLM pin.
- flash-attn optional: example wheel `flash_attn-2.7.4.post1+cu12torch2.6cxx11abiFALSE-cp310`; disable with `--not_use_flash_attn` — README "Installation"/"Inference". Docker image `juhayna/song-generation-levo:hf0613` — README.
- Downloads: `huggingface-cli download lglg666/SongGeneration-Runtime --local-dir ./runtime` then `mv runtime/ckpt ckpt; mv runtime/third_party third_party`; `huggingface-cli download lglg666/SongGeneration-v2-large --local-dir ./songgeneration_v2_large` (medium: `lglg666/SongGeneration-v2-medium`) — README "Inference". A third-party Modal plugin reports about 13 GB checkpoint plus runtime bundle downloaded — [tongflow-modal-levo](https://github.com/tong-io/tongflow-modal-levo).
- CLI: `sh generate.sh <ckpt_path> <lyrics.jsonl> <save_dir> [--low_mem] [--not_use_flash_attn] [--bgm|--vocal|--separate]`, which runs `python3 generate.py --ckpt_path --input_jsonl --save_dir --generate_type {mixed|separate|bgm|vocal} [--use_flash_attn] [--low_mem]` — [generate.sh](https://raw.githubusercontent.com/levo-demo/LeVo/main/generate.sh); generate.py:65-79 (argparse). `generate.sh` sets `USER=root`, `NCCL_HOME`, PYTHONPATH incl. `codeclm/tokenizer/Flow1dVAE`.
- Input jsonl fields: `idx`, `gt_lyric`, optional `descriptions`, optional `prompt_audio_path` (10 s used), optional `auto_prompt_audio_type` (README lists Pop, Latin, Rock, Electronic, Metal, Country, R&B/Soul, Ballad, Jazz, World, Hip-Hop, Funk, Soundtrack, Auto; but generate.py:19 defines `['Pop','R&B','Dance','Jazz','Folk','Rock','Chinese Style','Chinese Tradition','Metal','Reggae','Chinese Opera','Auto']` and asserts membership at :147 — README and code disagree; trust the code list). Do not combine `prompt_audio_path` and `descriptions` (README). Output: `save_dir/audio` and `save_dir/jsonl`.
- `gt_lyric` format: sections separated by `;`, tags `[intro-short|medium] [inst-short|medium] [outro-short|medium]` (no lyrics), `[verse] [chorus] [bridge]` (lyrics); sentences separated by `.`; English half-width punctuation; English final sentence must end in `.` — README "Input Guide". `descriptions` = comma-separated tags (gender, genre, emotion, instrument; BPM mentioned by third-party page only), not sentences.
- No seed argument: `np.random.seed(int(time.time()))` in `__main__` — generate.py:536; random prompt-audio pick uses `np.random.randint` (:148).
- Python API: `LeVoInference(ckpt_path)` in tools/gradio/levo_inference.py:16-63, `forward(lyric, description=None, prompt_audio_path=None, genre=None, auto_prompt_path=None, gen_type="mixed", params=dict())` returns `wav_seperate[0]` (:65-103); default params `cfg_coef=1.5, temperature=1.0, top_k=50, top_p=0.0, extend_stride=5, duration=max_dur` (:52-61); it imports `from separator import Separator` (:13), so `tools/gradio` must be on `sys.path`, and the repo root plus `codeclm/tokenizer/Flow1dVAE` on PYTHONPATH. Sample rate/shape of the returned tensor not verified.
- Low-memory variant: tools/gradio/levo_inference_lowmem.py reloads and deletes sub-models each call (`.cuda()` / `del` / `empty_cache` at lines ~49-66, ~129-137) and uses `OffloadProfiler` from `codeclm.utils.offload_profiler` (layer offload), so it cannot stay resident — [levo_inference_lowmem.py](https://raw.githubusercontent.com/levo-demo/LeVo/main/tools/gradio/levo_inference_lowmem.py). Gradio UI: `sh tools/gradio/run.sh ckpt_path` (runs `python3 tools/gradio/app.py`) — README / [run.sh](https://raw.githubusercontent.com/levo-demo/LeVo/main/tools/gradio/run.sh).
- CUDA hard-coding: `.cuda()` and `torch.autocast(device_type="cuda", dtype=torch.float16)` throughout generate.py (e.g. :101, :192, :233) and `torch.backends.cudnn.enabled = False` (levo_inference.py:20); on ROCm torch these map to HIP, so they run, but fp16 autocast is the dtype (no bf16).
- Licence: custom Tencent terms, "only for academic, research and education purposes", no commercial or production use — [LICENSE](https://raw.githubusercontent.com/levo-demo/LeVo/main/LICENSE) (fetched; first lines).
- Community GGUF route: `ckadirt/LeVo2-GGUF` quantisations (Q4_K_M … F16, LeLM about 1.9-10 GB, flow 0.6-2.65 GB, VAE 169-338 MB) with `LeVo2.cpp` (GGML) `levo-cli` and `levo-render`; built only with CUDA/CPU documented, no ROCm/Vulkan mention; marked research/education only; pinned to LeVo commit `653cbcf` — [HF card](https://huggingface.co/ckadirt/LeVo2-GGUF). Quality of quantised outputs not verified (card shows Q4_K_M flow SNR 8.1 dB vs F32).
- Quality claims (PER 8.55% vs Suno v5 12.4%, rivals MiniMax 2.5+) are Tencent self-reported — README.

### Inferences
- Must live in its own venv (torch 2.6.0 + transformers 4.37.2 vs bot's newer torch). Matching the ROCm 6.2.4 torch 2.6.0 wheel (pyproject.toml:84 comment) in that venv should work; `pip install -r requirements.txt` would otherwise replace torch with the CUDA build — install the ROCm torch first and use `--no-deps` for torch lines (unverified).
- 8 GB card: v2-medium at 12 GB nominal, with `--low_mem` offload layers it might run slowly; v2-large not realistic. Treat as unfit for the RX 6600 unless the GGUF route is validated on ROCm (not documented).
- A resident server is feasible only with the non-lowmem `LeVoInference`; GPU release = process kill.
- Because the CLI is batch/jsonl and loads models per process, cold start per request is the whole model load (minutes) unless wrapped around `LeVoInference`.

### Gaps
- Exact wheel disk size of v2-medium; cold-start seconds; any ROCm/RDNA2 reports (none found in this pass); what `separator.py` imports/needs (not read); output sample rate; whether v2-fast was ever released (not in README table).

## 4. YuE2-3B (m-a-p)

### Takeaway
Has the best-designed API of the group (`YuE2Pipeline`, `seed`, staged calls, ABC score input, wheel install) but is documented for a 24 GB NVIDIA GPU with Python 3.10+, peak ~11 GB VRAM and 24 GB host RAM, CC BY-NC 4.0, no ROCm mention. Not a fit for 8 GB without unproven offload.

### Cited Findings
- Model card [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B); code project https://github.com/multimodal-art-projection/YuE (link from the card; repo contents not read).
- Install: `python -m pip install huggingface-hub==0.36.2`; `hf download m-a-p/YuE2-3B yue2_infer-0.1.5-py3-none-any.whl --local-dir .`; `python -m pip install ./yue2_infer-0.1.5-py3-none-any.whl` — model card. Requirements: Linux, Python 3.10+, 24 GB NVIDIA GPU with BF16.
- Benchmarks used PyTorch 2.10, Transformers 4.57.6; server used Triton 3.6, PyTorch 2.6 for the VAE, vLLM 0.19 only for the separate H800 server; FlashAttention mentioned but not pinned; ROCm not mentioned — model card.
- API: `from yue2 import YuE2Pipeline`; `pipe = YuE2Pipeline.from_pretrained("m-a-p/YuE2-3B", device="cuda")`; `song = pipe(style=..., lyrics=..., cot="full", seed=...)`; `song.save("song.flac")`, `.save_artifacts(dir)`; staged: `pipe.plan()` -> `generate_semantic(plan)` -> `synthesize(semantic)` -> `decode(latents)`; `pipe.close()`; options `cfg_scale=1.2`, `vae="m-a-p/YuE2-Vae-legacy"`, `progress=False`, `abc=` — model card.
- CLI: `yue2 generate --quiet`, `yue2 batch --quiet` (other flags not documented) — model card.
- Inputs: `style` free-text genre/instrument prompt; `lyrics` full text organised into sections; `cot` in `"full"|"melody"|"off"` — model card.
- Perf: 3.6-minute song in 71 s on RTX 4090; peak VRAM ~11.0-11.2 GiB (14.08 GiB max-context), needs 24 GB host RAM; demo songs up to 5:00 — model card.
- Licence: weights CC BY-NC 4.0 — model card. Reported benchmark (SongBench 6.9632 vs Suno v5 6.8721) is self-reported — [ComfyUI Wiki](https://comfyui-wiki.com/news/2026-09-11-yue2-3b) (secondary). ComfyUI has native YuE2 support on a `yue2` branch (same source).

### Inferences
- Wrapper is trivial: one `YuE2Pipeline` instance, `pipe(style=caption, lyrics=lyrics, cot="full", seed=seed).save(path)`. Quality tiers: `cot="off"` (fast) vs `"full"`.
- Unknown torch dependency of the wheel (probably torch 2.10 per the benchmark notes): bot env torch 2.9 may fail to satisfy it; isolated venv needed. Peak 11 GB > 8 GB VRAM; `pipe.close()` between stages could reduce residency but is untested.

### Gaps
- Wheel metadata (Requires-Dist) and whether it runs on ROCm not read; disk size not listed on the card; GitHub repo README for YuE2 not read; YuE v1 (7B, exllama/llama.cpp variants) not covered because not requested.

## 5. MiniMax-Music3 (only if a practical route exists)

### Takeaway
A server route exists (`sgl-omni serve`, OpenAI-style `POST /v1/audio/speech`), but it is CUDA-only, about 57 GB of weights, and on an 8 GB card only "layer-by-layer streaming" (slow) is claimed. Practical only on NVIDIA; the hosted API ($0.15 per song) is the realistic route for this bot. Licence statements conflict across sources; the HF LICENSE file is a custom Community License.

### Cited Findings
- Weights `MiniMaxAI/MiniMax-Music3` (HF), ComfyUI build `Comfy-Org/MiniMax-Music-3`; released 2026-08-13; components 8B Global LLM, 0.6B Local LLM, 2.4B flow matching, 123M Flow-VAE; output 32 kHz 16-bit stereo WAV; up to 5 minutes — [HF card](https://huggingface.co/MiniMaxAI/MiniMax-Music3), [MiniMax blog](https://minimax.io/blog/minimax-music-3-0-next-generation-open-weights-production-ready-versatile-music-model).
- Hardware per HF card: CUDA required; full precision fits under 24 GB; about 22 GB with automatic CPU offloading; layer-by-layer LM streaming can run on 8 GB cards (slower).
- Serve: `hf download MiniMaxAI/MiniMax-Music3 --local-dir /path/to/minimax_ttm`; `sgl-omni serve --model-path MiniMaxAI/MiniMax-Music3 --port 8000`; endpoint `POST http://127.0.0.1:8000/v1/audio/speech` with `input` (lyrics with `[Verse]`/`[Chorus]` on own lines), `instructions` (structured caption: Global Metadata, Vocal Details, Arrangement), `response_format` `wav`, `seed`, `max_new_tokens` (25 fps audio frames, cap 9000), `stream` false; no streaming; prompt max 5000 tokens — HF card. Other frameworks: SGLang, diffusers, ComfyUI.
- Download about 57 GB; one source describes a 2-GPU split (LLM+RVQ on GPU 0, flow matching + decode on GPU 1) — [search result summary of third-party sources](https://aireiter.com/blog/minimax-music-3-0-review-api-pricing-local-setup) (secondary, not verified against the repo).
- Licence: HF LICENSE file is "MiniMax-Music3 COMMUNITY LICENSE": free use incl. weights, but commercial terms require displaying "MiniMax-Music3" in the commercial UI and a separate prior written authorization in some case (text truncated at the second commercial clause, rest not read) — [LICENSE](https://huggingface.co/MiniMaxAI/MiniMax-Music3/raw/main/LICENSE). Conflicting claims: a news article says CC BY-NC 4.0 — [mer.vin](https://mer.vin/news/minimax-music-3-is-open-weight-but-not-open-for-business/?amp=1); contradicted by the LICENSE file above, which I treat as authoritative.
- Hosted API: $0.15 per song, 120 RPM — [Atlas Cloud](https://www.atlascloud.ai/models/minimax/music-3.0) (via search summary; free tier reported discontinued; not verified on MiniMax's own docs).

### Inferences
- If used, it is the only candidate with a ready-made HTTP server: the bot's polling pattern collapses to a single blocking POST returning a WAV (submit+poll can be emulated by the wrapper). On this machine (AMD, 8 GB) it is not runnable; for "practical route" only the hosted API or a CUDA host qualifies.

### Gaps
- Rest of the Community License (revenue threshold, AUP) not read; SGLang-Omni ROCm support not checked; exact VRAM of the "8 GB streaming" mode and its speed not found; the hosted API's official endpoint and parameters not verified.

## 6. Minimal wrapper design and mapping to the bot's existing task pattern

### Takeaway
One tiny aiohttp (or FastAPI) script per model, run with that model's venv python, exposing `GET /health`, `POST /generate` (returns `task_id`), `POST /query_result`, `GET /v1/audio?path=` so the existing `AceStepClient` (submit, poll, download) works with at most a base-URL change. Models loaded lazily on first request; GPU freed by terminating the process (as `release_gpu()` already does).

### Cited Findings
- Bot client contract: `GET /health` must return JSON `data.status == "ok"` (ace_step_cog.py:211-216) inside an envelope `{code, data, error}` (ace_step_cog.py:205-209); `POST /release_task` -> `data.task_id` (+ optional `queue_position`) (:251-256); `POST /query_result {task_id_list:[id]}` -> list of `{task_id, status 0|1|2, result}` where `result` is a JSON string or list whose first element has `file` and `status` (:258-284); `GET /v1/audio?path=` download, same host only, size capped (:306-335).
- Bot lifecycle: starts the server with `subprocess.Popen(..., start_new_session=True)` and logs to `<server_dir>/acestep-api.log` (:430-439); waits on `/health` until `startup_timeout` (default 300 s) (:442-448); `release_gpu()` terminates it for TTS (:378-389); uses `venv_rocm/bin/python` when present (:414-420).
- Real calls to use inside each wrapper, verified in the sources above: HeartMuLa: `HeartMuLaGenPipeline.from_pretrained(...)` and `pipe({...}, save_path=...)` (music_generation.py:361-400); LeVo: `LeVoInference(ckpt)` / `forward(...)` (levo_inference.py:16-103); YuE2: `YuE2Pipeline.from_pretrained` / `pipe(...).save(...)` (model card).

### Inferences
Sketch (not executed; names above are real, glue is mine). One file, adapt the `load()` / `run()` pair per model; response envelope mirrors ACE-Step so `ace_step_cog.py` needs no parsing changes.

```python
# service.py  -- run with the model's own venv:  <venv>/bin/python service.py --port 8002
import asyncio, json, os, uuid, argparse, tempfile
from aiohttp import web

OUT = os.environ.get("SONG_OUT", os.path.expanduser("~/.cache/song-svc"))
os.makedirs(OUT, exist_ok=True)
JOBS: dict[str, dict] = {}
QUEUE: asyncio.Queue = asyncio.Queue()
MODEL = None   # loaded lazily, stays resident until the process is killed

def load():                      # --- per model ---
    global MODEL
    import torch
    from heartlib import HeartMuLaGenPipeline          # HeartMuLa example
    MODEL = HeartMuLaGenPipeline.from_pretrained(
        os.environ["HEARTMULA_CKPT"],
        device={"mula": torch.device("cuda"), "codec": torch.device("cuda")},
        dtype={"mula": torch.bfloat16, "codec": torch.float32},
        version="3B", lazy_load=True)

def run(job) -> str:             # blocking; returns output path  --- per model ---
    import torch
    torch.manual_seed(job["seed"])                      # heartlib has no seed arg
    path = os.path.join(OUT, f"{job['id']}.mp3")
    with torch.no_grad():
        MODEL({"lyrics": job["lyrics"], "tags": job["caption"].lower().replace(", ", ",")},
              max_audio_length_ms=job["duration"] * 1000, save_path=path,
              topk=50, temperature=1.0, cfg_scale=1.5)
    return path
# LeVo:  MODEL = LeVoInference(ckpt);  wav = MODEL(lyric=..., description=caption, gen_type="mixed");
#        torchaudio.save(path, wav, <sr: read from cfg, unverified>)
# YuE2:  MODEL = YuE2Pipeline.from_pretrained("m-a-p/YuE2-3B", device="cuda");
#        MODEL(style=caption, lyrics=lyrics, cot="full" if tier=="high" else "off", seed=seed).save(path)

async def worker():
    while True:
        job = await QUEUE.get()
        try:
            if MODEL is None: await asyncio.to_thread(load)
            job["file"] = await asyncio.to_thread(run, job); job["status"] = 1
        except Exception as e:
            job["status"], job["error"] = 2, str(e)

def env(data): return web.json_response({"code": 200, "data": data, "error": None})

async def health(_):   return env({"status": "ok"})
async def generate(r):
    b = await r.json(); jid = uuid.uuid4().hex
    JOBS[jid] = job = {"id": jid, "status": 0, "lyrics": b["lyrics"], "caption": b.get("caption", ""),
                       "duration": int(b.get("duration", 120)), "seed": int(b.get("seed", 0)),
                       "tier": b.get("quality", "standard")}
    await QUEUE.put(job); return env({"task_id": jid, "queue_position": QUEUE.qsize()})
async def query(r):
    ids = (await r.json())["task_id_list"]; out = []
    for i in ids:
        j = JOBS.get(i)
        if j: out.append({"task_id": i, "status": j["status"],
                          "result": json.dumps([{"file": f"/v1/audio?path={j.get('file','')}", "status": j["status"]}])})
    return env(out)
async def audio(r):
    p = os.path.realpath(r.query["path"])
    if not p.startswith(os.path.realpath(OUT) + os.sep): raise web.HTTPForbidden()
    return web.FileResponse(p)

async def on_start(app): app["w"] = asyncio.create_task(worker())
app = web.Application(); app.on_startup.append(on_start)
app.add_routes([web.get("/health", health), web.post("/generate", generate),
                web.post("/release_task", generate), web.post("/query_result", query),
                web.get("/v1/audio", audio)])
if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8002)
    web.run_app(app, host="127.0.0.1", port=ap.parse_args().port)
```

- Mapping to the cog: add per-model config (base URL, python path, launch args) next to `AceStepConfig` (ace_step_cog.py:119-140); generalise `_ensure_server` (:396-449) to pick `cmd = [<venv>/bin/python, "service.py", "--port", N]`; `submit()` (:218-256) maps `song.caption -> caption`, lyrics, `audio_duration -> duration`; seed from `use_random_seed` -> pass a random int. Because `/release_task` and `/query_result` are aliased in the sketch, `AceStepClient.query()` (:258-284) works unchanged. Per-model lyrics adaptation is needed: HeartMuLa `[verse]`-style lowercase text; LeVo `;`-separated, `.`-delimited, English punctuation; YuE2 sectioned plain text.
- Serialisation: the bot already serialises GPU users with `gpu_lock` and `release_gpu()` (ace_step_cog.py:378-381 comment); the wrapper should stay single-worker (one GPU job at a time), as in ACE-Step's default `ACESTEP_API_WORKERS=1` (docs/en/API.md:747).
- Cold start: no measurement exists in sources. Expect minutes for LeVo (multiple models: LM, audio tokenizer, separate tokenizer, flow VAE) and HeartMuLa with `lazy_load=True` (reload + `torch.compile` each call, music_generation.py:133-158); the bot's `startup_timeout` default 300 s may need raising.

### Gaps
- Sketch is untested. LeVo output sample rate and tensor layout unknown; HeartMuLa `mp3` saving depends on the torchaudio backend (not verified).

## 7. Concrete risks on this machine (RX 6600, 8 GB, gfx1032 with HSA_OVERRIDE 10.3.0, torch 2.9 ROCm 6.4 in bot)

### Takeaway
Only ACE-Step 2B turbo (current) and, with effort, HeartMuLa 3B are plausible on 8 GB. XL, LeVo v2-large/medium, YuE2 and MiniMax exceed 8 GB on paper or require NVIDIA; every candidate except ACE-Step needs its own venv.

### Cited Findings
- ACE-Step XL: unsupported tier at 6-8 GB — docs/en/GPU_COMPATIBILITY.md:5-18.
- LeVo: v2-large 22 GB, v2-medium 12 GB, base 10 GB — [README](https://raw.githubusercontent.com/levo-demo/LeVo/main/README.md); torch pinned 2.6.0 and transformers 4.37.2 — [requirements.txt](https://raw.githubusercontent.com/levo-demo/LeVo/main/requirements.txt); non-commercial licence — [LICENSE](https://raw.githubusercontent.com/levo-demo/LeVo/main/LICENSE).
- YuE2: 24 GB NVIDIA recommended, peak ~11 GiB — [model card](https://huggingface.co/m-a-p/YuE2-3B); CC BY-NC 4.0.
- HeartMuLa: torch range `>=2.4,<2.11` compatible with 2.9 in principle, but `numpy==2.0.2`, `transformers==4.57.0`, `torchao==0.9.0`, `bitsandbytes==0.49.0` pins — [pyproject.toml](https://raw.githubusercontent.com/HeartMuLa/heartlib/main/pyproject.toml).
- MiniMax-Music3: CUDA required — [HF card](https://huggingface.co/MiniMaxAI/MiniMax-Music3).
- Licences: HeartMuLa Apache-2.0; LeVo and YuE2 non-commercial; MiniMax custom Community License.
- Existing ROCm tweaks the bot already needs: `MIOPEN_FIND_MODE=FAST` (VAE stalls for minutes otherwise), `PYTORCH_HIP_ALLOC_CONF=expandable_segments:True`, `ACESTEP_ROCM_DTYPE=bfloat16` (ace_step_cog.py:421-425); the ACE-Step ROCm start script defaults `HSA_OVERRIDE_GFX_VERSION=11.0.0` (RDNA3) while this machine uses 10.3.0 from the bot's `.env` — /home/drift/git/ACE-Step-1.5/start_api_server_rocm.sh:26.

### Inferences
- Triton/flash-attn: none of HeartMuLa/LeVo require them (LeVo's flash-attn is optional; use `--not_use_flash_attn`); YuE2 mentions FlashAttention and Triton 3.6 without a pin; flash-attn on RDNA2 is unlikely to work, so disable everywhere. `torch.compile` in HeartMuLa needs Triton at runtime for the inductor GPU backend and may fail on gfx1032; heartlib catches failures and continues (music_generation.py:145-146).
- vLLM: not used by HeartMuLa or LeVo; YuE2 uses it only for the H800 server; irrelevant here (ROCm vLLM is the reason the bot already forces `ACESTEP_LM_BACKEND=pt`).
- fp16/bf16 on gfx1032 through the HSA override is the common unofficial path; correctness not verified for any of these models.
- Disk: ACE-Step XL about 9 GB per variant, LeVo about 13+ GB plus runtime, MiniMax 57 GB, HeartMuLa and YuE2 unknown (YuE2 card mentions a 7.3 GB checkpoint only in a secondary source). /home has 336 GB free, so disk is not the constraint; do not use /tmp for downloads (per user rules; set `TMPDIR=$HOME/.cache/tmp` and `HF_HOME` under /home).

### Gaps
- No ROCm/RDNA2 issue reports found for HeartMuLa, LeVo or YuE2 in this pass (searched only model pages/READMEs, not GitHub issues); no actual VRAM measurement exists for any model on this card.
