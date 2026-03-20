# Stack Research

**Domain:** Serverless AI inference deployment (RunPod Flash + llama-server GGUF)
**Researched:** 2026-03-20
**Confidence:** HIGH (core SDK API), MEDIUM (llama-server tuning flags), HIGH (model specs)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `runpod-flash` | `>=1.8.1` | Serverless GPU orchestration | Official SDK; `GpuGroup.AMPERE_80` targets A100 80GB; handles worker scaling, cold-start, HTTP routing |
| `ghcr.io/ggml-org/llama.cpp:server-cuda` | `b8457` (latest as of 2026-03-20) | OpenAI-compatible LLM inference server | Official llama.cpp image; CUDA 12.4.0; supports GGUF natively |
| Python | `3.12` | Runtime for Flash worker | Flash GPU workers deploy on Python 3.12 only; local dev supports 3.10–3.12 |
| `huggingface_hub` | `>=0.32.0` | Download GGUF model files from HuggingFace | Includes `hf_xet` for fast chunk-based downloads (replaces deprecated `hf_transfer`) |
| `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` | `UD-Q4_K_XL` quant | 120B MoE LLM weights | 83.8 GB total; fits on A100 80GB (leaves ~0 headroom — see notes); OpenAI reasoning-capable |

### Supporting Libraries

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| `huggingface-hub` CLI | `>=0.32.0` | `hf download` CLI for model pull in startScript | Enables `--include "UD-Q4_K_XL/*"` pattern filtering |
| NVIDIA Container Toolkit | host-level | GPU passthrough in Docker | Required on RunPod worker hosts — pre-installed on RunPod GPU nodes |
| CUDA | `12.4.0` | GPU acceleration | Bundled inside `ghcr.io/ggml-org/llama.cpp:server-cuda`; no separate install needed |

### Development Tools

| Tool | Version | Purpose |
|------|---------|---------|
| `uv` | latest | Recommended package manager for `runpod-flash` install |
| `flash` CLI | bundled with `runpod-flash` | `flash login`, `flash build`, local test runner |
| RunPod Network Volume | 100 GB | Persistent model cache across worker restarts; mounts at `/runpod-volume` |

---

## Installation

```bash
# Install runpod-flash (Python 3.10–3.12 required; 3.13+ NOT supported)
uv pip install "runpod-flash>=1.8.1"

# Or with pip
pip install "runpod-flash>=1.8.1"

# Authenticate
flash login
# or: export RUNPOD_API_KEY="..."
```

---

## RunPod Flash API Patterns

### Core Imports

```python
from runpod_flash import Endpoint, GpuGroup, NetworkVolume, PodTemplate
```

> Note: The SDK exposes `GpuGroup` (not `GpuType`) as the GPU enum in current versions. Earlier docs showed `GpuType` — use `GpuGroup`.

### GpuGroup Enum Values (relevant subset)

| Enum Value | GPU | VRAM |
|------------|-----|------|
| `GpuGroup.AMPERE_80` | A100 PCIe or SXM 80GB | 80 GB |
| `GpuGroup.ADA_80_PRO` | H100 PCIe/HBM3/NVL | 80 GB+ |
| `GpuGroup.HOPPER_141` | H200 | 141 GB |
| `GpuGroup.AMPERE_48` | A40 / A6000 | 48 GB |
| `GpuGroup.ANY` | Any available | varies |

### Endpoint Constructor — Full Parameter Reference

