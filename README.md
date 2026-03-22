# runpod-flash-nemotron

Run NVIDIA Nemotron-3-Super-120B-A12B GGUF on RunPod Flash with a shared network volume and expose it as an OpenAI-compatible API for Claude Code, OpenCode, and Mistral Vibe.

## What You Get

- One-file RunPod Flash deployment in [nemotron.py](nemotron.py)
- One-time remote seeding job that downloads the model and builds `llama-server` on the volume: `python nemotron.py seed`
- OpenAI-compatible `llama-server` endpoint on RTX Pro 6000 Blackwell (97 GB VRAM)
- Copy-paste integration guides for Claude Code, OpenCode, and Mistral Vibe in [docs/integrations](docs/integrations)

## Prerequisites

- RunPod account with Flash access
- Hugging Face token with access to `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF`
- Python 3.11+

> **New to RunPod?** Sign up via [runpod.io?ref=nqca85x5](https://runpod.io?ref=nqca85x5) to get **$5 free credit**. It also supports this repo with RunPod credits — thank you!

See the [RunPod Flash getting started guide](https://www.runpod.io/blog/introducing-flash-run-gpu-workloads-on-runpod-serverless-no-docker-required#get-started) for account setup and API key configuration.

```bash
pip install runpod-flash
flash login
```

## Setup (One Time)

**1. Export credentials:**

```bash
export RUNPOD_API_KEY="rp_your_runpod_key"
export HF_TOKEN="hf_your_huggingface_token"
```

**2. Seed the model and build `llama-server` into the network volume:**

```bash
HF_TOKEN=hf_... python nemotron.py seed
```

This starts a temporary remote worker that:
1. Builds `llama-server` from source and caches the binary to the volume
2. Downloads the GGUF shards (~84 GB) from Hugging Face into the volume

Both steps are idempotent — re-running `seed` skips anything already present and returns immediately. Cold starts after seeding restore the binary from the volume and load the model into VRAM (~1–2 min), with no download or build step.

**CLI options:**

```bash
python nemotron.py seed                          # skip if binary and model already present
python nemotron.py seed --clean-binary           # force rebuild of llama-server (~10 min)
python nemotron.py seed --clean-model            # re-download model (~84 GB)
python nemotron.py seed --clean-binary --clean-model  # full rebuild + re-download
```

**Why seeding is necessary:** RunPod serverless workers are stateless — they boot from a fresh container every time. The network volume persists across workers, so the model and binary are available immediately on every cold start without re-downloading or recompiling.

**Network volume cost:** ~$0.07/GB/month on RunPod, so the 100 GB volume costs approximately **$7/month** regardless of whether any workers are running. This is a fixed baseline cost on top of per-second GPU charges.

**3. Create your deployment environments:**

```bash
flash env create develop
flash env create staging
flash env create production
```

## Development Workflow

```
flash run  →  iterate locally  →  flash deploy --env production
```

**Local dev with live GPU workers:**

```bash
flash run
# or pre-provision to avoid cold starts on first request:
flash run --auto-provision
```

`flash run` starts a local dev server at `localhost:8888`, provisions real GPU workers on RunPod, and hot-reloads on code changes. Ctrl+C shuts everything down and cleans up remote resources automatically.

**Trigger provisioning** by hitting any endpoint — the worker is not spun up until the first request:

```bash
curl http://localhost:8888/nemotron-super-120b/v1/models
```

The URL pattern is `http://localhost:8888/<endpoint-name>/<route>`. This first request will block while the worker boots and loads the model (~5–10 min on first cold start while building llama-server, ~8–10 min on subsequent cold starts once the binary is cached to the volume).

**Test inference:**

```bash
curl http://localhost:8888/nemotron-super-120b/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello"}], "max_tokens": 50}'
```

**Deploy when ready:**

```bash
flash deploy --env develop      # test on dedicated dev environment
flash deploy --env staging      # pre-production check
flash deploy --env production   # live
```

**Inspect environments:**

```bash
flash env list
flash env get production
flash undeploy list
```

## Worker Debugging

### Checking Endpoint Health (No SSH)

```bash
# Is the endpoint up and model/binary present?
curl https://<your-endpoint-url>/health
# → {"status": "ready"}          — model loaded, safe to send requests
# → {"status": "warming_up"}     — llama-server process started, still loading model (~3-5 min)
# → {"status": "cold"}           — worker up but warmup not triggered yet (call /warmup)
# → {"status": "missing_binary"} — run /admin/install
# → {"status": "missing_model"}  — run HF_TOKEN=hf_... python nemotron.py seed
```

### Admin Endpoints

```bash
# Trigger llama-server install (uses volume cache if available, otherwise builds ~5-10 min)
curl -X POST https://<your-endpoint-url>/admin/install \
  -H "Content-Type: application/json" -H "Authorization: Bearer <token>" -d '{}'

# Force a full rebuild and recache (e.g. after updating the build script)
curl -X POST https://<your-endpoint-url>/admin/install \
  -H "Content-Type: application/json" -H "Authorization: Bearer <token>" -d '{"force": true}'
```

`/admin/install` returns `returncode`, truncated stdout/stderr, and whether the binary and volume cache are present.

### Getting an SSH Connection

1. Go to [console.runpod.io](https://console.runpod.io)
2. Navigate to **Serverless** in the left sidebar
3. Find **nemotron-super-120b** (the endpoint provisioned by `flash run` or `flash deploy`)
4. Click **Workers** tab
5. Find a worker with status **Running** and click it
6. In the side panel, click the **Connect** tab
7. Copy the SSH command and paste it into your terminal

### Checking llama-server (SSH)

```bash
# Is the binary present?
/app/llama-server --version

# Is the volume-cached binary present?
ls -lh /runpod-volume/cache/llama-server

# Is it already running?
pgrep -a llama-server

# Check GPU memory usage
nvidia-smi
```

### Installing llama-server if Missing (SSH)

```bash
bash /app/patches/install_llama_server.sh
```

The script checks the volume cache first — if a cached binary exists it copies it in seconds. Only falls through to a full build (~5–10 min) if neither local nor cached binary is present.

If `patches/` is not on the container (startScript never ran), copy-paste this directly:

```bash
set -euo pipefail
BINARY="/app/llama-server"
VOLUME_CACHE="/runpod-volume/cache/llama-server"

if [[ -x "${VOLUME_CACHE}" ]] && "${VOLUME_CACHE}" --version &>/dev/null; then
    echo "==> Restoring from volume cache"
    cp "${VOLUME_CACHE}" "${BINARY}"
    chmod +x "${BINARY}"
    "${BINARY}" --version
else
    pip install "cmake>=3.28"
    BUILD_DIR="/tmp/llama-cpp-build"
    rm -rf "${BUILD_DIR}"
    git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "${BUILD_DIR}"
    cmake "${BUILD_DIR}" -B "${BUILD_DIR}/build" \
        -DBUILD_SHARED_LIBS=OFF -DGGML_CUDA=ON \
        -DCMAKE_CUDA_ARCHITECTURES="80"
    cmake --build "${BUILD_DIR}/build" --config Release -j$(nproc) --target llama-server
    cp "${BUILD_DIR}/build/bin/llama-server" "${BINARY}"
    chmod +x "${BINARY}"
    mkdir -p "$(dirname "${VOLUME_CACHE}")"
    cp "${BINARY}" "${VOLUME_CACHE}"
    chmod +x "${VOLUME_CACHE}"
    rm -rf "${BUILD_DIR}"
    "${BINARY}" --version
fi
```

If a volume cache exists from a previous worker, this completes in seconds. Otherwise it's a full build (~5–10 min) and caches the result for future workers.

### Starting llama-server Manually

**Important:** do not offload layers to CPU — it explodes the compute buffer from ~282 MiB to ~2,500 MiB and causes CUDA OOM. Keep all layers on GPU and move the KV cache to RAM instead:

```bash
# Loading takes 8–10 minutes. The bottleneck is reading 78 GiB of model
# weights from the network volume (backed by S3) at ~0.4 GB/s into GPU VRAM.
/app/llama-server \
  --model /runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf \
  --host 127.0.0.1 --port 8081 \
  --n-gpu-layers 99 \
  --no-kv-offload \
  --parallel 1 \
  --ctx-size 32768 \
  --flash-attn on &

until curl -s http://127.0.0.1:8081/health | grep -q "ok"; do echo "waiting..."; sleep 5; done && echo "Ready"
```

### Testing Inference

```bash
# Quick health check
curl -s http://127.0.0.1:8081/health

# List models
curl -s http://127.0.0.1:8081/v1/models | python3 -m json.tool

# Chat completion
curl -s http://127.0.0.1:8081/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron","messages":[{"role":"user","content":"Say hello in one sentence."}],"max_tokens":50}' \
  | python3 -m json.tool
```

## Daily Usage: warmup.sh

Run [warmup.sh](warmup.sh) at the start of each session and keep it running in a terminal. It scales the endpoint to 1 worker, waits until the model is loaded, then keeps the worker alive. Press **Ctrl+C** when done — it automatically scales back to 0 workers and billing stops.

```bash
RUNPOD_API_KEY=rp_... bash warmup.sh
```

Output during a session:

```
==> Scaling endpoint to 1 worker (max 2 for overflow)...
==> Triggering warmup...
==> Waiting for model to load (polling every 10s, keeping worker alive)...
    09:01:12 — cold
    09:01:22 — warming_up
    09:01:32 — warming_up
    ...
    09:04:01 — ready

==> Ready! Nemotron is loaded and serving requests.
    Keep this terminal open — Ctrl+C will scale down the endpoint and stop billing.
```

**Do not close this terminal while working.** When you press Ctrl+C, the endpoint scales to 0 and no GPU is allocated until you run warmup.sh again.

## Cold Starts and FlashBoot Limitation

Cold start cost (model load from network volume into GPU VRAM):

- **First cold start ever**: ~13–20 min — builds llama-server from source (~5–10 min) + loads 78 GiB model (~8–10 min). Binary is then cached to `/runpod-volume/cache/llama-server`.
- **Subsequent cold starts**: ~8–10 min — restores binary from volume cache (seconds) + loads 78 GiB model (~8–9 min).

**Why not FlashBoot?** FlashBoot would snapshot the warm worker and restore it in ~10s on the next cold start — eliminating the 8–10 min wait. However, the Flash load balancer force-kills idle workers after ~5 minutes, before RunPod can write the snapshot. This makes FlashBoot unreliable for this setup and it is currently disabled.

**Why always-on workers?** With `workers=(0,2)` and no active requests, the Flash LB scaler aggressively kills workers within ~5 minutes regardless of `idle_timeout`. Sending keepalive requests during model loading prevents premature shutdown, but once the model is warm you need at least 1 worker kept alive by the scaler. The warmup.sh script manages this by scaling to `workers=(1,2)` at session start and back to `workers=(0,2)` on Ctrl+C.

## Context and Memory

Default: `--ctx-size 32768`, all layers on GPU.

For longer context with 250 GB RAM available:

```bash
--n-gpu-layers 85 --no-kv-offload --ctx-size 131072 --parallel 1
```

KV cache for the 8 attention layers at 128k context is ~781 MiB in RAM. The SSM recurrent state (659 MiB) is fixed regardless of context length.

## Cost Notes

- **GPU**: RTX Pro 6000 Blackwell (97GB VRAM) — only GPU with enough VRAM that isn't cost-prohibitive. A100/H100 80GB OOM on this model; H200/B200 work but cost 3–4× more with no benefit.
- **Price**: ~$1.69/hr on RTX Pro 6000 Blackwell
- **Billing**: only while a worker is running. The warmup.sh script starts/stops billing automatically.
- **Estimated cost**: 8h/day × $1.69 × 22 working days ≈ **~$297/month**
- **Fixed baseline**: network volume ~$7/month regardless of GPU usage
- **Network volume**: 100 GB at ~$0.07/GB/month

<details>
<summary>Aside: running this model on your own hardware (March 2026 snapshot prices, no accuracy guarantee)</summary>

The RTX Pro 6000 Blackwell (96 GB GDDR7) is the same GPU used on RunPod and fits in a standard full-tower desktop. It requires a 1600W ATX 3.0 PSU (600W TDP) and a workstation platform to support enough RAM.

**Why you need a workstation platform:** Running an 84 GB GGUF with mmap keeps a copy of the model in system RAM as a page cache alongside the VRAM copy. Consumer platforms (AM5, LGA1851) max out at 192 GB — not enough. Threadripper PRO on WRX90 supports up to 2 TB DDR5 ECC.

**Estimated build cost (March 2026):**

| Component | Choice | ~Price |
|-----------|--------|--------|
| GPU | RTX PRO 6000 Blackwell 96GB (PNY) | $7,999 |
| CPU | Threadripper PRO 9955WX (16-core Zen 5) | $1,649 |
| Motherboard | ASUS Pro WS WRX90E-SAGE SE (EEB) | $1,247 |
| RAM | 256GB DDR5 ECC RDIMM (8×32GB) | ~$3,500–4,500 |
| NVMe | Samsung 990 PRO 4TB | $699 |
| PSU | ASUS ROG Thor 1600W Titanium | $753 |
| Case + cooler | Full-tower EEB + TR5 cooler | ~$400 |
| **Total** | | **~$16,000–17,500** |

RAM is the biggest wildcard — DDR5 RDIMM prices rose sharply in early 2026.

**Break-even vs RunPod at $1.69/hr:**

| Usage | RunPod/month | Break-even |
|-------|-------------|-----------|
| 100 hrs/month | $169 | ~8 years |
| 200 hrs/month | $338 | ~4 years |
| 400 hrs/month | $676 | ~2 years |
| 24/7 | $1,217 | ~14 months |

For occasional coding assistant use, RunPod is cheaper for 3–4 years. The hardware makes sense for heavy daily use (300+ hrs/month), data privacy requirements, or zero cold-start latency.

</details>

## Known Limitations

- **Live deployment not yet fully verified** — this repo is under active debugging. Core seeding and deployment flows work, but behavior on first cold start after a fresh volume may differ.
- **LICENSE not yet added** — MIT license is planned but the `LICENSE` file has not been added to this repository yet.
- **Streaming not supported** — SSE streaming is disabled through the Flash LB; see `stream: False` in `chat_completions`. Non-streaming responses only.
- **EU-RO-1 only** — RunPod Flash serverless is currently restricted to the EU-RO-1 datacenter. Expect higher latency from outside Europe.

## Integration Guides

- Claude Code: [docs/integrations/claude-code.md](docs/integrations/claude-code.md)
- OpenCode: [docs/integrations/opencode.md](docs/integrations/opencode.md)
- Mistral Vibe: [docs/integrations/mistral-vibe.md](docs/integrations/mistral-vibe.md)

### Open WebUI

```bash
WEBUI_AUTH=False \
AIOHTTP_CLIENT_TIMEOUT_MODEL_LIST=60 \
AIOHTTP_CLIENT_TIMEOUT=300 \
OPENAI_API_KEY=$RUNPOD_API_KEY \
OPENAI_API_BASE_URL=https://<RUNPOD_ID>.api.runpod.ai/v1 \
open-webui serve
```

Replace `<RUNPOD_ID>` with your endpoint ID from the RunPod console. The extended timeouts are required because model list and completion requests can take longer than the default limits on a 120B model.
