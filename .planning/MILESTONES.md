# Project Milestones: runpod-flash-nemotron

## v0.1.0 MVP (Shipped: 2026-03-22)

**Delivered:** Working RunPod Flash deployment for Nemotron-3-Super-120B-A12B GGUF with integration guides, streaming, and cold-start optimization — early pre-release.

**Phases completed:** 1–6 (8 active plans, 2 skipped)

**Key accomplishments:**

- Single-file RunPod Flash deployment (`nemotron.py`) with llama-server GGUF on RTX Pro 6000 Blackwell (96 GB VRAM)
- Network volume binary caching — seed builds llama-server once; cold start cut from 16m30s to 8m45s
- Integration guides + example configs for Claude Code (LiteLLM gateway), OpenCode, and Mistral Vibe
- SSE streaming confirmed working through Flash LB via FastAPI `StreamingResponse` (prior "not supported" assumption disproved)
- Slot priming fix — eliminates first-request KV cache failure on fresh workers (NemotronH hybrid-attention quirk)
- Cost analysis: ~$0.28/warmup, scale-to-zero recommended for single-developer use (~$126/month typical)

**Stats:**

- 50 files created/modified
- ~1,953 lines (Python, shell, Markdown, JSON, YAML, TOML)
- 6 phases, 8 active plans, 2 skipped (CACHE-01–03 deferred — RunPod selective quant not available)
- 2 days (2026-03-20 → 2026-03-22)

**Git range:** `4286f1c` (init) → `841ad6b` (Phase 4 complete)

**Known gaps (accepted as tech debt):**

- CACHE-01–03: RunPod cached models downloads all repo files — no selective quant filtering. `get_cached_model_path()` is dormant pending RunPod fix. Network volume serves the model without download delay.
- STRM-03: Claude Code and Mistral Vibe streaming untested against live endpoint. OpenCode + Open WebUI verified live.

**What's next:** Define v0.2.0 goals — candidates include VRAM load time reduction, multi-region support, or v2 requirements from REQUIREMENTS.md (streaming config examples, quant variants).

---