```python
Endpoint(
    name="endpoint-name",          # required (unless id= is set)
    id=None,                        # connect to existing endpoint by ID
    gpu=GpuGroup.AMPERE_80,         # single GPU type
    # gpu=[GpuGroup.AMPERE_80, GpuGroup.ADA_80_PRO],  # list = auto-select by availability
    workers=1,                      # shorthand for (0, 1); default is (0, 1)
    # workers=(1, 3),               # explicit (min, max) tuple
    idle_timeout=60,                # seconds before worker scales to 0
    image="ghcr.io/ggml-org/llama.cpp:server-cuda",  # pre-built Docker image
    env={
        "HF_TOKEN": "...",
        "MODEL_PATH": "/runpod-volume/models/nemotron",
    },
    volume=NetworkVolume(name="nemotron-models", size=100),  # persistent storage
    template=PodTemplate(containerDiskInGb=120),             # ephemeral container disk
    flashboot=True,                 # snapshot-based fast cold starts
    execution_timeout_ms=0,         # 0 = unlimited
)
```

**Key constraints:**
- `gpu` and `cpu` are mutually exclusive.
- `workers=N` expands to `(0, N)`. Default is `(0, 1)`.
- `workers=(min, max)` requires `min >= 5` to enable automatic GPU-type switching across a list.
- `idle_timeout` defaults to 60 seconds (scale-to-zero after 60 s of no requests).
- The `image=` parameter disables the decorator pattern — use instance pattern with `.post()` / `.get()` / `.run()`.
- Imports must occur INSIDE decorated functions (cloudpickle limitation). With `image=` this is irrelevant.
- 10 MB payload limit — pass URLs or file paths, not raw binary.

### NetworkVolume

```python
NetworkVolume(name="nemotron-models", size=100)  # size in GB; default 100
```

- Mounts at `/runpod-volume` inside the worker container.
- Persists across worker restarts/scale-downs — avoids re-downloading the 83.8 GB model.
- Do not write from multiple workers simultaneously (risk of corruption).

### PodTemplate

```python
PodTemplate(
    containerDiskInGb=120,   # ephemeral disk for container (default 64)
    dockerArgs="",           # extra docker run arguments
    ports="",                # exposed ports
    startScript=""           # shell script to run on container start
)
```

### HTTP Client Pattern (for `image=` deployments)

```python
import asyncio
from runpod_flash import Endpoint, GpuGroup, NetworkVolume, PodTemplate

server = Endpoint(
    name="nemotron-llama-server",
    image="ghcr.io/ggml-org/llama.cpp:server-cuda",
    gpu=GpuGroup.AMPERE_80,
    workers=1,
    env={"HF_TOKEN": os.environ["HF_TOKEN"]},
    volume=NetworkVolume(name="nemotron-models", size=100),
    template=PodTemplate(containerDiskInGb=120, startScript="/workspace/start.sh"),
    flashboot=True,
    idle_timeout=300,
)

# Direct HTTP forwarding
result = await server.post("/v1/chat/completions", {"model": "...", "messages": [...]})
models = await server.get("/v1/models")

# Queue-based (longer jobs)
job = await server.run({"input": {...}})
result = await job.wait()
```

---

## llama-server CLI Flags for Nemotron-3-Super-120B on A100 80GB

### Model Facts

- **Quant:** UD-Q4_K_XL
- **Total model size:** 83.8 GB
- **Architecture:** Hybrid MoE (Mamba + Transformer); 12B active / 120B total parameters
- **Default context:** 256k tokens (1M tokens possible with `LLAMA_ALLOW_LONG_MAX_MODEL_LEN=1`)
- **Files:** 3 split GGUF files, pattern: `NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-000NN-of-00003.gguf`
- **llama.cpp support added:** PR #20411, merged ~commit `88915cb55c` or later (build ≥ b4900 approx)

### A100 80GB VRAM Budget

| Component | Size |
|-----------|------|
| Model weights (UD-Q4_K_XL) | ~83.8 GB |
| KV cache @ 8k context | ~0.5 GB |
| Compute buffers | ~2–3 GB |
| **Total** | **~86+ GB** |

> **Critical:** 83.8 GB model weights alone exceed A100 80GB VRAM. You MUST use MoE expert CPU offloading via `--override-tensor` to keep routed expert weights on CPU RAM while offloading attention, dense FFN, and shared expert layers to GPU.

