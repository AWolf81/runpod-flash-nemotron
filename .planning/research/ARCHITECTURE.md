# Architecture Research

**Domain:** Serverless AI inference deployment (RunPod Flash + llama-server GGUF)
**Researched:** 2026-03-20
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
Developer machine
  │
  ├── nemotron.py          (RunPod Flash deployment script)
  │     └── flash deploy   ────────────────────────────────────────────────────────────┐
  │                                                                                    │
  └── Client tools                                                        RunPod EU-RO-1 datacenter
        ├── Claude Code (~/.claude/settings.json)                                      │
        ├── OpenCode (~/.config/opencode/config.json)   ←── HTTPS ───── RunPod Proxy URL
        └── Mistral Vibe (OPENAI_BASE_URL env var)                                     │
                                                                            Worker (A100 80GB)
                                                                                       │
                                                                  ┌────────────────────┴─────┐
                                                                  │   llama-server (GGUF)    │
                                                                  │   /v1/chat/completions   │
                                                                  └───────────┬──────────────┘
                                                                              │ loads from
                                                                  ┌───────────┴──────────────┐
                                                                  │  Network Volume (100 GB) │
                                                                  │  /runpod-volume/models/  │
                                                                  └──────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| `nemotron.py` | Declares serverless endpoint configuration | Python file with `Endpoint`, `GpuGroup`, `NetworkVolume` objects; run once via `flash deploy` |
| RunPod Flash SDK | Translates Python config into RunPod API calls | `runpod-flash>=1.8.1`; handles worker lifecycle |
| RunPod Proxy | Routes HTTPS requests to active workers | Managed by RunPod; exposes stable `api.runpod.ai/v2/{id}/openai/v1` URL |
| Worker container | Runs llama-server process | Official `ghcr.io/ggml-org/llama.cpp:server-cuda` image; no custom image needed |
| llama-server | OpenAI-compatible inference API | Exposes `/v1/chat/completions` on port 8080; handles GGUF model loading |
| Network Volume | Persistent 100 GB model cache | Mounts at `/runpod-volume`; survives worker scale-down |

## Recommended Project Structure

```
runpod-flash-nemotron/
├── nemotron.py              # Single deployment script (RunPod Flash config)
├── download_model.py        # One-time model pre-population helper
├── README.md                # Quickstart + integration guides
├── LICENSE                  # MIT
└── .gitignore               # Exclude .env, secrets
```

### Structure Rationale

- **Single deployment file:** The core value proposition — one file, one command. No `src/`, no packages.
- **Separate download helper:** Model pre-population is a prerequisite, not part of the deployment itself. Separating it makes the quickstart clearer.

## Architectural Patterns

### Pattern 1: Deployment Script as Config

**What:** `nemotron.py` is purely declarative — it creates Python objects (`Endpoint`, `GpuGroup.AMPERE_80`, `NetworkVolume`) and `flash deploy` reads them. No business logic in the deployment script.

**When to use:** Always — this is the RunPod Flash model.

**Trade-offs:** Simple and readable, but not a general-purpose Python script. The objects only do anything when executed via `flash deploy`.

**Example:**
```python
from runpod_flash import Endpoint, GpuGroup, NetworkVolume
import os

volume = NetworkVolume(name="nemotron-model", size=100)

endpoint = Endpoint(
    name="nemotron-super",
    image="ghcr.io/ggml-org/llama.cpp:server-cuda",
    gpu=GpuGroup.AMPERE_80,
    workers=(0, 1),           # scale-to-zero
    idle_timeout=300,
    flashboot=True,
    volume=volume,
    volume_mount_path="/runpod-volume",
    container_disk_in_gb=120,
    execution_timeout=1800,   # 30 min — required for 120B model
    env={
        "HF_TOKEN": os.environ["HF_TOKEN"],
        "LLAMA_API_KEY": os.environ["LLAMA_API_KEY"],
    },
    cmd=["/bin/sh", "-c", "...llama-server startup command..."],
)
```

