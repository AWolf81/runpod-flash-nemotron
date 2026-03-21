# Phase 5: Model Caching - Research

**Researched:** 2026-03-22
**Domain:** RunPod serverless cached models feature vs. network volume trade-offs
**Confidence:** HIGH

<research_summary>
## Summary

Researched RunPod's native cached models feature to determine whether it can replace the current network volume approach for storing the Nemotron-3-Super-120B GGUF model (~83.8 GB for UD-Q4_K_XL, 3 shards).

**Critical finding: RunPod cached models cannot selectively download specific quantization files from a multi-quant HuggingFace repo.** The `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` repo contains 23 quantization variants totalling **2.01 TB**. RunPod would download all of it — making the feature unusable against this repo as-is.

The viable path to use RunPod cached models is to **create a private single-quant HuggingFace repo** containing only the 3 UD-Q4_K_XL shard files (~83.8 GB). This repo becomes the cached models target, bypassing the multi-quant limitation.

**Primary recommendation:** Create a private HuggingFace repo with only the UD-Q4_K_XL shards, configure RunPod cached models against it, and update the worker to resolve the HuggingFace-style snapshot path rather than reading from `/runpod-volume/models/`.
</research_summary>

<standard_stack>
## Standard Stack

No new libraries required — the migration is a configuration change (RunPod console + HuggingFace repo) plus a path update in `nemotron.py`.

### Core Tools

| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| RunPod Console UI | N/A (web) | Configure cached model on endpoint | Only way to set cached model — no SDK API |
| `huggingface-cli` | current | Create and upload files to private HF repo | Official HF upload tool |
| `huggingface_hub` | >=0.32.0 | Already used for seed; can also push files | Already a project dependency |

### Runtime Path Resolution Pattern

| Instead of | Use Instead | Tradeoff |
|------------|-------------|----------|
| Hard-coded `/runpod-volume/models/UD-Q4_K_XL/...` | Dynamic snapshot path resolver | Handles hash-based snapshot dirs correctly |
| Network volume mount | RunPod cached model mount at `/runpod-volume/huggingface-cache/hub/` | No $7/month fixed cost; no 8-10 min download cold start |

**No pip install needed** — path resolution is pure Python using `os.path` and `pathlib`.
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### How RunPod Cached Models Work

```
1. One-time setup (developer):
   a. Create private HF repo with only UD-Q4_K_XL shards
   b. In RunPod console: endpoint → Settings → Model → enter repo ID + HF token
   c. RunPod pre-caches model files on fleet hosts

2. Cold start (per-worker):
   a. RunPod scheduler picks a host that already has the model cached
   b. If no cached host: RunPod downloads model (developer NOT billed for this)
   c. Model files appear at /runpod-volume/huggingface-cache/hub/...
   d. Worker starts — model is already on disk

3. Worker runtime:
   a. Read snapshot hash from refs/main
   b. Construct model path from hash
   c. Pass path to llama-server --model flag
```

### Recommended File Structure After Migration

```
/runpod-volume/huggingface-cache/hub/
└── models--{org}--{repo-name}/
    ├── refs/
    │   └── main          ← contains the snapshot commit hash (plain text)
    └── snapshots/
        └── {hash}/
            ├── NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf
            ├── NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00002-of-00003.gguf
            └── NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00003-of-00003.gguf
```

### Pattern 1: Snapshot Path Resolution

