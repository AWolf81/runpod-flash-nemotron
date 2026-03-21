# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-20)

**Core value:** Give any developer a self-hosted AI coding assistant at Claude Code / Codex quality and speed, paying only for GPU seconds used on RunPod serverless — not a subscription.
**Current focus:** Phase 3 — README & Documentation reconciliation

## Current Position

Phase: 5 (Model Caching)
Plan: 1 of 2 in current phase
Status: Checkpoint — awaiting human action
Last activity: 2026-03-22 — Task 1 complete (get_cached_model_path added to nemotron.py); blocked on user creating private HF repo with UD-Q4_K_XL shards

Progress: ████████░░ 80%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: ~2 min
- Total execution time: ~0.05 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-core-deployment | 2/2 | ~3 min | ~2 min |
| 02-integration-guides | 1/1 | ~1 min | ~1 min |

**Recent Trend:**
- Last 5 plans: 02-01 (1 min), 01-02 (1 min), 01-01 (2 min)
- Trend: —

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 01-02 | unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF as download source | GGUF-only repo avoids pulling full safetensor weights |
| 01-02 | allow_patterns=["*UD-Q4_K_XL*"] for selective download | Downloads only target quant (~60 GB, not full repo) |
| 01-02 | One-command remote seeding via `python nemotron.py seed` | Keeps the volume bootstrap path in the main deployment script and runs the download on RunPod |
| 01-02 | No argparse; token from env, path fixed | Keeps script minimal and readable for OSS users |
| 01-01 | workers=(0,1) scale-to-zero default | Cheapest for single-developer; always-on alternative documented inline |
| 01-01 | MODEL_FILENAME as top-level variable | Easy quant variant updates without hunting through CMD string |
| 01-01 | CMD as concatenated Python string | Per-flag inline comments stay adjacent to each flag |

### Pending Todos

- User must create private HF repo with only UD-Q4_K_XL shards (~83.8 GB) and provide the repo ID
- After user provides repo ID: execute Plan 05-02 to wire get_cached_model_path() into all call sites

### Blockers/Concerns

- Plan 05-01 Task 2 is a blocking human-action checkpoint: user must create private HF repo and provide repo ID before Plan 05-02 can run
- Live RunPod deployment is still under active debugging

### Key Decisions (Phase 05)

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 05-01 | CACHED_REPO_ID left as empty string placeholder | Call sites unchanged until user confirms private HF repo exists |
| 05-01 | get_cached_model_path() returns None when CACHED_REPO_ID is empty | Preserves network volume fallback (MODEL_PATH) during transition |
| 05-01 | Snapshot fallback: list snapshots/ if refs/main absent | Defensive: handles edge case where refs/main is not yet written |

## Session Continuity

Last session: 2026-03-22
Stopped at: Plan 05-01 Task 1 complete (bc3cf2a); checkpoint awaiting user HF repo creation
Resume file: None
Resume signal: User provides private HF repo ID (e.g. "myname/nemotron-q4-xl")
