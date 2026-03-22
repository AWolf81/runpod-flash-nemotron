# runpod-flash-nemotron

## What This Is

A one-command RunPod Flash deployment script and integration guide for running NVIDIA Nemotron-3-Super-120B-A12B on a single RTX Pro 6000 Blackwell (96 GB VRAM) via llama-server (GGUF), exposing an OpenAI-compatible API endpoint usable as a self-hosted backend for Claude Code, OpenCode, and Mistral Vibe. Designed for public OSS use — a developer picks up this repo and is coding with a powerful open model within minutes.

## Core Value

Give any developer a self-hosted AI coding assistant at Claude Code / Codex quality and speed, paying only for GPU seconds used on RunPod serverless — not a subscription.

## Requirements

### Validated

- ✓ Single-file RunPod Flash deployment script (`nemotron.py`) that deploys Nemotron-3-Super GGUF UD-Q4_K_XL via llama-server — v0.1.0 (hardware: RTX Pro 6000 Blackwell 96GB; A100 80GB OOMs on this model)
- ✓ OpenAI-compatible API endpoint exposed via RunPod proxy URL — v0.1.0
- ✓ Integration guide + config snippets for Claude Code (via LiteLLM gateway) — v0.1.0
- ✓ Integration guide + config snippets for OpenCode — v0.1.0
- ✓ Integration guide + config snippets for Mistral Vibe — v0.1.0
- ✓ Cost breakdown and usage tips (~$0.28/warmup, scale-to-zero ~$126/month typical) — v0.1.0
- ✓ MIT licensed, clean README with one-command quickstart — v0.1.0
- ✓ Scale-to-zero vs always-on trade-offs documented — v0.1.0
- ✓ SSE streaming via FastAPI `StreamingResponse` (Flash LB passes through unchanged) — v0.1.0
- ✓ Binary caching on network volume — seed builds llama-server, workers restore; cold start 8m45s — v0.1.0
- ✓ Cold start benchmarks and cost analysis documented — v0.1.0

### Active

- [ ] VRAM load time reduction — ~3–6 min mmap over network volume; `--no-mmap` OOMs (CUDA pre-allocates full 79GB buffer before streaming); needs more VRAM or a different serving approach
- [ ] Selective quant caching — `get_cached_model_path()` dormant; `CACHED_REPO_ID=""` guards it pending RunPod selective quant support
- [ ] Streaming config examples in integration snippets (ENH-01 from v2 backlog)
- [ ] Claude Code and Mistral Vibe streaming verified against live endpoint (STRM-03 partial — OpenCode + Open WebUI verified live)

### Out of Scope

- vLLM FP8 / 2×H100 path — exceeds budget; single-user dev use targets one GPU
- Fine-tuning or model training — inference only
- Multi-user / team deployment — serverless cold starts incompatible with shared use
- Web UI / chat interface — pure API backend
- Other models — Nemotron-3-Super-120B only (this is the value proposition)
- A100 80GB — OOMs on this model; RTX Pro 6000 Blackwell (96GB VRAM) is minimum viable hardware

## Context

- **RunPod Flash** is a Python library for RunPod serverless. You write a Python script with `Endpoint`, `GpuType`, `PodTemplate` objects and run `flash deploy` to push it. Pricing is per GPU-second.
- **Nemotron-3-Super-120B-A12B** (released March 2026): 120B total params, 12B active params per token (MoE). GGUF UD-Q4_K_XL quant is ~79GB in VRAM — requires RTX Pro 6000 Blackwell (96GB) or H200. A100 80GB OOMs. llama-server exposes `/v1/chat/completions`.
- **Target hardware**: RTX Pro 6000 Blackwell (~$1.69/hr on RunPod). At $20/month with serverless pay-per-second, a developer gets ~12 GPU-hours — plenty for focused coding sessions. Realistic total including warmups: ~$126/month.
- **All three target tools** (Claude Code, OpenCode, Mistral Vibe) consume OpenAI-compatible APIs. Same endpoint, different config files. Claude Code requires a LiteLLM gateway (expects Anthropic-format traffic).
- **EU-RO-1 datacenter**: RunPod Flash serverless is currently restricted to EU-RO-1 — low latency from Europe, noted in docs.
- **Model source**: `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` on HuggingFace. Requires `HF_TOKEN`.
- **Scale-to-zero option**: `workers=(0,1)` saves cost when idle but adds ~8m45s cold start (binary restore from volume + VRAM load). Documented as user choice.
- **Shipped v0.1.0**: 50 files, ~1,953 LOC, 6 phases, 2 days.

## Constraints

- **Hardware**: RTX Pro 6000 Blackwell 96GB minimum (A100 80GB OOMs); the GGUF UD-Q4_K_XL path requires 96GB VRAM
- **API compatibility**: Output must be OpenAI-compatible `/v1/chat/completions` — llama-server satisfies this
- **Dependency**: Requires RunPod account, HuggingFace token, `runpod-flash>=1.8.1`
- **License**: MIT — clean IP, no NVIDIA proprietary tooling bundled
- **Scope**: Public OSS — README must be beginner-friendly with copy-paste quickstart

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| GGUF via llama-server over vLLM FP8 | Single GPU vs 2×H100 = fits budget; llama-server is OpenAI-compatible out of the box | ✓ Good — works, benchmarked at 81.7 tok/s gen |
| UD-Q4_K_XL quant over Q4_K_M | Better quality-size balance; recommended by community for this model | ✓ Good — fits in 96GB with headroom |
| RunPod Flash Python SDK over manual pod API | DX goal: one Python file, one CLI command to deploy — no dashboard clicking | ✓ Good — `flash deploy` works |
| Focus on three tools (Claude Code, OpenCode, Mistral Vibe) | These are the main OSS AI coding clients with OpenAI-compatible config | ✓ Good |
| Claude Code via LiteLLM gateway (not direct) | Claude Code expects Anthropic-format traffic; direct OpenAI endpoint not compatible | ✓ Good — only viable path |
| Binary caching on volume over RunPod cached models | RunPod cached models downloads all repo files (2.01 TB for unsloth repo); no selective quant filtering | ✓ Good — cut cold start from 16m30s to 8m45s |
| workers=(0,2) scale-to-zero default | Cheapest for single-developer; cold start documented clearly | ✓ Good |
| Multi-arch CUDA build sm_90;100;120 | Supports H200/B200/RTX Pro 6000 Blackwell from one binary | ✓ Good |
| FastAPI StreamingResponse for SSE | Flash LB passes through unchanged; prior "not supported" comment was unverified | ✓ Good — live-tested with OpenCode + Open WebUI |
| Slot priming on first /health ok | NemotronH hybrid-attention requires KV cache init; first real request was timing out | ✓ Good — first-request failure eliminated |

---
*Last updated: 2026-03-22 after v0.1.0 milestone*
