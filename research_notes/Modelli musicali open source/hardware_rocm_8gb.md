# Open-weight song models on 8 GB AMD RDNA2 (RX 6600, gfx1032) under ROCm

Assumptions (mine): RX 6600 8 GB, ROCm 6.4 PyTorch wheels, HSA_OVERRIDE_GFX_VERSION=10.3.0, Fedora, 16+ GB system RAM. Research date 2026-11-19. Many sources are secondary (blogs, wikis, search-snippet summaries); marked where so. Roughly 25 tool calls; some pages 404'd/timed out (SongGeneration GitHub README, AMD ACE-Step blog fetch). No source found documents ANY of these models (other than ACE-Step) on RDNA2.

## 1. Per-model VRAM, speed and quantization

### Takeaway
Only ACE-Step 1.5 (2B DiT + 0.6B LM) is documented for tiers that include 6-8 GB and AMD RDNA2. DiffRhythm v1 (8 GB with chunked decode), YuE v1 (8 GB with exllamav2 4.25bpw), SongBloom (6-8 GB bf16, community claim) and HeartMuLa 3B (6-8 GB with lazy load) are claimed to fit in 8 GB but on NVIDIA only; SongGeneration needs 10 GB minimum; YuE2, SongGeneration-v2-large and MiniMax Music 3 are 16-24 GB+ class. ACE-Step XL officially needs 12 GB minimum.