---

### Pattern 2: llama-server as the API Handler

**What:** llama-server handles all inference requests directly — no FastAPI wrapper, no custom handler. RunPod's proxy routes directly to port 8080.

**When to use:** Always for this use case — no custom logic needed.

**Trade-offs:** Simpler than writing a RunPod handler function, but less flexible. No pre/post processing hooks.

**Example startup command (in `cmd=`):**
```bash
llama-server \
  -m /runpod-volume/models/nemotron/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
  --host 0.0.0.0 \
  --port 8080 \
  -ngl 99 \
  --override-tensor "exps=CPU" \
  -c 8192 \
  -b 2048 \
  -ub 512 \
  -fa \
  --no-mmap \
  -np 1 \
  --cont-batching \
  --jinja \
  --temp 1.0 \
  --top-p 0.95 \
  --api-key "$LLAMA_API_KEY"
```

---

### Pattern 3: Download-If-Absent Model Caching

**What:** `download_model.py` checks if the model already exists on the network volume before downloading. On subsequent cold starts, llama-server loads directly from the cached files.

**When to use:** Required — without pre-population, cold starts exceed RunPod's initialization timeout.

**Trade-offs:** Requires an explicit one-time setup step before first deploy. Must be documented clearly in README.

**Example:**
```python
from huggingface_hub import snapshot_download
import os, pathlib

MODEL_DIR = pathlib.Path("/runpod-volume/models/nemotron")
FIRST_SHARD = MODEL_DIR / "NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"

if not FIRST_SHARD.exists():
    snapshot_download(
        repo_id="unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF",
        local_dir=str(MODEL_DIR),
        allow_patterns="UD-Q4_K_XL/*",
        token=os.environ["HF_TOKEN"],
    )
    print("Model cached to network volume.")
else:
    print("Model already cached — skipping download.")
```

## Data Flow

### Request Flow

```
Client (Claude Code / OpenCode / Mistral Vibe)
  │
  │  POST https://api.runpod.ai/v2/{ENDPOINT_ID}/openai/v1/chat/completions
  │  Authorization: Bearer <LLAMA_API_KEY>
  │
  ▼
RunPod Proxy (EU-RO-1)
  │  routes to active worker; queues if cold-starting
  │
  ▼
Worker Container (A100 80GB)
  │
  ▼
llama-server :8080
  │  loads model from /runpod-volume/models/nemotron/ (already cached)
  │  GPU: attention + dense FFN + shared experts (~30 GB VRAM)
  │  CPU: MoE routed expert weights (~55 GB RAM)
  │
  ▼
JSON response (OpenAI format) → Client
```

### VRAM Budget

| Component | Location | Approx Size |
|-----------|----------|-------------|
| Non-expert layers (attention, dense FFN, shared experts) | GPU VRAM | ~25–30 GB |
| MoE routed expert weights (`exps=CPU`) | CPU RAM | ~55 GB |
| KV cache at `-c 8192` | GPU VRAM | ~0.5 GB |
| Compute buffers | GPU VRAM | ~2–3 GB |
| **GPU total** | | **~30 GB / 80 GB used** |
| **CPU RAM total** | | **~55 GB** |

### Key Data Flows

1. **First deploy:** `nemotron.py` → `flash deploy` → RunPod creates endpoint → Network Volume mounted → llama-server starts → `/health` returns 200 → endpoint is live
2. **Cold start (scale-to-zero):** Request arrives → RunPod allocates A100 → container starts → llama-server loads model from volume (~2–3 min) → request served
3. **Warm request:** Request arrives → RunPod routes to running worker → llama-server generates response → tokens streamed back

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| 1 developer, occasional use | `workers=(0, 1)`, `idle_timeout=300` — scale-to-zero; pay only for active sessions |
| 1 developer, active day | `workers=(0, 1)`, `idle_timeout=600` — longer warm window reduces cold starts |
| 1 developer, always-on | `workers=(1, 1)` — ~$1.89/hr; eliminates cold starts entirely |
| Team (not recommended) | Would require multiple endpoints or higher `-np` slots; exceeds $20/month; out of scope |

