---
plan: 05-01
phase: 05-model-caching
status: complete
completed: 2026-03-22
commit: bc3cf2a
---

# Summary: 05-01 Dynamic Model Path Resolver

## What Was Done

Task 1 (auto) completed as planned — added `get_cached_model_path()`, `CACHED_REPO_ID`, and `CACHED_CACHE_BASE` to `nemotron.py`.

Task 2 (checkpoint: private HF repo) was **abandoned** after investigation revealed:
- RunPod cached models downloads all files in a repo — no selective quant filtering
- The unsloth repo is 2.01 TB across 23 quants; pointing cached models at it would download everything
- The workaround (private single-quant repo) requires uploading 83.8 GB to HF — not worth it when the network volume already serves the model instantly on cold start

## Key Discovery

**The network volume already eliminates the model download cold start.** Volume files are available immediately on worker boot — no sync, no download. The original 8-10 min cold start assumption was wrong; model files were never the bottleneck.

The actual cold start costs are:
1. **llama-server binary**: build from source (~5-10 min) — now fixed by binary caching on volume
2. **Model load into VRAM**: mmap over network volume (~3-6 min) — open issue, see Known Issues

## Deviations

Phase 5 pivoted from "RunPod cached models migration" to "binary caching on network volume":
- `get_cached_model_path()` added but `CACHED_REPO_ID` left empty (feature dormant until RunPod ships selective quant support)
- Seed runner overhauled: now builds llama-server on the volume during seed, same GPU type as inference workers
- Multi-arch CUDA build: `sm_90;100;120` (H200/B200/RTX Pro 6000 Blackwell)
- `--clean-binary` and `--clean-model` CLI flags added to seed
- `.env` auto-loading added to seed
- `--no-mmap` attempted but caused OOM (CUDA buffer pre-allocation exhausts 97GB VRAM); reverted
- `--no-kv-offload` removed — was causing OOM by forcing KV cache into VRAM alongside model weights

## Files Modified

- `nemotron.py` — `get_cached_model_path()`, seed overhaul, flag cleanup, `.env` loading, health endpoint improvements
- `patches/install_llama_server.sh` — multi-arch CUDA build (`sm_90;100;120`), GPU/arch coupling comment
- `README.md` — seed CLI docs, local hardware cost aside (March 2026 snapshot)
- `warmup.sh` — improved health polling (502/503 → `starting` status)

## Known Issues

- **VRAM load time (~3-6 min)**: mmap over network volume is slow. `--no-mmap` OOMs because CUDA pre-allocates the full buffer (79GB) upfront before streaming tensors, exceeding 97GB VRAM. Root cause: KV cache + model weights + CUDA overhead > 97GB. No clean fix without either more VRAM or a different serving approach.
- **Benchmark needed**: idle-to-ready time with warm binary (post-seed) not yet measured precisely — aborted at 6 min during testing.