### Cited Findings
**ACE-Step 1.5 / XL**
- Tier table: 6-8 GB tier allows 0.6B LM, pt backend, CPU+DiT offload, INT8; XL (4B) DiT marked unsupported below 12 GB; XL weights about 9 GB vs about 4.7 GB for the 2B DiT; 12-16 GB marginal, 16-20 GB with offload, 20 GB+ without — [local GPU_COMPATIBILITY.md](file:///home/drift/git/ACE-Step-1.5/docs/en/GPU_COMPATIBILITY.md) (same at [upstream](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/HEAD/docs/en/GPU_COMPATIBILITY.md))
- XL model card/README: min 12 GB with offload + quantization, 20 GB recommended without offload — [HF xl-base](https://huggingface.co/ace-step/acestep-v15-xl-base), [README](https://cdn.jsdelivr.net/gh/ace-step/ace-step-1.5@main/README.md) (via search summary)
- A community bf16 conversion of xl-turbo claims 8 GB with offload + INT8, 12 GB offload only; this is the converter's claim, not official — [marcorez8 xl-turbo-bf16](https://cnb.cool/ai-models/marcorez8/acestep-v15-xl-turbo-bf16) (search summary only, not opened)
- Speed (non-XL setups): under 2 s per full song on A100, under 10 s on RTX 3090; xl-turbo is 8 steps, no CFG, about 6x faster than xl base/sft — [ComfyUI blog](https://blog.comfy.org/p/ace-step-15-xl-commercial-grade-music). No 8 GB XL or GGUF timing found.

**YuE (v1)**
- README claims runs on 8 GB with quantized models; an exllamav2 port reports stage1 at 4.25 bpw working in a minimum of 8 GB — [YuE README](https://cdn.jsdelivr.net/gh/multimodal-art-projection/yue@main/README.md), [issue #44](https://github.com/multimodal-art-projection/YuE/issues/44) (search snippet)
- INT8 stage-2 1B checkpoint exists on HF — [Alissonerdx/YuE-s2-1B-general-int8](https://huggingface.co/Alissonerdx/YuE-s2-1B-general-int8)
- Speed on 8 GB: no figure found.

**YuE2 (3B, released 2026-09-09, CC-BY-NC-4.0)**
- Official README baseline: NVIDIA, BF16, 24 GB VRAM, Linux, Python 3.12; AMD listed as experimental path — [README](https://cdn.jsdelivr.net/gh/multimodal-art-projection/yue@main/README.md)
- Official `docs/hardware.md`: `--low-vram` (only active AR or NAR module on the accelerator, song model unloaded before VAE decode, needs host RAM, slower); `--budget 8` option; FP8 AR weights NVIDIA-only; an 8 GB RTX 5060 Laptop completed two songs with low_vram, BF16/FP8 AR, 6000-token cap; stable length limits on 6/8/12 GB "not measured" — [hardware.md](https://raw.githubusercontent.com/multimodal-art-projection/YuE/main/docs/hardware.md)
- HF card: RTX 4090 generated a 3.6-min song in 71 s; serving benchmark peak 78.55 GiB (vLLM-style concurrent serving) — [HF M-A-P/YuE2-3B](https://huggingface.co/M-A-P/YuE2-3B) (via search summary)
- Community GGUF conversions exist (unofficial) — [ldov/YuE2-GGUF](https://huggingface.co/ldov/YuE2-GGUF); VRAM claims in blogs conflict (under 8 GB vs 4.5 GB); no independent benchmark.

**DiffRhythm / DiffRhythm 2**
- DiffRhythm-base min 8 GB with `--chunked` decoding; no generation-time benchmarks in README; README lists only v1.2/v1/VAE (no DiffRhythm 2 weights listed) — [ASLP-Lab/DiffRhythm](https://github.com/ASLP-Lab/DiffRhythm)
- 8 GB RTX 3060 Ti test: failed until chunked=True — [LinuxLinks review](https://linuxlinks.com/machine-learning-linux-diffrhythm-song-generation/2)
- DiffRhythm 2: paper (5 Hz VAE, songs up to 210 s); no VRAM number found — [arXiv 2510.22950](https://arxiv.org/html/2510.22950v1)

**SongGeneration / LeVo (v1 base, v2 "large", released 2026-03-01 per blog)**
- v1 base: 10 GB without prompt audio, 16 GB with; `--low_mem` flag for OOM — [HF model card README](https://huggingface.co/lglg666/SongGeneration-base/blob/refs%2Fpr%2F1/README.md), [cnb mirror](https://cnb.cool/3844522/SongGeneration)
- v2-large: claims range from 22 GB+ (vendor blogs, ComfyUI node 22-28 GB normal mode) to a user report of 16 GB VRAM + 32 GB RAM working — [ComfyUI FL-SongGen](https://comfy.icu/extension/filliptm__ComfyUI_FL-SongGen), [HF discussions](https://huggingface.co/lglg666/SongGeneration-v2-large/discussions), [InsMelo](https://insmelo.com/blog/levo-2-song-generation)
- Speed: RTF 0.82 for v2 (third-party, unverified, GPU unstated) — [gaga.art](https://gaga.art/blog/songgeneration-2/)

**HeartMuLa (only 3B open; 7B is internal)**
- No VRAM numbers in repo; `--lazy_load true` for single GPU; bf16 LM, fp32 HeartCodec (bf16 codec degrades audio); RTF about 1.0; acceleration TODO; no quantization mentioned — [heartlib](https://github.com/HeartMuLa/heartlib)
- Third-party: about 8 GB minimum with lazy load, 16 GB recommended; 3B lazy-load peak about 6.2 GB; ComfyUI node table 3B about 6 GB fp16; HeartMuLa Studio wants 10 GB+, INT8 option; CPU-only 30-60+ min per song vs about 4 min GPU — [Hermes skill docs](https://hermes-agent.nousresearch.com/docs/user-guide/skills/optional/creative/creative-heartmula), [ComfyUI_FL-HeartMuLa](https://github.com/filliptm/ComfyUI_FL-HeartMuLa), [HeartMuLa-Studio](https://github.com/fspecii/HeartMuLa-Studio)
- Releases 2026: Jan 14 first 3B, Jan 23 RL 3B, Feb 13 happy-new-year 3B, Sep 16 MuLaCover — [heartlib](https://github.com/HeartMuLa/heartlib)

**SongBloom**
- No VRAM figure in README (suggests bf16 for lower-VRAM GPUs); ComfyUI wrapper: about 8 GB fp32, 6 GB bf16, described as optimistic; tutorial claims 6 GB minimum; one HF mirror says official GitHub/HF repos were deleted by authors, code survives in forks — [HF CypressYang/SongBloom](https://huggingface.co/CypressYang/SongBloom), [comfy.icu node](https://comfy.icu/node/SongBloomGenerator), [NextDiffusion](https://www.nextdiffusion.ai/tutorials/how-to-use-songbloom-to-make-ai-music-in-comfyui) (search summary; status unverified)

**MiniMax Music 3 (August 2026, CC BY-NC 4.0)**
- 8B global LLM + 0.6B local LLM + 2.4B flow matching + 123M decoder (about 11B); HF card 24 GB+ standard, CPU offload to "8GB" cards via Diffusers; GitHub reference uses two CUDA GPUs; repo about 57 GB — [mer.vin](https://mer.vin/news/minimax-music-3-is-open-weight-but-not-open-for-business/) (secondary; sources disagree, one outlet said weights not yet out on Aug 13)

### Inferences
- 8 GB claims for DiffRhythm, YuE v1, HeartMuLa, SongBloom come from authors or users on NVIDIA; RDNA2 allocates a bit differently (no fp8, slower bf16 math), so treat as "might fit", not verified.
- Offload of a 2B-3B model between 8 GB and host RAM over PCIe 4.0 x8 (RX 6600 is x8) will likely dominate runtime; no measured penalty found, so any slowdown figure is my guess (likely several x).
- XL on 8 GB: weights about 9 GB bf16; INT8 about 4.5 GB would fit in theory, but official floor is 12 GB because of activations/VAE/LM; unverified.

### Gaps
- No per-GPU timing for 2-4 min songs on 8 GB cards for any model except YuE2/4090 and ACE-Step A100/3090 figures.
- DiffRhythm 2 weights/code availability and VRAM.
- SongGeneration official README (404) and v2 requirements; SongBloom official repo status.
- AMD ACE-Step blog (timeout) — its generation times not captured.

## 2. ROCm / AMD evidence and component breakage

### Takeaway
ACE-Step is the only model with documented RDNA2 support (HSA override 10.3.0, pt LM backend, no vLLM). YuE2 officially supports ROCm 7.1 PyTorch with plain SDPA (tested only on MI350X). The others never mention ROCm; their risk lies in flash-attn, Triton and CUDA-only deps, but I found no concrete failure reports either way.

### Cited Findings
- ACE-Step: RDNA2 needs `HSA_OVERRIDE_GFX_VERSION=10.3.0`; recommend `ACESTEP_LM_BACKEND=pt` on ROCm; torch.compile set to eager on ROCm Windows; WSL2 ROCm limited; Linux manual at `docs/en/ACE-Step1.5-Rocm-Manual-Linux.md` — [GPU_TROUBLESHOOTING](https://raw.githubusercontent.com/ace-step/ACE-Step-1.5/HEAD/docs/en/GPU_TROUBLESHOOTING.md)
- `uv run acestep` may install CUDA torch wheels over a ROCm setup; use a manual venv with `pip install -e .` (community mirror READMEs) — [README mirror](https://gh.r-mj.com/ace-step/ACE-Step-1.5)
- AMD blog (Feb 2026): ACE-Step 1.5 on Radeon via ComfyUI, ROCm 7.2 — [AMD](https://www.amd.com/en/blogs/2026/commercial-grade-ai-music-generation-on-amd-ryzen-ai-and-radeon-ace-step-1-5.html) (search summary; page not opened)
- ACE-Step vLLM/nano-vllm is CUDA/Triton-oriented; docs' auto vLLM fallback covers only pre-Volta NVIDIA; ROCm excluded from that check — local GPU_COMPATIBILITY.md
- YuE2: ROCm uses `--device cuda`, eager AR decoding, SDPA, no NVIDIA-private attention; pip wheel torch 2.10.0 from rocm7.1 index; tested only on MI350X attention comparisons, not full generation; optional vLLM worker separate; no RDNA2 mention — [hardware.md](https://raw.githubusercontent.com/multimodal-art-projection/YuE/main/docs/hardware.md)
- SongGeneration: flash-attn optional; `--not_use_flash_attn` fallback; one fork reports SDPA faster than flash_attn — [gitlink mirror](https://www.gitlink.org.cn/yangchuangfu/SongGeneration), [Siriusquirrel fork](https://gh.hhj520.top/Siriusquirrel/SongGeneration)
- HeartMuLa: Triton needed for GPU acceleration, Linux-only (Hermes docs); no ROCm mention in repo — [Hermes docs](https://hermes-agent.nousresearch.com/docs/user-guide/skills/optional/creative/creative-heartmula)
- DiffRhythm, HeartMuLa, SongBloom, SongGeneration: searches for ROCm/AMD returned no relevant issues or reports.
- ExLlamaV2 on RX 6800 (gfx1030) discussed in an exllamav2 thread; not a YuE result — [discussion #562](https://scriptagc.wasmer.app/https_github_com/turboderp-org/exllamav2/discussions/562)

### Inferences
- bitsandbytes (INT8/4-bit) on gfx1032 is historically unreliable; ACE-Step's INT8 is torchao-style/own quantization and runs on the user's machine at about 7 GB (from the task brief). Whether other repos' INT8 paths work on ROCm is unknown.
- Models that depend only on PyTorch SDPA (YuE2, SongGeneration with flag, ACE-Step pt) are the likeliest to run; anything needing flash-attn, exllamav2 CUDA kernels, FP8 or vLLM is likely out or needs a patched path.

### Gaps
- No RDNA2-specific failure/success reports for any model except ACE-Step; Reddit/GitHub issue search not exhaustive (search tool surfaced none).

## 3. Realistic paths for larger/newer models (offload, quant, staged)

### Takeaway
Staged execution exists in YuE2 (`--low-vram`: AR and NAR modules swapped, song model unloaded before VAE decode) and HeartMuLa (`--lazy_load`), both trading speed for fit via host RAM; INT8 for ACE-Step XL is the nearest-in-reach upgrade but officially below the 12 GB floor.

### Cited Findings
- YuE2 low-vram and HeartMuLa lazy-load mechanics as above — [hardware.md](https://raw.githubusercontent.com/multimodal-art-projection/YuE/main/docs/hardware.md), [heartlib](https://github.com/HeartMuLa/heartlib)
- GGUF/quantization can lower VRAM yet sometimes reduce speed — [ComfyUI speed guide](https://comfyui.nomadoor.net/en/basic-workflows/speed-and-efficiency/) (via search summary)
- ACE-Step already uses CPU+DiT offload + INT8 on the 6-8 GB tier — local GPU_COMPATIBILITY.md
- MiniMax Music 3 card claims CPU offload to 8 GB cards via Diffusers — [mer.vin](https://mer.vin/news/minimax-music-3-is-open-weight-but-not-open-for-business/)

### Inferences
- Candidates to test, in order: ACE-Step XL-turbo with INT8 + offload (same codebase, same ROCm setup); HeartMuLa 3B lazy-load (about 6 GB peak claimed, RTF 1 so about 3-4 min per 3-4 min song on NVIDIA, slower with swaps); YuE2 low-vram (SDPA-only, ROCm-aware docs, but 3B AR plus NAR plus long audio chunks; expect many minutes per song); DiffRhythm v1 chunked (fast, 8 GB, quality lower, CUDA-focused deps like espeak only).
- Costs are my estimates; no measured penalty found.

### Gaps
- No measured offload slowdowns on PCIe x8 8 GB cards.

## 4. Likely excluded on this hardware

### Takeaway
Excluded or very unlikely: MiniMax Music 3 (about 11B, 24 GB+/two GPUs, offload claim unverified), SongGeneration-v2-large (16-28 GB, flash-attn/CUDA stack), ACE-Step 4B LM and unquantized XL, YuE2 with default settings (24 GB; vLLM/FP8 paths NVIDIA-only). SongBloom is uncertain mainly because the official repo may be deleted.

### Cited Findings
- See per-model figures in section 1; XL below 12 GB marked unsupported by ACE-Step docs; YuE2 low-length limits on 8 GB unmeasured — [hardware.md](https://raw.githubusercontent.com/multimodal-art-projection/YuE/main/docs/hardware.md)
- SongGeneration base needs 10 GB minimum (above this card's 8 GB) unless `--low_mem` works — [cnb mirror](https://cnb.cool/3844522/SongGeneration)

### Inferences
- Exclusion is a judgment from documented minimums plus lack of any ROCm/RDNA2 evidence, not from failed trials.

### Gaps
- Did not find other 2026 open song models beyond YuE2, SongGeneration 2, HeartMuLa updates, MiniMax Music 3, ACE-Step XL; search was broad but thin.