**What:** Resolve the hash-based snapshot directory without hardcoding
**When to use:** Any time model path changes due to HF repo updates
**Example:**
```python
import os

def resolve_model_path(cache_base: str, repo_id: str, filename: str) -> str:
    """
    Resolve the HuggingFace snapshot path for a cached model.

    cache_base: /runpod-volume/huggingface-cache/hub
    repo_id: org/repo-name (e.g., "myorg/nemotron-q4-xl")
    filename: the first shard filename
    """
    # HF hub stores as models--org--repo
    repo_dir = "models--" + repo_id.replace("/", "--")
    hub_path = os.path.join(cache_base, repo_dir)

    # Read snapshot hash from refs/main
    refs_path = os.path.join(hub_path, "refs", "main")
    if os.path.exists(refs_path):
        with open(refs_path) as f:
            commit_hash = f.read().strip()
    else:
        # Fallback: pick first entry in snapshots/
        snapshots_dir = os.path.join(hub_path, "snapshots")
        entries = os.listdir(snapshots_dir)
        commit_hash = entries[0]

    return os.path.join(hub_path, "snapshots", commit_hash, filename)

# Usage in worker:
CACHE_BASE = "/runpod-volume/huggingface-cache/hub"
REPO_ID = "myorg/nemotron-q4-xl"   # your private single-quant repo
MODEL_FILENAME = "NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"
model_path = resolve_model_path(CACHE_BASE, REPO_ID, MODEL_FILENAME)
```
**Source:** Verified against official RunPod model-store-cache-example repo

### Pattern 2: Offline Mode Guard

**What:** Set HF offline env vars to prevent accidental downloads during inference
**When to use:** Every worker that uses cached models
**Example:**
```python
import os

# In worker startup — prevent HF from trying to download at inference time
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
```

### Anti-Patterns to Avoid

- **Hard-coding the snapshot hash:** Hash changes on every HF commit; read from `refs/main` instead
- **Using `/runpod/model-store/` path:** Old path found in some docs — the correct path is `/runpod-volume/huggingface-cache/hub/`
- **Pointing cached models at the multi-quant unsloth repo directly:** RunPod will download 2.01 TB instead of 83.8 GB
- **Removing the seed flow before cached models is confirmed working:** Keep both paths until the new flow is validated
</architecture_patterns>

<dont_hand_roll>
## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Snapshot path resolution | Custom directory scanner | Read `refs/main` file (4 lines of Python) | HF format is stable; the file always exists when model is present |
| Private repo creation | Manual git LFS setup | `huggingface-cli upload` or `HfApi.upload_large_folder` | HF handles LFS chunking for large GGUFs automatically |
| Validating cached model presence | Runtime download fallback | Check path exists at startup, raise clear error | If cache miss, worker should fail fast with clear message, not silently re-download |

**Key insight:** The hard part of this phase is not code — it's the one-time HuggingFace repo setup and RunPod console configuration. The code changes in `nemotron.py` are minimal (replace hard-coded path with path resolver).
</dont_hand_roll>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Pointing at the Multi-Quant Unsloth Repo
**What goes wrong:** RunPod downloads all 23 quant variants (~2.01 TB) instead of the 3 UD-Q4_K_XL shards (~83.8 GB). This is an indefinitely long cold start and may fail entirely on disk space.
**Why it happens:** RunPod cached models currently offers no `allow_patterns` filtering — all files in the repo are downloaded.
**How to avoid:** Create a dedicated private HuggingFace repo containing only the 3 target GGUF files and point cached models at that repo.
**Warning signs:** Cold start does not finish; RunPod logs show downloading hundreds of files.

### Pitfall 2: Hard-Coding the Snapshot Hash in Model Path
**What goes wrong:** Model path breaks when the HuggingFace repo is updated (new commit hash).
**Why it happens:** Snapshot directories are named by commit hash, which changes on every push.
**How to avoid:** Always resolve the hash dynamically from `refs/main` or by listing `snapshots/`.
**Warning signs:** Worker starts but fails with "model file not found" after a repo update.

### Pitfall 3: Assuming Cached Model Cold Start Is "Seconds" for 80GB Models
**What goes wrong:** Expectations are set incorrectly; user thinks cold start will be sub-10 seconds.
**Why it happens:** RunPod docs quote "seconds" for cold start — this refers to *download time* being eliminated, not model *loading time* into VRAM. A 80GB model still takes 60–120 seconds to load into VRAM regardless.
**How to avoid:** Be clear in README: cold start = "download eliminated, but model still loads into VRAM in ~1-2 min". Network volume cold start was 8-10 min download + 1-2 min load; cached cold start is 0 min download + 1-2 min load.
**Warning signs:** Users complain cold start is still slow after migration.