### Recommended llama-server Command

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
  --top-p 0.95
```

### Flag Reference

| Flag | Value | Purpose |
|------|-------|---------|
| `-ngl 99` | 99 | Offload all non-expert layers to GPU |
| `--override-tensor "exps=CPU"` | regex match `exps` | Keep all MoE routed expert weights in CPU RAM (frees ~50+ GB VRAM) |
| `-c 8192` | 8192 | Context size — keep small to conserve VRAM on A100 80GB |
| `-b 2048` | 2048 | Logical batch size |
| `-ub 512` | 512 | Physical micro-batch size (increase to 2048–4096 for throughput if VRAM allows) |
| `-fa` | — | Enable Flash Attention (reduces KV cache VRAM) |
| `--no-mmap` | — | Disable memory mapping — more predictable VRAM behavior on server |
| `-np 1` | 1 | Parallel slots (single request at a time; increase with VRAM headroom) |
| `--cont-batching` | — | Continuous/dynamic batching for better throughput |
| `--jinja` | — | Enable Jinja2 chat template rendering |
| `--temp 1.0 --top-p 0.95` | — | NVIDIA-recommended sampling parameters for all tasks |
| `--host 0.0.0.0` | — | Listen on all interfaces (required inside container) |
| `--port 8080` | 8080 | Default port |

### Advanced MoE Tuning (if more VRAM headroom available)

```bash
# More selective: keep only deeper expert layers on CPU, put earlier ones on GPU
--override-tensor "blk\.(6[0-9]|7[0-9]|8[0-9]|9[0-9]|[1-9][0-9]{2})\.ffn_.*_exps\.=CPU"

# Alternatively: use --n-cpu-moe flag (if available in build)
--n-cpu-moe 40

# Increase parallel slots if VRAM allows
-np 2

# For maximum prompt-processing throughput
-b 4096 -ub 4096
```

### Environment Variables (inside container)

```bash
GGML_CUDA_GRAPH_OPT=1          # CUDA graph optimization
LLAMA_SET_ROWS=1               # Row-based tensor operations for MoE
```

---

## HuggingFace Model Download Patterns

### Model Repository

```
unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF
```

### Python Download (recommended — uses hf_xet for fast chunked downloads)

```python
from huggingface_hub import snapshot_download

# Download only UD-Q4_K_XL quant (83.8 GB) to a specific local dir
snapshot_download(
    repo_id="unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF",
    local_dir="/runpod-volume/models/nemotron",
    allow_patterns="UD-Q4_K_XL/*",
    token=os.environ.get("HF_TOKEN"),  # required if repo is gated
)
```

### CLI Download

```bash
# Install tool
pip install -U "huggingface_hub>=0.32.0"

# Download only UD-Q4_K_XL split files
hf download unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF \
  --include "UD-Q4_K_XL/*" \
  --local-dir /runpod-volume/models/nemotron \
  --token "$HF_TOKEN"
```

### Single File Download (if split files need individual handling)

```python
from huggingface_hub import hf_hub_download

# llama.cpp can load multi-part GGUF by pointing to the first file
path = hf_hub_download(
    repo_id="unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF",
    filename="UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf",
    local_dir="/runpod-volume/models/nemotron",
    token=os.environ.get("HF_TOKEN"),
)
```

> llama.cpp auto-discovers split files when you pass the first split (`-00001-of-00003.gguf`).

---

## Docker Image Reference

| Image | CUDA | Purpose |
|-------|------|---------|
| `ghcr.io/ggml-org/llama.cpp:server-cuda` | 12.4.0 | Latest stable server (rolling tag) |
| `ghcr.io/ggml-org/llama.cpp:server-cuda-b8457` | 12.4.0 | Pinned to build b8457 (2026-03-20) |
| `ghcr.io/ggml-org/llama.cpp:full-cuda` | 12.4.0 | Full toolchain (server + convert + quantize) |

> Use `server-cuda` (rolling) or pin to a specific build tag like `server-cuda-b8457` for reproducibility.
> Old registry (`ghcr.io/ggerganov/llama.cpp`) is deprecated; use `ghcr.io/ggml-org/llama.cpp`.

### Docker Run Example (for local testing)

```bash
docker run --gpus all \
  -v /path/to/models:/models \
  -p 8080:8080 \
  ghcr.io/ggml-org/llama.cpp:server-cuda \
  -m /models/nemotron/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
  --host 0.0.0.0 --port 8080 \
  -ngl 99 --override-tensor "exps=CPU" \
  -c 8192 -fa --no-mmap
