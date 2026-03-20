---
phase: 01-core-deployment
plan: 01
subsystem: infra
tags: [runpod, runpod-flash, llama-server, gguf, nemotron, a100, serverless]

# Dependency graph
requires: []
provides:
  - RunPod Flash endpoint deployment script (nemotron.py)
  - llama-server CMD with all required flags and inline documentation
  - Context window scaling ladder comment block
affects: [02-integration-guides, 03-readme-documentation]

# Tech tracking
tech-stack:
  added: [runpod-flash>=1.8.1]
  patterns:
    - "Single Python file deploys entire serverless endpoint via `flash deploy`"
    - "llama-server CMD assembled as a concatenated Python string with per-flag inline comments"

key-files:
  created: [nemotron.py]
  modified: []

key-decisions:
  - "workers=(0,1) scale-to-zero default — cheapest option; documented always-on alternative as inline comment"
  - "execution_timeout=1800 — 120B model needs >10 min for long responses; default 600s kills mid-generation"
  - "idle_timeout=60s — aggressive scale-to-zero for short coding sessions; documented trade-off inline"
  - "MODEL_FILENAME extracted as a top-level variable for easy quant variant updates"

patterns-established:
  - "Inline comments on every non-obvious config param — script is self-explaining without external docs"
  - "Context window tradeoff documented as a comment block with the scaling ladder and memory math"

# Metrics
duration: 2min
completed: 2026-03-20
---

# Phase 1 Plan 01: Write nemotron.py Summary

**RunPod Flash serverless endpoint for Nemotron-3-Super-120B on A100 80GB via llama-server GGUF, with all flags, inline comments, and context window scaling ladder**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-20T21:22:17Z
- **Completed:** 2026-03-20T21:23:31Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Created `nemotron.py` — complete, syntactically valid RunPod Flash deployment script (92 lines)
- Configured endpoint with GpuGroup.AMPERE_80, NetworkVolume (100GB at /workspace/models), FlashBoot, execution_timeout=1800, idle_timeout=60
- Added llama-server CMD with all 8 required flags: `-ngl 99`, `--override-tensor "exps=CPU"`, `-c 32768`, `-fa`, `--no-mmap`, `-np 1`, `--cont-batching`, `--port 8080`
- Added inline comments on every non-obvious flag explaining the reasoning
- Added context window scaling ladder comment block with KV cache memory math (~320KB/token, scaling from 32768 to 131072+)

## Task Commits

Each task was committed atomically:

1. **Task 1: Endpoint configuration (GPU, volume, FlashBoot, timeouts)** - `63518e5` (feat)

   Note: Task 2 (llama-server CMD) was included in the same file creation — both tasks are captured in this single commit as the llama-server CMD is inseparable from the endpoint definition. All Task 2 done criteria are satisfied.

**Plan metadata:** _(docs commit follows)_

## Files Created/Modified

- `nemotron.py` — RunPod Flash deployment script: endpoint config, llama-server CMD, all inline documentation

## Decisions Made

- **workers=(0,1) scale-to-zero** — cheapest default for single-developer use; always-on alternative documented inline as a comment
- **MODEL_FILENAME as top-level variable** — makes it easy to swap quant variants without hunting through the CMD string
- **CMD assembled as concatenated Python string** — keeps per-flag inline comments adjacent to each flag, which is clearer than a multi-line shell heredoc

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required beyond what is already documented in the script itself.

## Next Phase Readiness

- `nemotron.py` is complete and satisfies all DEPL-01, DEPL-02, DEPL-04, DEPL-05, DEPL-06, DEPL-07 requirements
- Ready for 01-02: Write download_model.py (snapshot_download with HF_TOKEN, UD-Q4_K_XL pattern)
- No blockers

---
*Phase: 01-core-deployment*
*Completed: 2026-03-20*
