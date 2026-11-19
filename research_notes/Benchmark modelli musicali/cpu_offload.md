# CPU / heavy-offload feasibility of large song models on Ryzen 9 5900X + RX 6600 8 GB (research date 2026-11-19)

Labels used: [DOC] documented by vendor/repo/paper; [USER] user-reported; [LOCAL] read from local source; [EST] my own estimate (arithmetic shown); [GAP] not found.
Headline: I found NO measured CPU-only or 8 GB-offload benchmark for any of the target models. Every minute figure below marked [EST] is derived, not measured.

## 1. Measured/published speeds on CPU, CPU+8GB GPU, and quantized, per model

### Takeaway
No model has a published CPU-only or 8 GB-offload timing. ACE-Step XL-turbo is the only one whose compute (4B DiT x 8 steps, no CFG) is small enough for CPU to plausibly land in single-digit minutes [EST]. LM-based models (HeartMuLa, LeVo2, YuE) are autoregressive token generators; on CPU that is memory-bandwidth-bound and gives tens of minutes [EST].

### Cited Findings
- ACE-Step 1.5 paper: 240 s track in ~1 s on A100, under 10 s on RTX 3090, 8 steps no CFG, <4 GB VRAM (for the 2B turbo; no CPU data, XL not covered) — [arXiv 2602.00744](https://arxiv.org/html/2602.00744) [DOC, GPU only]
- ACE-Step docs call CPU mode "Slow, for testing only" — [LOCAL] /home/drift/git/ACE-Step-1.5/docs/en/BENCHMARK.md line 40. No CPU numbers in that file. CPU run command: `python profile_inference.py --device cpu --lm-backend pt` (BENCHMARK.md line 333).
- ACE-Step XL-turbo: 8 steps, no CFG; XL-sft/base: 50 steps with CFG (so 2 forward passes/step) — [LOCAL] docs/en/Tutorial.md lines 259-263. Weights ~9 GB bf16 (vs ~4.7 GB 2B) — [LOCAL] docs/en/GPU_COMPATIBILITY.md line 18 and acestep/gpu_config.py line 151.
- HeartMuLa (heartlib): "current inference speed is around RTF ≈ 1.0" (GPU, unspecified); streaming/acceleration scripts unreleased; no quantization, no ROCm, no CPU path documented; `--lazy_load` loads modules on demand; devices default cuda — [GitHub HeartMuLa/heartlib](https://github.com/HeartMuLa/heartlib) [DOC]. Paper: 67.95 s lowest e2e latency (streaming), 210 s avg at BS=4, 390 s at BS=8, GPU unspecified, song length unclear — [arXiv 2601.10547](https://arxiv.org/pdf/2601.10547) [DOC, from search snippet only].
- LeVo 2 large on GH200 (95 GiB): batch 1 = 0.57-0.673x realtime (36.5 s for 20.7 s of audio; 44.4 s for 29.8 s), LM stage dominates (34.3 of 36.5 s); peak VRAM 16.8 GiB; full ~2.7 min songs at batch 8 + CUDA graph = 152.9 s wall (8.52x RT). Profiler: GPU idle ~79% of each step, CPU 58 ms/step dispatch overhead — [levo_throughput page](https://tts-agi-moss-voice-profiles.static.hf.space/levo_throughput.html) [USER/third-party, GH200 datacenter GPU, undated]. Implication: single-song batch 1 is ~1.5-1.8x slower than realtime even on a GH200.
- LeVo 2 GGUF port "LeVo2.cpp" (GGML, no Python, optional CUDA): LeLM medium/large at F16/Q8_0/Q6_K/Q5_K_M/Q4_K_M, Flow Q8..Q4, VAE; "0.7B params" label is the flow part; no speed or RAM figures on the page, timings said to live in the source repo's docs; research/education license only; audio-prompt encoding and source separation not implemented — [HF ckadirt/LeVo2-GGUF](https://huggingface.co/ckadirt/LeVo2-GGUF) [DOC, undated]. Page mentions CUDA only, says VAE verified on CPU and CUDA.
- LeVo 2 large on AMD: fork runs it on RX 9070 16 GB, ROCm 7.2.1, PyTorch 2.11, 32 GB RAM; FP16 conversion 13 -> 9.5 GB, 8-bit KV cache, 4-stage memory manager; "minimum VRAM 16 GB"; no timings, no CPU path — [Siriusquirrel/SongGeneration](https://github.com/Siriusquirrel/SongGeneration) [USER]. HF discussion #2 "SongGeneration-v2-large running on 16GB VRAM and 32GB system RAM" (title only) — [HF discussions](https://huggingface.co/lglg666/SongGeneration-v2-large/discussions).
- LeVo 2 other claims: ComfyUI wrapper says layer offloading for v2 allows 12 GB and GGUF speeds inference — [comfy.icu SongGeneration](https://comfy.icu/extension/smthemex__ComfyUI_SongGeneration) [from search snippet].
- YuE2-3B: released 2026-09-09, 24 GB BF16 no quantization listed, CC-BY-NC-4.0, no speed — [ComfyUI Wiki YuE2-3B](https://comfyui-wiki.com/en/models/yue2/yue2-3b) [DOC secondary]. A MindStudio guide claims 4.5 GB VRAM on Nvidia/AMD, unconfirmed and conflicts with 24 GB — [MindStudio](https://www.mindstudio.ai/blog/yue2-open-music-generation-model/) (search snippet only; treat as unreliable). Original YuE (v1) README says optimized for 8 GB with quantized models; community fork YuEGP has 8-bit profiles + sequential CPU offload; no timings anywhere — [YuE README](https://cdn.jsdelivr.net/gh/multimodal-art-projection/yue@main/README.md), search snippet. I did NOT find a `--low-vram` flag in YuE2 docs [GAP].
- MiniMax-Music3: params are 8B global LLM (Qwen3-8B init) + 0.6B local LLM + 2.4B flow-matching + 123M VAE = ~11.1B total, which matches the "~11B" in the brief (other sources round to 8.6B by counting only the LLMs) — [localaimaster](https://localaimaster.com/blog/minimax-music-3-local-8gb), [OpenSourceForU 2026-08-18](https://www.opensourceforu.com/?p=102453). Model card: "Inference requires CUDA"; no ROCm path documented; 8 GB claim is "layer streaming / group offloading", vendor claim, not benchmarked; generation time on 8 GB "not measured"; ComfyUI offers int8_convrot DiT (2.5 GB), pruned int8 text encoder (9.2 GB), GGUF DiT Q4_K_M 1.49 GB..F16 4.98 GB; community estimate 32 GB system RAM for the 8 GB row; license permits commercial use with attribution (<US$20M revenue) — same sources plus [ComfyUI docs](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3). Released 2026-08-07.
- Measured MiniMax peak: just over 27 GB on RTX 6000 48 GB — [MindStudio review](https://www.mindstudio.ai/blog/minimax-music-3-quality-review/) [USER, from snippet].

### Inferences [EST]
- ACE-Step XL DiT compute per step, 180 s song: ~2250 patch tokens (25 Hz latent, patch 2; my assumption) x 2 x 4e9 params = ~18 TFLOP + attention. 5900X fp32 AVX2 peak is ~1.6 TFLOPS theoretical (12 cores x 2 FMA x 8 lanes x 2 x ~4.2 GHz), ~0.5-1.0 achieved => ~20-40 s/step. XL-turbo 8 steps ~3-5 min DiT, plus CPU VAE decode and LM. XL-sft/base 50 steps x CFG x2 = ~100 passes = ~35-70 min: NOT practical.
- bf16 on Zen 3 has no native support, so CPU runs fp32 (local code picks float32 for CPU, init_service_orchestrator.py ~line 101), which means 4B x 4 bytes = ~16 GB RAM for the DiT alone, leaving almost nothing of the 18 GB free. INT8 weight-only via torchao on CPU would cut that to ~4-5 GB but torchao int8 CPU kernels are slow and `compile_model` is required for quantization in ACE-Step's own validation [LOCAL: GPU_COMPATIBILITY.md line 41 "Compile Model... required for quantization"].
- LM-based models: decode speed on CPU ~ memory bandwidth / weight bytes. DDR4-3200 dual channel ~40-50 GB/s real. A 4B model at Q4 (~2.4 GB) ~15-20 tok/s ceiling; at Q8 ~8-10 tok/s. Song token rates for these models are ~25-50 tokens per second of audio (LeVo 2 LM took 120 s for ~160 s audio at batch 8 on GH200, i.e. several tokens/s per sequence is the GPU number). 180 s of audio x 25-50 tok/s = 4500-9000 tokens => ~5-15 min at best for Q4 GGUF-class CPU decode, realistic 15-40 min once flow/VAE and prefill are included. No such CPU GGUF pipeline is documented for HeartMuLa/YuE; LeVo2.cpp exists but only documents CUDA.
- PCIe: ACE-Step's offload is whole-model swap, not per-step weight streaming (see section 3), so the PCIe cost is a one-time ~9 GB (bf16) copy per generation: 9 GB / ~14 GB/s practical PCIe 4.0 x8 = ~1 s, negligible. Per-step layer streaming (group offload, MiniMax "8 GB" claim) would move all non-resident weights each step: e.g. 10 GB/step at 14 GB/s ~0.7 s/step overhead per forward, which is fine for a flow/DiT (8-50 steps) but terrible for an autoregressive LM (every token = full weight pass => ~1 token/s).

### Gaps
- No measured CPU-only/offload times for any target model; no Ryzen or 8 GB-GPU data for XL, HeartMuLa, LeVo 2, YuE2 or MiniMax-Music3.
- LeVo2.cpp speed docs in its source repo not located; no CPU-only (no CUDA) build timing.
- YuE2 `--low-vram` option not confirmed; YuEGP timings absent.
- No GitHub issue found for ACE-Step CPU/Ryzen speed (search index did not surface issue pages).

## 2. Memory footprint in system RAM (does it fit 18-24 GB free?)

### Takeaway
Only INT8/GGUF-class versions fit comfortably. fp32 CPU runs of 4B models (~16 GB) barely fit and leave no room for LM, text encoder and OS cache.

### Cited Findings
- ACE-Step XL weights ~9 GB (bf16); 2B ~4.7 GB; INT8 2B ~2.4 GB — [LOCAL] GPU_COMPATIBILITY.md, gpu_config.py line 410 comment ("DiT(INT8, ~2.4GB)").
- ACE-Step LM sizes 0.6B/1.7B/4B; Tier 3-4 (6-12 GB) allow only 0.6B LM — [LOCAL] GPU_COMPATIBILITY.md lines 11-12.
- MiniMax-Music3: original repo ~57 GB download; text encoder bf16 18.47 GB, pruned int8 9.2 GB, DiT int8 2.5 GB; 8 GB row total ~10.9 GB on disk — [localaimaster](https://localaimaster.com/blog/minimax-music-3-local-8gb). With a text encoder alone at 9-18 GB it hardly fits 18 GB free RAM with the rest.
- LeVo 2 large: 13 GB fp32 -> 9.5 GB fp16; user ran with 32 GB RAM, WSL allocated 26 GB — [Siriusquirrel](https://github.com/Siriusquirrel/SongGeneration).
- LeVo2 GGUF Q4_K_M listed file sizes: 1.92 / 3.44 GB class (mapping of numbers to files unclear) — [HF ckadirt/LeVo2-GGUF](https://huggingface.co/ckadirt/LeVo2-GGUF).
- YuE2-3B BF16: ~24 GB host RAM claimed in a secondary source — search snippet, [ComfyUI Wiki](https://comfyui-wiki.com/en/models/yue2/yue2-3b) (RAM figure unconfirmed).

### Inferences [EST]
- ACE-Step XL-turbo with INT8 (~4.5-5 GB) + 0.6B LM (~1.2 GB bf16) + text encoder (~1.2 GB) + VAE fits in RAM easily; fp32 XL (~16 GB) does not fit comfortably.
- MiniMax-Music3 needs ≥ ~14 GB RAM even in its smallest int8 combo (9.2 + 2.5 + VAE + LM 17 GB if the 8B LLM is separate [the 17.2 GB LM file in the original repo]); likely exceeds 18 GB free once the 8B LLM is counted; GGUF DiT alone is small but the text encoder/LLM is the bulk.

### Gaps
- Actual RSS measurements for any of these. HeartMuLa memory footprint not found.

## 3. Software stacks and known breakages (CPU / ROCm)

### Takeaway
ACE-Step is the only one with first-class CPU and ROCm code paths. HeartMuLa, MiniMax-Music3 (model card: "requires CUDA") and the LeVo2.cpp GGUF port document only CUDA. torchao INT8 and torch.compile are the risk items on gfx1032.

### Cited Findings
- ACE-Step: ROCm detection exists (`gpu_config.is_rocm_available()`), ROCm dtype via `_resolve_rocm_dtype()`, override `ACESTEP_ROCM_DTYPE=bfloat16|float16`; `ACESTEP_DEVICE` auto/cuda/cpu/xpu; CPU-only "possible with ACESTEP_DEVICE=cpu and ACESTEP_LM_BACKEND=pt" — [LOCAL] acestep/core/generation/handler/init_service_orchestrator.py lines 85-88, .claude/skills/acestep-docs/guides/ENVIRONMENT_SETUP.md line 533. ROCm excluded from the legacy-CUDA vLLM fallback; vLLM backend is NVIDIA-oriented, `pt` backend is the safe one on ROCm — [LOCAL] GPU_COMPATIBILITY.md lines 51-62 (vLLM text).
- ACE-Step quantization: `--quantization int8_weight_only|fp8_weight_only|w8a8_dynamic` via torchao; compile required — [LOCAL] acestep/cli_args.py, handler.py line 152, GPU_COMPATIBILITY.md line 41.
- HeartMuLa: PyTorch, Python 3.10, CUDA default, no quantization, no ROCm, no CPU documented — [heartlib](https://github.com/HeartMuLa/heartlib).
- LeVo 2: PyTorch; AMD fork on ROCm 7.2.1 / PyTorch 2.11 with SDPA preferred over flash-attn 2 (author found SDPA faster) — [Siriusquirrel](https://github.com/Siriusquirrel/SongGeneration). LeVo2.cpp = GGML, `-DGGML_CUDA=ON`, otherwise CPU build implied but undocumented.
- MiniMax-Music3: "Inference requires CUDA", no ROCm path — [localaimaster](https://localaimaster.com/blog/minimax-music-3-local-8gb); Diffusers group offloading + SGLang-Omni (two CUDA GPUs reference) — [OpenSourceForU](https://www.opensourceforu.com/?p=102453). ComfyUI int8_convrot weights and GGUF DiT exist — [ComfyUI docs](https://docs.comfy.org/tutorials/audio/minimax/minimax-music-3).

### Inferences [EST]
- gfx1032 with HSA_OVERRIDE 10.3.0 runs as gfx1030; torchao INT8 kernels on ROCm are not something I found documented; INT8 on ROCm is a test-first risk.
- Zen 3 has no AVX-512 and no AMX; oneDNN bf16 falls back to emulated conversion, so CPU bf16 is slower than fp32. INT8 via oneDNN uses AVX2 VNNI-less paths (Zen 3 lacks AVX-VNNI), so expect smaller INT8 gain than on Intel.

### Gaps
- No evidence on torchao INT8 on RDNA2/ROCm 6.4, nor on torch.compile with ROCm for ACE-Step; no ONNX ports for any of these found.

## 4. ACE-Step specifics (local repo)

### Takeaway
On an 8 GB card the official tier table (Tier 3/4) marks XL as not supported. Code offload is whole-model swapping, not layer streaming, so XL bf16 (~9 GB) cannot run on an 8 GB GPU; XL with INT8 (~4.5-5 GB est.) on GPU, or XL fp32 on CPU, are the only paths.

### Cited Findings
- Tier table [LOCAL GPU_COMPATIBILITY.md lines 7-16]: 6-8 GB = Tier 3, XL ❌, LM 0.6B, backend pt, offload CPU+DiT, INT8; 8-12 GB = Tier 4 (an 8.0 GB card sits at the boundary; the RX 6600 reports ~8 GB so tier 3/4 is ambiguous), XL ❌, LM 0.6B, vllm (not usable on ROCm; pt fallback); 12-16 GB Tier 5 XL ⚠️ "marginal (offload + quantization required)"; 16-20 GB Tier 6a XL ✅ with offload. INSTALL.md / Tutorial.md: XL "≥12GB VRAM (with offload)", minimum 12 GB with offload + quantization, 20 GB+ recommended — docs/en/INSTALL.md lines 657-703, Tutorial.md line 257.
- Env vars [LOCAL]: `ACESTEP_OFFLOAD_TO_CPU` (default false; auto-on for low tiers), `ACESTEP_OFFLOAD_DIT_TO_CPU` (default false), `ACESTEP_DEVICE`, `ACESTEP_LM_DEVICE`, `ACESTEP_LM_BACKEND` — acestep/api/startup_model_init.py lines 50-61, .claude/skills/acestep-docs/api/API.md lines 674-686. `MAX_CUDA_VRAM=8` simulates tier (also enforces a hard memory fraction) — GPU_COMPATIBILITY.md lines 85-104. README-XPU.md line 109 mentions `ACESTEP_OFFLOAD_TO_CPU=true`.
- Offload mechanism [LOCAL]: init_service_offload_context.py `_load_model_context` moves the entire model (`_recursive_to_device`) to GPU for the duration of a context and back to CPU on exit; with offload_to_cpu but not offload_dit_to_cpu the DiT is moved to GPU "persistent"; VAE and text encoder are swapped in/out. There is no per-layer or per-step weight streaming. Consequence: a DiT that does not fit in free VRAM simply OOMs.
- Runtime safety: VAE decode falls back GPU tiled -> GPU with CPU offload -> full CPU decode; VRAM guard reduces batch — GPU_COMPATIBILITY.md lines 44-49.
- VRAM estimate table in code has dit_xl_turbo/dit_xl_base 9.0 GB; I found no hard gate that forbids XL on small tiers in gpu_config.py (grep shows only estimation entries, lines 151-217), so XL is "unsupported" by docs but likely launchable; it would OOM on GPU at bf16/fp16 [EST from 9 GB + CUDA context > 8 GB].
- Official XL speed numbers: none; only "turbo 8 steps no CFG; sft/base 50 steps CFG" — Tutorial.md. A ComfyUI blog says 8 steps is a "six-fold" speedup vs base (GPU) — [Pulse blog](https://www.pulse.bot/ai/blogs/ace-step-15-xl-commercial-grade-music-generation-in-comfyui-37f64d09-4f0c-42e6-bd40-d507b7f60992/) (search snippet).

### Inferences [EST]
- Path A (GPU, INT8 XL): torchao int8_weight_only XL ~4.5-5 GB + activations + VAE fits 8 GB if LM is on CPU/0.6B and VAE tiled; speed would be near 2B turbo x ~2 (4B vs 2B) on an RX 6600, i.e. tens of seconds to ~1-2 min. This is the single most promising test; blocked only if torchao INT8 or compile fails on gfx1030-override.
- Path B (CPU fp32 XL-turbo): ~3-5 min DiT + VAE/LM extras, ~16 GB RAM (see section 1).
- Path C (XL-sft/base): 50 steps x CFG, impractical on CPU (35-70 min); on GPU-INT8 maybe 5-10 min [EST].
- PCIe link is irrelevant for ACE-Step offload (one-shot copy per generation, ~1 s).

### Gaps
- Real RX 6600/ROCm behaviour of torchao INT8 in this repo; whether the tier detector treats 8 GB as Tier 3 or 4.

## 5. Recommendation

### Takeaway
ACE-Step XL-turbo is the only large model with a realistic path: first test it INT8 on the GPU (Path A), second as CPU fp32 with a 0.6B LM (Path B, ~3-6 min and ~16+ GB RAM [EST]). LeVo 2 large, HeartMuLa, YuE2 and MiniMax-Music3 have no documented non-CUDA/CPU route and, being autoregressive LMs, would likely take 15-40+ min [EST], so they are not recommended for the bot.

### Cited Findings
- See sections 1-4 for sources; no new facts here.

### Inferences [EST]
Test order (nothing run by me; all to be tested later by the user):
1. `MAX_CUDA_VRAM=8`, `ACESTEP_DEVICE=cuda`, `ACESTEP_LM_BACKEND=pt`, `ACESTEP_OFFLOAD_TO_CPU=true`, `ACESTEP_OFFLOAD_DIT_TO_CPU=true`, xl-turbo with `--quantization int8_weight_only`, 0.6B LM, via `profile_inference.py` with 180 s duration. Record RSS and VRAM. If it OOMs or torchao fails on ROCm, go to step 2.
2. `ACESTEP_DEVICE=cpu`, xl-turbo, LM off first (then 0.6B), 8 steps; check `free -g` (needs ~16-17 GB); expect ~3-6 min [EST]; try ACESTEP_ROCM_DTYPE irrelevant on CPU.
3. Only if steps 1-2 are good, try xl-sft with fewer steps; skip 50-step CPU runs.
4. LeVo2.cpp CPU build of Q4_K_M only if you want a second candidate (document says only CUDA tested).
Skip: MiniMax-Music3 (CUDA-only, 27 GB measured peak, ~11B), HeartMuLa (RTF ~1 on GPU, no CPU path), YuE2 (24 GB, no low-VRAM option found).

### Gaps
- All timings above are estimates until one of the steps is run; speed ceiling on Zen 3 fp32 (0.5-1 TFLOPS) is assumed, not benchmarked.
