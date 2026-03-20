---
phase: 01-core-deployment
plan: 02
subsystem: infra
tags: [huggingface_hub, snapshot_download, gguf, runpod, network-volume]

# Dependency graph
requires: []
provides:
  - download_model.py script for seeding RunPod network volume with Nemotron GGUF
affects: [01-core-deployment, readme-docs]

# Tech tracking
tech-stack:
  added: [huggingface_hub (snapshot_download)]
  patterns: [env-var-token-auth, allow_patterns-for-selective-download]

key-files:
  created: [download_model.py]
  modified: []

key-decisions:
  - "Use unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF repo (GGUF-only repo, avoids pulling full safetensor weights)"
  - "allow_patterns=[\"*UD-Q4_K_XL*\"] to download only target quant file (~60 GB, not full repo)"
  - "Destination /workspace/models — matches nemotron.py model path"
  - "No argparse — keep script simple; token from env, path is fixed"

patterns-established:
  - "HF_TOKEN pattern: os.environ.get() with explicit error and sys.exit(1) on missing value"

# Metrics
duration: 1min
completed: 2026-03-20
---

# Phase 1 Plan 02: download_model.py Summary

**HuggingFace snapshot_download seeder using allow_patterns for UD-Q4_K_XL GGUF only, with HF_TOKEN env-var auth and /workspace/models destination matching nemotron.py**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-20T21:22:23Z
- **Completed:** 2026-03-20T21:23:00Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `download_model.py` — one-time seeder script for the RunPod network volume
- Uses `allow_patterns=["*UD-Q4_K_XL*"]` to download only the ~60 GB GGUF file, not the full repo
- HF_TOKEN read from environment; clear error message with token URL on missing value
- Destination `/workspace/models` matches the model path in nemotron.py

## Task Commits

Each task was committed atomically:

1. **Task 1: Write download_model.py using huggingface_hub snapshot_download** - `1f2ab38` (feat)

**Plan metadata:** (this docs commit)

## Files Created/Modified

- `download_model.py` - One-time model download script; seeds RunPod network volume before first deploy

## Decisions Made

- Used `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` repo (GGUF-specific repo; avoids pulling full safetensor weights alongside GGUF files)
- `allow_patterns=["*UD-Q4_K_XL*"]` scopes download to only the target quantization file
- No argparse — token from env, path fixed; keeps the script minimal for OSS readability

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required beyond HF_TOKEN (already documented in script).

## Next Phase Readiness

- `download_model.py` ready for developer use: `HF_TOKEN=hf_... python download_model.py`
- Phase 1 complete — both `nemotron.py` (plan 01-01) and `download_model.py` (plan 01-02) needed before Phase 2
- No remaining Phase 1 implementation work; next step is Phase 2

---
*Phase: 01-core-deployment*
*Completed: 2026-03-20*
