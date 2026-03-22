# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Give any developer a self-hosted AI coding assistant at Claude Code / Codex quality and speed, paying only for GPU seconds used on RunPod serverless — not a subscription.
**Current focus:** All planned phases complete. Open issue: VRAM load time (mmap over network volume ~3-6 min).

## Current Position

Phase: 5 of 5 (Model Caching) — Complete
Status: All phases done
Last activity: 2026-03-22 — Phase 5 complete; binary caching on volume implemented; cached model approach abandoned (RunPod has no selective quant filtering)

Progress: ██████████ 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 4 (+ 2 skipped)
- Average duration: ~2 min
- Total execution time: ~0.05 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-deployment | 2/2 | ~3 min | ~2 min |
| 02-integration-guides | 1/1 | ~1 min | ~1 min |
| 03-readme-documentation | 2/2 | ~2 min | ~1 min |
| 05-model-caching | 1/3 (2 skipped) | ~60 min | — |

## Accumulated Context

### Decisions

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 01-02 | unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF as download source | GGUF-only repo avoids pulling full safetensor weights |
| 01-02 | allow_patterns=["*UD-Q4_K_XL*"] for selective download | Downloads only target quant (~60 GB, not full repo) |
| 01-02 | One-command remote seeding via `python nemotron.py seed` | Keeps the volume bootstrap path in the main deployment script |
| 01-01 | workers=(0,2) scale-to-zero default | Cheapest for single-developer |
| 05 | Binary caching on volume instead of RunPod cached models | RunPod cached models downloads all files — no selective quant filtering; 2.01 TB would be downloaded from unsloth repo |
| 05 | Seed runner uses same GPU as inference (RTX Pro 6000 Blackwell) | Binary must be compiled on same CUDA driver stack as inference workers |
| 05 | Multi-arch CUDA build: sm_90;100;120 | Supports H200/B200/RTX Pro 6000 Blackwell from one binary |
| 05 | --no-kv-offload removed | Was causing OOM — forces KV cache into VRAM alongside 79GB model weights, exceeding 97GB |
| 05 | --no-mmap reverted | OOM: CUDA pre-allocates full 79GB buffer before streaming tensors; mmap stays |
| 05 | get_cached_model_path() dormant (CACHED_REPO_ID="") | Feature ready for when RunPod ships selective quant support |

### Pending Todos

- Benchmark idle-to-ready time with warm binary (binary on volume, model on volume) — aborted at 6 min
- Investigate why mmap load takes ~3-6 min over network volume and whether it can be reduced

### Blockers/Concerns

- VRAM load time with mmap over network volume is slow (~3-6 min observed). Root cause unclear — may be network volume throughput, mmap page fault pattern, or CUDA transfer speed.

## Session Continuity

Last session: 2026-03-22
Stopped at: Phase 5 complete; all SUMMARYs written; open issue is VRAM load benchmark
Resume file: None
