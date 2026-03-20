# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Give any developer a self-hosted AI coding assistant at Claude Code / Codex quality and speed, paying only for GPU seconds used on RunPod serverless — not a subscription.
**Current focus:** Phase 1 — Core Deployment Script

## Current Position

Phase: 1 of 3 (Core Deployment Script)
Plan: 2 of 2 in current phase
Status: Phase complete
Last activity: 2026-03-20 — Completed 01-01-PLAN.md (nemotron.py); Phase 1 complete

Progress: ████░░░░░░ 40%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: ~2 min
- Total execution time: ~0.05 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-deployment | 2/2 | ~3 min | ~2 min |

**Recent Trend:**
- Last 5 plans: 01-02 (1 min), 01-01 (2 min)
- Trend: —

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 01-02 | unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF as download source | GGUF-only repo avoids pulling full safetensor weights |
| 01-02 | allow_patterns=["*UD-Q4_K_XL*"] for selective download | Downloads only target quant (~60 GB, not full repo) |
| 01-02 | No argparse; token from env, path fixed | Keeps script minimal and readable for OSS users |
| 01-01 | workers=(0,1) scale-to-zero default | Cheapest for single-developer; always-on alternative documented inline |
| 01-01 | MODEL_FILENAME as top-level variable | Easy quant variant updates without hunting through CMD string |
| 01-01 | CMD as concatenated Python string | Per-flag inline comments stay adjacent to each flag |

### Pending Todos

None.

### Blockers/Concerns

None.

## Session Continuity

Last session: 2026-03-20
Stopped at: Completed Phase 1 reconciliation; ready to begin Phase 2 planning/execution
Resume file: None