```

---

## Alternatives Considered

| Alternative | Why Not Chosen |
|-------------|---------------|
| **vLLM** | Doesn't support GGUF natively; requires BF16/FP8; needs 8× H100 for full Nemotron-120B |
| **SGLang** | Same GPU requirements as vLLM; no GGUF support |
| **TRT-LLM** | Requires multi-GPU (8× H100); complex build pipeline |
| **Ollama** | Convenient wrapper over llama.cpp but less control over server flags; less suited for RunPod serverless |
| **runpod-python (old SDK)** | Lower-level; requires writing a RunPod handler; Flash abstracts this away |
| **NVIDIA NIM** | Subscription/enterprise product; cost-prohibitive for single-dev ~$20/month budget |
| **UD-Q5_K_XL (5-bit)** | 89.7 GB — exceeds A100 80GB even with CPU offloading of experts; requires H100/H200 |
| **UD-Q3_K_M (3-bit)** | 61.7 GB — fits more comfortably; lower quality than Q4_K_XL |
| **BF16 / FP8** | 242 GB / requires compute capability 89+ (A100 is cc80, does NOT support FP8) |

---

## What NOT to Use

- **`hf_transfer`**: Deprecated as of `huggingface_hub>=0.32.0`; replaced by `hf_xet`.
- **`ghcr.io/ggerganov/llama.cpp`**: Old/deprecated registry path. Use `ghcr.io/ggml-org/llama.cpp`.
- **llama.cpp before commit `88915cb55c` (PR #20411)**: Will fail to load `UD-Q4_K_XL` with tensor shape error on `blk.1.ffn_down_exps.weight`. Always use build b4900+ or `server-cuda` latest.
- **`GpuType` enum**: Older API name. Current SDK uses `GpuGroup`.
- **FP8 quantization (MXFP4_MOE)**: A100 has compute capability 8.0 (not 8.9+); FP8 will throw a hardware capability error.
- **Python 3.13+**: Not yet supported by `runpod-flash`.
- **Module-level imports in decorated functions**: Will break serialization (cloudpickle). Always import inside the function body (only relevant in decorator/queue mode, not image= mode).

---

## Stack Patterns by Variant

### Pattern A: External Docker Image + HTTP Proxy (Recommended for this project)

Best when: using pre-built inference server (llama-server) inside container.

```python
server = Endpoint(
    name="nemotron-server",
    image="ghcr.io/ggml-org/llama.cpp:server-cuda-b8457",
    gpu=GpuGroup.AMPERE_80,
    workers=1,
    env={"HF_TOKEN": os.environ["HF_TOKEN"]},
    volume=NetworkVolume(name="nemotron-models", size=100),
    template=PodTemplate(containerDiskInGb=120, startScript="/start.sh"),
    idle_timeout=300,
    flashboot=True,
)
result = await server.post("/v1/chat/completions", {...})
```

### Pattern B: Decorator / Queue Mode (Not recommended for this project)

Best when: running Python ML code without a built-in HTTP server.

```python
@Endpoint(name="worker", gpu=GpuGroup.AMPERE_80, dependencies=["torch"])
async def infer(data):
    import torch
    ...
    return result
