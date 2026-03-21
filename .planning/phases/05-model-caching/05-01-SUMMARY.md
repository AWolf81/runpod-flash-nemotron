---
plan: 05-01
phase: 05-model-caching
status: checkpoint
completed: 2026-03-22
commit: bc3cf2a
checkpoint: human-action
---

# Summary: 05-01 Dynamic Model Path Resolver

## What Was Done

### Task 1: Add CACHED_REPO_ID config and get_cached_model_path() resolver (complete)

Added to `nemotron.py` immediately after `GPU_INFERENCE_ENDPOINT_NAME`:

- `CACHED_REPO_ID = ""` — placeholder for the user's private single-quant HF repo ID
- `CACHED_CACHE_BASE = "/runpod-volume/huggingface-cache/hub"` — RunPod cached model mount base
- `get_cached_model_path() -> str | None` — reads `refs/main` for the commit hash, falls back to
  listing `snapshots/` if `refs/main` is absent, returns `None` when `CACHED_REPO_ID` is empty or
  the cache directory does not exist

Existing constants (`VOLUME_NAME`, `MODEL_DIR`, `MODEL_FILENAME`, `MODEL_PATH`) and all call sites
are unchanged. Network volume path remains the active fallback.

Verification passed:
- `python -m py_compile nemotron.py` — exit 0
- `python -c "import nemotron; print('get_cached_model_path' in dir(nemotron))"` — True

## Checkpoint: Awaiting Human Action

Task 2 is a `checkpoint:human-action` gate. Execution is paused until the user:

1. Creates a **private** HuggingFace repository containing only the 3 UD-Q4_K_XL shard files
   (~83.8 GB total).
   - URL: https://huggingface.co/new
   - Settings: Type = Model, Visibility = Private

2. Uploads the 3 GGUF shards:
   ```bash
   pip install "huggingface_hub>=0.32.0"
   huggingface-cli login --token $HF_TOKEN
   huggingface-cli upload your-org/nemotron-q4-xl \
     /runpod-volume/models/UD-Q4_K_XL/ \
     --repo-type model
   ```

3. Verifies the upload and provides the repo ID (e.g. `your-username/nemotron-q4-xl`).

**Why not the unsloth repo directly:** RunPod cached models downloads all files in a repo — the
unsloth repo is 2.01 TB with 23 quantization variants. The private single-quant repo is ~83.8 GB.

## Resume Signal

Paste your repo ID (e.g. `myname/nemotron-q4-xl`) to continue to Plan 02, which will:
- Set `CACHED_REPO_ID` to your actual repo ID
- Update all hard-coded `model_path` strings in `chat_completions`, `warmup`, `gpu_health`,
  and `make_seed_runner` to use `get_cached_model_path()`

## Files Modified

- `nemotron.py` — added `CACHED_REPO_ID`, `CACHED_CACHE_BASE`, and `get_cached_model_path()`

## Deviations from Plan

None. The function matches the plan specification exactly.