### Pitfall 4: Removing Network Volume Before Verifying Cache Works
**What goes wrong:** Deployment is broken during transition if cached model path is wrong.
**Why it happens:** Path resolver misconfigured, or cached model not yet propagated.
**How to avoid:** Ship the path resolver update first, verify it works with volume-cached path, then switch to RunPod cached model. Keep the network volume as fallback.
**Warning signs:** Worker fails to find model file on cold start.

### Pitfall 5: Flash SDK Has No CachedModel API
**What goes wrong:** Developer searches for `CachedModel` class in `runpod_flash` and can't find it; wastes time trying to configure it in code.
**Why it happens:** RunPod cached models is configured **only via the RunPod console UI** (or GraphQL API), not via the Flash Python SDK `Endpoint` constructor.
**How to avoid:** Treat cached model configuration as an out-of-band step in the RunPod console, not a code change.
**Warning signs:** N/A — just awareness that it's a UI config, not code.
</common_pitfalls>

<code_examples>
## Code Examples

### Creating a Private Single-Quant HuggingFace Repo

```bash
# Install HF CLI
pip install huggingface_hub

# Log in
huggingface-cli login --token $HF_TOKEN

# Create private repo (run once)
huggingface-cli repo create nemotron-q4-xl --type model --private

# Upload the 3 GGUF shard files from network volume
# (Run this from a RunPod instance with volume mounted, or locally if you have the files)
huggingface-cli upload your-org/nemotron-q4-xl \
    /runpod-volume/models/UD-Q4_K_XL/ \
    --repo-type model

# Or with Python:
from huggingface_hub import HfApi
api = HfApi()
api.upload_large_folder(
    repo_id="your-org/nemotron-q4-xl",
    repo_type="model",
    folder_path="/runpod-volume/models/UD-Q4_K_XL/",
    private=True,
)
```

### Dynamic Model Path Resolver for nemotron.py

```python
# Source: Official RunPod model-store-cache-example repo pattern
import os

CACHE_BASE = "/runpod-volume/huggingface-cache/hub"
REPO_ID = "your-org/nemotron-q4-xl"
MODEL_FILENAME = "NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"

def get_cached_model_path() -> str:
    repo_dir = "models--" + REPO_ID.replace("/", "--")
    hub_path = os.path.join(CACHE_BASE, repo_dir)

    refs_path = os.path.join(hub_path, "refs", "main")
    if os.path.exists(refs_path):
        with open(refs_path) as f:
            commit_hash = f.read().strip()
    else:
        snapshots_dir = os.path.join(hub_path, "snapshots")
        commit_hash = os.listdir(snapshots_dir)[0]

    return os.path.join(hub_path, "snapshots", commit_hash, MODEL_FILENAME)
```

### Health Check Update for Cached Model Path

```python
@gpu_api.get("/health")
async def gpu_health() -> dict:
    import os, httpx

    model_path = get_cached_model_path()  # replaces hard-coded path
    llama_bin = "/app/llama-server"

    if not os.path.exists(model_path):
        return {"status": "missing_model", "model_path": model_path}
    if not os.path.exists(llama_bin):
        return {"status": "missing_binary", "binary": llama_bin}
    # ... rest unchanged
```

### RunPod Console Configuration (Out of Band)

```
# In RunPod Console → Serverless → Your Endpoint → Settings:
#
# Model section:
#   Hugging Face Model ID: your-org/nemotron-q4-xl
#   Hugging Face API Key:  [your HF_TOKEN]
#
# No changes to nemotron.py Endpoint() constructor needed.
```
</code_examples>

<sota_updates>
## State of the Art (2026)

| Old Approach | Current Approach | Notes |
|---|---|---|
| Network volume (seed + mount) | RunPod cached models | Eliminates $7/month fixed volume cost; eliminates 8-10 min download cold start |
| HuggingFace multi-quant repo | Private single-quant repo | Workaround for RunPod's "no selective files" limitation |
| Hard-coded model path | Dynamic snapshot resolver | Required for cached models' hash-based path structure |

