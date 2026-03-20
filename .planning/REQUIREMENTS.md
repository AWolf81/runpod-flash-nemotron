# Requirements: runpod-flash-nemotron

**Defined:** 2026-03-20
**Core Value:** Give any developer a self-hosted AI coding assistant at Claude Code / Codex quality and speed, paying only for GPU seconds used on RunPod serverless — not a subscription.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Deployment

- [ ] **DEPL-01**: Developer can deploy a serverless endpoint with a single `flash deploy` command using `nemotron.py`
- [ ] **DEPL-02**: Deployment script configures A100 80GB GPU (`GpuGroup.AMPERE_80`), 100 GB Network Volume, FlashBoot, and `execution_timeout=1800`
- [ ] **DEPL-03**: Developer can seed the Network Volume using `download_model.py` before first deploy, preventing cold-start timeout loop
- [ ] **DEPL-04**: llama-server starts with correct flags (`-ngl 99 --override-tensor "exps=CPU" -c 8192 -fa --no-mmap -np 1 --cont-batching`), exposing `/v1/chat/completions` on port 8080
- [ ] **DEPL-05**: `execution_timeout=1800` is set with inline comment explaining why (120B models require >10 min for long responses)
- [ ] **DEPL-06**: `--override-tensor "exps=CPU"` is documented with explanation that MoE expert weights exceed VRAM and must route to CPU RAM
- [ ] **DEPL-07**: `idle_timeout` tuning is documented with guidance on reducing billing for short coding sessions

### Integration

- [ ] **INTG-01**: Developer can configure Claude Code to use the RunPod endpoint via `~/.claude/settings.json` or environment variables
- [ ] **INTG-02**: Developer can configure OpenCode to use the RunPod endpoint via `~/.config/opencode/config.json`
- [ ] **INTG-03**: Developer can configure Mistral Vibe to use the RunPod endpoint via environment variable override

### Documentation

- [ ] **DOCS-01**: README provides one-command quickstart with prerequisites, `HF_TOKEN` setup steps, and explicit cold-start warning
- [ ] **DOCS-02**: Cost breakdown documents scale-to-zero vs always-on trade-offs and $20/month math (~10.5 GPU-hours at ~$1.89/hr)
- [ ] **DOCS-03**: NVIDIA-recommended sampling defaults (`--temp 1.0 --top-p 0.95`) are documented with source reference
- [ ] **DOCS-04**: EU-RO-1 datacenter restriction is noted with latency implications for non-EU users
- [ ] **DOCS-05**: Context window tuning documents `-c` flag options and VRAM/RAM constraints (why 8192 is the safe cap)
- [ ] **DOCS-06**: MIT LICENSE file is included in the repository

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhancement

- **ENH-01**: Streaming config examples in integration snippets (add when users request)
- **ENH-02**: Other quant variants (Q8_0 for quality, Q3_K_M for smaller VRAM) — research needed
- **ENH-03**: Multi-region deployment guide (pending RunPod Flash expansion beyond EU-RO-1)
- **ENH-04**: GitHub Actions deploy workflow for automated re-deployment

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| vLLM FP8 / 2×H100 | Requires 2×H100 (~$6+/hr), exceeds $20/month single-user budget |
| Fine-tuning / model training | Inference only |
| Multi-user / team deployment | Single developer target; serverless cold starts incompatible with shared use |
| Web UI / chat interface | Pure API backend; users already have Claude Code, OpenCode, Mistral Vibe |
| Other model support | Nemotron-3-Super-120B only; generalization dilutes value proposition |
| Streaming enabled by default | Keep deployment script simple; document as optional in integration snippets |

## Traceability

Which phases cover which requirements. Updated by create-roadmap.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEPL-01 | — | Pending |
| DEPL-02 | — | Pending |
| DEPL-03 | — | Pending |
| DEPL-04 | — | Pending |
| DEPL-05 | — | Pending |
| DEPL-06 | — | Pending |
| DEPL-07 | — | Pending |
| INTG-01 | — | Pending |
| INTG-02 | — | Pending |
| INTG-03 | — | Pending |
| DOCS-01 | — | Pending |
| DOCS-02 | — | Pending |
| DOCS-03 | — | Pending |
| DOCS-04 | — | Pending |
| DOCS-05 | — | Pending |
| DOCS-06 | — | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 0 (pending create-roadmap)
- Unmapped: 16 ⚠️

---
*Requirements defined: 2026-03-20*
*Last updated: 2026-03-20 after initial definition*