```

### Pattern C: Load-Balanced Routes

Best when: multiple endpoints needed on one worker.

```python
api = Endpoint(name="api", gpu=GpuGroup.AMPERE_80, workers=(1, 3))

@api.post("/v1/chat/completions")
async def chat(data: dict): ...

@api.get("/health")
async def health(): ...
```

---

## Version Compatibility Matrix

| Component | Required Version | Notes |
|-----------|-----------------|-------|
| `runpod-flash` | `>=1.8.1` | `GpuGroup.AMPERE_80` available |
| Python (local) | `3.10–3.12` | 3.13+ not supported |
| Python (worker) | `3.12` | GPU workers run Python 3.12 only |
| `huggingface_hub` | `>=0.32.0` | For `hf_xet` fast downloads |
| llama.cpp build | `>=b4900` (PR #20411 merged) | For UD-Q4_K_XL / MoE tensor support |
| CUDA (in container) | `12.4.0` | Bundled in `ghcr.io/ggml-org/llama.cpp:server-cuda` |
| A100 compute capability | `8.0` | FP8 NOT supported (requires 8.9+); GGUF Q4 works fine |

---

## Sources

### HIGH Confidence (official documentation / primary sources)

- [runpod/flash GitHub README + SKILL.md](https://github.com/runpod/flash) — GpuGroup enum, Endpoint parameters, PodTemplate, NetworkVolume API
- [runpod/flash-examples GitHub](https://github.com/runpod/flash-examples) — Example patterns including network volumes
- [RunPod Flash custom Docker images docs](https://docs.runpod.io/flash/custom-docker-images) — `image=`, `env=`, `template=`, HTTP proxy patterns
- [RunPod Flash quickstart](https://docs.runpod.io/flash/quickstart) — Install command, Python version requirements
- [runpod-flash PyPI](https://pypi.org/project/runpod-flash/) — Latest version 1.8.1
- [ggml-org/llama.cpp server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) — All CLI flags reference
- [llama.cpp Docker docs](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md) — Official Docker image names, CUDA 12.4.0 default
- [llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases) — Latest build b8457 (2026-03-20)
- [huggingface_hub download guide](https://huggingface.co/docs/huggingface_hub/guides/download) — `hf_hub_download`, `snapshot_download`, `allow_patterns`, `hf_xet`
- [unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF HuggingFace](https://huggingface.co/unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF) — Model sizes, quantization options, 83.8 GB for UD-Q4_K_XL

### MEDIUM Confidence (community guides / derived)

- [llama.cpp MoE offload guide (Doctor-Shotgun / HuggingFace Blog)](https://huggingface.co/blog/Doctor-Shotgun/llamacpp-moe-offload-guide) — `--override-tensor exps=CPU` pattern, batch size recommendations
- [llama.cpp gpt-oss-120b discussion #15396](https://github.com/ggml-org/llama.cpp/discussions/15396) — `-ngl 99 -fa -b 2048 -ub 2048` for 120B on 80GB GPU
- [Optimizing gpt-oss-120b (carteakey.dev)](https://carteakey.dev/blog/optimizing-gpt-oss-120b-local-inference/) — `--fit`, `--no-mmap`, `GGML_CUDA_GRAPH_OPT=1`, `LLAMA_SET_ROWS=1`
- [llama.cpp --override-tensor discussion #13154](https://github.com/ggml-org/llama.cpp/discussions/13154) — Regex syntax for tensor overrides

### HIGH Confidence (bug / compatibility reports)

- [UD-Q4_K_XL llama.cpp compatibility issue (HuggingFace discussion #2)](https://huggingface.co/unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF/discussions/2) — PR #20411, commit `88915cb55c` fix confirmed
- [NVIDIA blog on Nemotron-3-Super](https://developer.nvidia.com/blog/introducing-nemotron-3-super-an-open-hybrid-mamba-transformer-moe-for-agentic-reasoning/) — Architecture facts, temperature/top_p recommendations