**Known RunPod roadmap items (from official docs):**
- Selective quantization file download (currently downloads all files in repo) — planned but not yet available
- Multiple cached models per endpoint — currently one per endpoint maximum

**What this means:** If RunPod ships selective file patterns, the private repo workaround becomes unnecessary and the unsloth repo can be used directly.

**FlashBoot note:** FlashBoot is **orthogonal** to cached models — FlashBoot handles container snapshot caching, cached models handles the ML model files. They can be used together. However, this project currently has `flashboot=False` because the LB force-kills workers before a snapshot can be written. That constraint is independent of model caching.
</sota_updates>

<open_questions>
## Open Questions

1. **VRAM fit for UD-Q4_K_XL on current GPU**
   - What we know: `nemotron.py` now uses RTX Pro 6000 Blackwell (97GB VRAM), not A100 80GB. The UD-Q4_K_XL shard is ~83.8GB. With `--n-gpu-layers 99` and `--no-kv-offload`, this should fit.
   - What's unclear: Whether `--override-tensor "exps=CPU"` is still needed, or whether the 97GB VRAM is enough to hold everything in GPU.
   - Recommendation: Leave llama-server flags unchanged during this migration; model loading behavior is the same regardless of where the files come from.

2. **Private HF repo access from RunPod cached models**
   - What we know: RunPod console accepts an HF API key when configuring cached models, so private repos are supported.
   - What's unclear: Whether the key needs read-only scope or full access.
   - Recommendation: Use a read-only HF token for the cached model configuration.

3. **Can the seed flow be removed entirely?**
   - What we know: Seed flow downloads to `/runpod-volume/models/`. With cached models, model is at `/runpod-volume/huggingface-cache/hub/...`.
   - What's unclear: Whether users will still want the seed flow as a fallback during the cached models transition.
   - Recommendation: Keep `python nemotron.py seed` as an optional fallback, but update docs to note it's no longer the primary bootstrap path.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)
- https://docs.runpod.io/serverless/endpoints/model-caching — Official RunPod cached models docs
- https://github.com/runpod-workers/model-store-cache-example — Official working example (code confirmed)
- https://huggingface.co/unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF/tree/main — Confirmed: 2.01 TB, 23 quant variants
- https://github.com/runpod/flash — runpod-flash SDK source (confirmed: no CachedModel API)
- https://pypi.org/project/runpod-flash/ — v1.10.1 (March 17, 2026)

### Secondary (MEDIUM confidence)
- https://docs.runpod.io/tutorials/serverless/model-caching-text — Tutorial showing console configuration flow
- RunPod Discord/AnswerOverflow threads on cached models limitations (selective quant, one model per endpoint)

### Tertiary (LOW confidence — needs validation)
- Cold start timing estimate (60-120 seconds for 80GB VRAM load) — based on general knowledge of llama.cpp model loading speed; not RunPod-specific benchmarks
</sources>

<metadata>
## Metadata

**Research scope:**
- Core technology: RunPod serverless cached models feature
- Ecosystem: HuggingFace Hub CLI, runpod-flash SDK, RunPod console configuration
- Patterns: Dynamic snapshot path resolution, private single-quant repo workaround
- Pitfalls: Multi-quant repo limitation, hard-coded path, VRAM load time expectations

**Confidence breakdown:**
- Cached models feature behavior: HIGH — verified via official docs + working example repo
- "No selective files" limitation: HIGH — explicitly stated in official docs
- Unsloth repo size (2.01 TB, 23 quants): HIGH — directly fetched from HF repo tree
- Runtime path structure: HIGH — code confirmed from official example
- Flash SDK has no CachedModel API: HIGH — source code inspected
- Cold start timing: MEDIUM — qualitative, no large-model benchmarks found
- Private repo workaround: HIGH — logically follows from limitation + HF token support in console

**Research date:** 2026-03-22
**Valid until:** 2026-06-22 (90 days — feature is stable but RunPod may ship selective file filtering)
</metadata>

---

*Phase: 05-model-caching*
*Research completed: 2026-03-22*
*Ready for planning: yes*
