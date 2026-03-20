# runpod-flash-nemotron

## What This Is

A one-command RunPod Flash deployment script and integration guide for running NVIDIA Nemotron-3-Super-120B-A12B on a single A100 80GB via llama-server (GGUF), exposing an OpenAI-compatible API endpoint usable as a self-hosted backend for Claude Code, OpenCode, and Mistral Vibe. Designed for public OSS use — a developer picks up this repo and is coding with a powerful open model within minutes, for ~$20/month.

## Core Value

Give any developer a self-hosted AI coding assistant at Claude Code / Codex quality and speed, paying only for GPU seconds used on RunPod serverless — not a subscription.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Single-file RunPod Flash deployment script (`nemotron.py`) that deploys Nemotron-3-Super GGUF UD-Q4_K_XL on A100 80GB via llama-server
- [ ] OpenAI-compatible API endpoint exposed via RunPod proxy URL (no custom server needed)
- [ ] Integration guide + config snippets for Claude Code (`~/.claude/settings.json` / env vars)
- [ ] Integration guide + config snippets for OpenCode (`~/.config/opencode/config.json`)
- [ ] Integration guide + config snippets for Mistral Vibe (env-based OpenAI override)
- [ ] Cost breakdown and usage tips to stay within $20/month
- [ ] MIT licensed, clean README with one-command quickstart
- [ ] Config template for `scale-to-zero` (workers=0,1) vs `always-on` (workers=1) trade-offs documented

### Out of Scope

- vLLM FP8 / 2×H100 path — exceeds $20/month budget for single-user dev use
- Fine-tuning or model training — inference only
- Multi-user / team deployment — single developer target
- Web UI / chat interface — pure API backend
- Other models — Nemotron-3-Super-120B only (this is the value proposition)

## Context

- **RunPod Flash** is a Python library for RunPod serverless. You write a Python script with `Endpoint`, `GpuType`, `PodTemplate` objects and run `flash deploy` to push it. Pricing is per GPU-second.
- **Nemotron-3-Super-120B-A12B** (released March 2026): 120B total params, 12B active params per token (MoE). GGUF UD-Q4_K_XL quant fits in ~65GB VRAM, leaving headroom on A100 80GB. llama-server exposes `/v1/chat/completions`.
- **Target hardware**: A100 80GB PCIe (~$1.89/hr on RunPod). At $20/month with serverless pay-per-second, a developer gets ~10.5 GPU-hours — plenty for focused coding sessions.
- **All three target tools** (Claude Code, OpenCode, Mistral Vibe) consume OpenAI-compatible APIs. Same endpoint, different config files.
- **EU-RO-1 datacenter**: RunPod Flash serverless is currently restricted to EU-RO-1 — low latency from Europe, noted in docs.
- **Model source**: `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` on HuggingFace. Requires `HF_TOKEN`.
- **Scale-to-zero option**: `workers=(0,1)` saves cost when idle but adds ~2-5 min cold start (model download). Documented as user choice.

## Constraints

- **Budget**: ~$20/month single-user — constrains to GGUF on A100 80GB; no H100 multi-GPU paths
- **Hardware**: Single A100 80GB PCIe minimum; the GGUF path must fit within 80GB with headroom
- **API compatibility**: Output must be OpenAI-compatible `/v1/chat/completions` — llama-server satisfies this
- **Dependency**: Requires RunPod account, HuggingFace token, `runpod-flash>=1.8.1`
- **License**: MIT — clean IP, no NVIDIA proprietary tooling bundled
- **Scope**: Public OSS — README must be beginner-friendly with copy-paste quickstart

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| GGUF via llama-server over vLLM FP8 | Single A100 vs 2×H100 = fits $20/month budget; llama-server is OpenAI-compatible out of the box | — Pending |
| UD-Q4_K_XL quant over Q4_K_M | Better quality-size balance at ~65GB; recommended by community for this model | — Pending |
| RunPod Flash Python SDK over manual pod API | DX goal: one Python file, one CLI command to deploy — no dashboard clicking | — Pending |
| Focus on three tools (Claude Code, OpenCode, Mistral Vibe) | These are the main OSS AI coding clients with OpenAI-compatible config | — Pending |

---
*Last updated: 2026-03-20 after initialization*