### Scaling Priorities

1. **First bottleneck:** Cold start latency — solved by FlashBoot + Network Volume caching
2. **Second bottleneck:** Token throughput — ~14 t/s with CPU offloading; not bottlenecked for single-user dev use

## Anti-Patterns

### Anti-Pattern 1: Downloading Model on Every Cold Start

**What people do:** Omit the network volume and download the model inside the container startup script.

**Why it's wrong:** 83.8 GB download exceeds RunPod's ~7-minute worker initialization timeout. Endpoint cycles in a failed-init loop indefinitely.

**Do this instead:** Pre-populate a 100 GB network volume once via `download_model.py`, then mount it in every worker.

---

### Anti-Pattern 2: Hardcoding Secrets in `nemotron.py`

**What people do:** Set `env={"HF_TOKEN": "hf_xxxx..."}` directly in the script.

**Why it's wrong:** If `nemotron.py` is committed to a public repo, the token is permanently exposed in git history.

**Do this instead:** Read from local environment: `env={"HF_TOKEN": os.environ["HF_TOKEN"]}`. Configure the actual values in RunPod Secrets.

---

### Anti-Pattern 3: Default Context Window

**What people do:** Omit `-c` flag, letting llama-server use its default (can be 32k–256k).

**Why it's wrong:** Context windows beyond ~8192 tokens on A100 80GB exceed the VRAM budget. Worker is SIGKILL'd mid-response; endpoint goes unhealthy.

**Do this instead:** Always set `-c 8192` explicitly. Document the limitation in README.

---

### Anti-Pattern 4: No `--api-key` on llama-server

**What people do:** Start llama-server without authentication.

**Why it's wrong:** Anyone who discovers the RunPod proxy URL can use your endpoint and bill your account.

**Do this instead:** Always set `--api-key "$LLAMA_API_KEY"` in the server startup command. Keep the proxy URL private.

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| HuggingFace | `snapshot_download` via `huggingface_hub>=0.32.0` | Requires `HF_TOKEN`; download to network volume once |
| RunPod Flash | `flash login` + `flash deploy nemotron.py` | `RUNPOD_API_KEY` env var required |
| RunPod Proxy | HTTPS to `api.runpod.ai/v2/{id}/openai/v1` | Stable URL; survives worker restarts |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `nemotron.py` ↔ RunPod Flash API | `flash deploy` CLI call | One-way; script declares config, CLI pushes it |
| RunPod Proxy ↔ Worker | Internal HTTP (port 8080) | Managed by RunPod; no configuration needed |
| Worker ↔ Network Volume | POSIX filesystem | Mounted at `/runpod-volume`; model files at `/runpod-volume/models/nemotron/` |

## Sources

- RunPod Flash SDK documentation — `Endpoint`, `GpuGroup`, `NetworkVolume`, `flashboot`, `idle_timeout`, `execution_timeout` patterns (HIGH confidence)
- `stanchino/runpod-llama.cpp` — community reference implementation of subprocess + health-poll architecture (MEDIUM confidence)
- llama.cpp server documentation — CLI flags, GGUF loading, `--override-tensor` (HIGH confidence)
- RunPod community forums — `GpuGroup.AMPERE_80` vs deprecated `GpuType`, EU-RO-1 restrictions (MEDIUM confidence)
- NVIDIA Nemotron-3-Super model card + unsloth HuggingFace discussion — VRAM requirements, `--override-tensor "exps=CPU"` necessity (HIGH confidence)

---
*Architecture research for: Serverless AI inference deployment (runpod-flash-nemotron)*
*Researched: 2026-03-20*
