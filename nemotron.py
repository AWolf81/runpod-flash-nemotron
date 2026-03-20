"""
nemotron.py — RunPod Flash deployment script for Nemotron-3-Super-120B-Instruct.

Deploys a serverless endpoint on a single A100 80GB (AMPERE_80) that serves the
UD-Q4_K_XL GGUF quant via llama-server, exposing an OpenAI-compatible
/v1/chat/completions API.

Prerequisites:
  - RunPod account with Flash access
  - Network Volume pre-seeded with the model (see download_model.py)
  - runpod-flash >= 1.8.1 installed (`pip install runpod-flash`)

Deploy:
  flash deploy nemotron.py
"""

from runpod_flash import Endpoint, GpuGroup, NetworkVolume, FlashBoot

# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

# GGUF quant filename on the network volume.
# Update this if you download a different quant variant.
MODEL_FILENAME = "Nemotron-3-Super-120B-Instruct-UD-Q4_K_XL.gguf"

# Path where the network volume is mounted inside the container.
MODEL_DIR = "/workspace/models"

MODEL_PATH = f"{MODEL_DIR}/{MODEL_FILENAME}"

# ---------------------------------------------------------------------------
# llama-server command
# ---------------------------------------------------------------------------

# Context window options (KV cache lives in VRAM, ~320KB/token):
#   -c 32768   ~10 GB KV  — safe default, good for most coding tasks
#   -c 65536   ~20 GB KV  — larger files, multi-file context
#   -c 131072  ~40 GB KV  — experimental; test for OOM before relying on it
#   -c 200000            — likely OOM on A100 80GB with this model
# Non-expert weights use ~25-30 GB, leaving ~50 GB for KV cache.

LLAMA_SERVER_CMD = (
    "llama-server"
    " -ngl 99"                              # Offload all layers to GPU (use a number >= actual layer count)
    f' --override-tensor "exps=CPU"'        # MoE expert weights (~80% of params) exceed VRAM; offloaded to CPU RAM. Non-expert weights + KV cache stay in VRAM.
    " -c 32768"                             # Context window — see comment block above for scaling options
    " -fa"                                  # Flash Attention — required for large context without OOM
    " --no-mmap"                            # Disable memory mapping; load model fully into RAM before serving
    " -np 1"                                # One parallel slot; serverless handles concurrency by spawning instances
    " --cont-batching"                      # Continuous batching for throughput when multiple requests queue
    " --port 8080"
    f" --model {MODEL_PATH}"
)

# ---------------------------------------------------------------------------
# Endpoint definition
# ---------------------------------------------------------------------------

endpoint = Endpoint(
    name="nemotron-super-120b",

    # A100 80GB PCIe — minimum GPU for this model.
    # ~$1.89/hr on RunPod; at $20/month you get ~10.5 GPU-hours.
    gpu=GpuGroup.AMPERE_80,

    # 100 GB network volume pre-seeded with the model file.
    # Mount path must match MODEL_DIR above and the path used in download_model.py.
    volume=NetworkVolume(
        size_gb=100,
        mount_path=MODEL_DIR,
    ),

    # FlashBoot caches the container image layer so subsequent cold starts
    # skip the image pull and only wait for the model to load into RAM.
    flash_boot=FlashBoot(enabled=True),

    # The command that runs inside the container on each worker startup.
    # llama-server binds to port 8080; RunPod proxies it to the endpoint URL.
    cmd=LLAMA_SERVER_CMD,

    # 120B model needs >10 min for long responses; default 600s will kill mid-generation.
    execution_timeout=1800,

    # Scale to zero after 60s idle; lower = less billing for short coding sessions,
    # higher = faster response if switching tasks frequently.
    idle_timeout=60,

    # Workers: (min, max). (0, 1) = scale-to-zero (cheapest, ~2-5 min cold start).
    # Change to (1, 1) for always-on (instant response, ~$1.89/hr always).
    workers=(0, 1),
)
