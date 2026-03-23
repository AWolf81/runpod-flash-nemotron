"""
nemotron.py — RunPod Flash deployment for Nemotron-3-Super-120B-Instruct.

This project has two flows:

1. One-time remote model seeding:
     HF_TOKEN=hf_... python nemotron.py seed

2. Inference deployment:
     flash deploy

`python nemotron.py seed` runs locally, but it submits a temporary remote job on
RunPod that downloads the model into the shared network volume. That seed job is
not part of the deployed Flash app surface.
"""

import asyncio
import os
import subprocess
import sys
import threading
import time

from runpod_flash import Endpoint, GpuType, NetworkVolume
from runpod_flash.core.resources.template import PodTemplate


def _auto_start():
    """Run install script and start llama-server in background at app startup."""
    subprocess.Popen(["bash", "/app/patches/install_llama_server.sh"])


if os.path.exists("/app/patches/install_llama_server.sh"):
    threading.Thread(target=_auto_start, daemon=True).start()

VOLUME_NAME = "nemotron-model-cache"
MODEL_DIR = "/runpod-volume/models/UD-Q4_K_XL"
MODEL_FILENAME = "NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"
MODEL_PATH = f"{MODEL_DIR}/{MODEL_FILENAME}"

GPU_INFERENCE_ENDPOINT_NAME = "nemotron-super-120b"

# ── Cached Model Configuration ────────────────────────────────────────────────
# RunPod cached models mounts the HF repo at:
#   /runpod-volume/huggingface-cache/hub/models--org--repo/snapshots/{hash}/
# Set CACHED_REPO_ID to your private single-quant repo (org/repo-name).
# Leave as empty string to fall back to the network volume path (MODEL_PATH).
CACHED_REPO_ID = ""  # e.g. "your-org/nemotron-q4-xl"
CACHED_CACHE_BASE = "/runpod-volume/huggingface-cache/hub"


def get_cached_model_path() -> str | None:
    """
    Resolve the HuggingFace snapshot path for a RunPod cached model.

    Returns the path to the first GGUF shard if CACHED_REPO_ID is set and the
    cache directory exists. Returns None if CACHED_REPO_ID is empty or the
    cache is missing (caller falls back to MODEL_PATH from network volume).
    """
    if not CACHED_REPO_ID:
        return None

    repo_dir = "models--" + CACHED_REPO_ID.replace("/", "--")
    hub_path = os.path.join(CACHED_CACHE_BASE, repo_dir)

    refs_path = os.path.join(hub_path, "refs", "main")
    if os.path.exists(refs_path):
        with open(refs_path) as f:
            commit_hash = f.read().strip()
    else:
        snapshots_dir = os.path.join(hub_path, "snapshots")
        if not os.path.isdir(snapshots_dir):
            return None
        entries = [e for e in os.listdir(snapshots_dir) if os.path.isdir(os.path.join(snapshots_dir, e))]
        if not entries:
            return None
        commit_hash = sorted(entries)[0]

    return os.path.join(hub_path, "snapshots", commit_hash, MODEL_FILENAME)


def make_volume() -> NetworkVolume:
    return NetworkVolume(name=VOLUME_NAME, size=100)


gpu_api = Endpoint(
    name=GPU_INFERENCE_ENDPOINT_NAME,
    # Requires >90GB VRAM: model weights are 78 GiB and compute buffers push
    # total usage past 80GB, causing OOM on A100 80GB and H100 80GB HBM3.
    # RTX Pro 6000 Blackwell (97GB) at $1.69/hr — best value for this model.
    # H200/B200 have more VRAM but cost 3-4x more with no benefit here.
    gpu=[
        GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_SERVER_EDITION,
    ],
    env={"PORT": "80"},
    dependencies=["httpx"],
    volume=make_volume(),
    template=PodTemplate(
        containerDiskInGb=64,
        # startScript appears not to run reliably in Flash LB workers.
        # Auto-warmup is handled by the _auto_start thread in nemotron.py instead.
        # startScript="bash /app/patches/install_llama_server.sh",
    ),
    flashboot=False,  # Flash LB force-kills workers at ~5min, preventing snapshot write.
    execution_timeout_ms=1800 * 1000,  # Per-slot timeout. Set high so multi-turn sessions don't hit LB cutoff mid-conversation.
    idle_timeout=1800,
    workers=(0, 2),
)


_slot_primed = False


@gpu_api.post("/v1/chat/completions")
async def chat_completions(
    messages: list,
    model: str = "nemotron",
    temperature: float = 1.0,
    top_p: float = 0.95,
    max_tokens: int = None,
    stream: bool = False,
    stop=None,
    response_format=None,
    tools=None,
    tool_choice=None,
):
    import asyncio
    import subprocess
    import httpx
    from fastapi import HTTPException
    from starlette.responses import StreamingResponse

    llama_bin = "/app/llama-server"
    model_path = "/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"
    server_url = "http://127.0.0.1:8081"

    # Check if server is already running
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{server_url}/health", timeout=2)
            server_ready = r.status_code == 200
        except Exception:
            server_ready = False

    if not server_ready:
        import os
        if not os.path.exists(llama_bin):
            raise RuntimeError(
                f"llama-server binary not found at {llama_bin}. "
                "The startScript may not have run. Install it via:\n"
                "  POST /admin/install\n"
                "or via SSH: bash /app/patches/install_llama_server.sh"
            )

        subprocess.Popen([
            llama_bin,
            "--model", model_path,
            "--host", "127.0.0.1",
            "--port", "8081",
            "--n-gpu-layers", "99",
            "--parallel", "1",
            "--ctx-size", "32768",
            "--flash-attn", "on",
        ])
        async with httpx.AsyncClient() as client:
            for _ in range(120):
                try:
                    r = await client.get(f"{server_url}/health", timeout=2)
                    if r.status_code == 200:
                        break
                except Exception:
                    pass
                await asyncio.sleep(5)
            else:
                raise RuntimeError("llama-server failed to become ready")

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "top_p": top_p,
        "stream": stream,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if stop is not None:
        payload["stop"] = stop
    if response_format is not None:
        payload["response_format"] = response_format
    if tools is not None:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice

    # stream=True: proxied via StreamingResponse (FastAPI LB supports SSE pass-through)
    if stream:
        # Inject stream_options so llama-server emits a final usage chunk
        # (choices:[], usage:{prompt_tokens, completion_tokens, total_tokens}).
        # The gateway layer uses this for token metering. Clients that don't
        # understand stream_options safely ignore it.
        payload["stream_options"] = {"include_usage": True}

        async def sse_generator():
            async with httpx.AsyncClient(timeout=1800) as client:
                async with client.stream(
                    "POST",
                    f"{server_url}/v1/chat/completions",
                    json=payload,
                ) as r:
                    if not r.is_success:
                        error_data = await r.aread()
                        yield f"data: {error_data.decode()}\n\n"
                        return
                    async for chunk in r.aiter_bytes():
                        if chunk:
                            yield chunk

        return StreamingResponse(
            sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async with httpx.AsyncClient(timeout=1800) as client:
        r = await client.post(f"{server_url}/v1/chat/completions", json=payload)
        if r.status_code == 503:
            raise HTTPException(
                status_code=503,
                detail="llama-server is still loading. Poll GET /health until status=ready before sending requests.",
            )
        if not r.is_success:
            raise HTTPException(
                status_code=r.status_code,
                detail=f"llama-server error: {r.text[:500]}",
            )
        return r.json()


@gpu_api.get("/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [{"id": "nemotron", "object": "model", "owned_by": "runpod-flash-nemotron"}],
    }


@gpu_api.get("/admin/debug")
async def admin_debug() -> dict:
    import os
    return {
        "patch_exists": os.path.exists("/app/patches/install_llama_server.sh"),
        "binary_exists": os.path.exists("/app/llama-server"),
        "volume_cache_exists": os.path.exists("/runpod-volume/cache/llama-server"),
        "local_model_exists": os.path.exists("/local-model/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"),
        "runpod_pod_id": os.environ.get("RUNPOD_POD_ID"),
        "env_keys": [k for k in os.environ if "RUNPOD" in k],
    }


@gpu_api.post("/admin/install")
async def admin_install(force: bool = False) -> dict:
    """Manually trigger llama-server installation. Pass force=true to skip cache."""
    import subprocess
    import os

    llama_bin = "/app/llama-server"
    volume_cache = "/runpod-volume/cache/llama-server"

    if force:
        for path in (llama_bin, volume_cache):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

    result = subprocess.run(
        ["bash", "/app/patches/install_llama_server.sh"],
        capture_output=True,
        text=True,
    )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-2000:],
        "binary_present": os.path.exists(llama_bin),
        "cache_present": os.path.exists(volume_cache),
    }


@gpu_api.post("/warmup")
async def warmup() -> dict:
    """Start llama-server in the background. Returns immediately. Poll /health until llama_server_ready=true."""
    import os
    import subprocess

    llama_bin = "/app/llama-server"
    model_path = "/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"

    if not os.path.exists(llama_bin):
        return {
            "status": "error",
            "message": f"Binary not found at {llama_bin}. Run POST /admin/install first.",
        }

    subprocess.Popen([
        llama_bin,
        "--model", model_path,
        "--host", "127.0.0.1",
        "--port", "8081",
        "--n-gpu-layers", "99",
        "--parallel", "1",
        "--ctx-size", "32768",
        "--flash-attn", "on",
    ])
    return {"status": "warming_up", "message": "Poll GET /health until llama_server_ready=true, then send requests."}


@gpu_api.post("/keepalive")
async def keepalive() -> dict:
    """Lightweight POST to keep the LB scaler from scaling to zero during warmup."""
    return {"alive": True}


@gpu_api.get("/health")
async def gpu_health() -> dict:
    import os
    import httpx

    model_path = "/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"
    llama_bin = "/app/llama-server"
    if not os.path.exists(model_path):
        return {"status": "missing_model", "model_path": model_path}
    if not os.path.exists(llama_bin):
        return {"status": "missing_binary", "binary": llama_bin}

    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://127.0.0.1:8081/health", timeout=2)
            # llama-server returns 200 {"status":"ok"} when ready,
            # 503 {"status":"loading"} while tensors are loading into VRAM.
            body = r.json()
            llama_status = body.get("status", "")
            llama_ready = llama_status == "ok"
            llama_loading = llama_status == "loading"
    except Exception:
        llama_ready = False
        llama_loading = False

    if llama_ready:
        # Prime slot 0 to absorb NemotronH hybrid-attention first-request KV cache init (llama.cpp PR #13194)
        global _slot_primed
        if not _slot_primed:
            try:
                async with httpx.AsyncClient(timeout=30.0) as prime_client:
                    await prime_client.post(
                        "http://127.0.0.1:8081/v1/chat/completions",
                        json={
                            "model": "nemotron",
                            "messages": [{"role": "user", "content": "hi"}],
                            "max_tokens": 1,
                            "temperature": 0,
                        },
                    )
            except Exception as e:
                import logging
                logging.getLogger(__name__).warning("Slot priming request failed (non-fatal): %s", e)
            finally:
                _slot_primed = True
        return {"status": "ready"}
    if llama_loading:
        return {"status": "warming_up", "detail": "loading tensors into VRAM"}

    import subprocess
    llama_running = bool(subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True).returncode == 0)
    return {"status": "warming_up" if llama_running else "cold"}


def make_seed_runner(hf_token: str):
    temp_seed_name = f"nemotron-seed-{int(time.time())}"

    async def seed_model(payload: dict | None = None) -> dict:
        import os
        import subprocess
        import shutil
        from huggingface_hub import snapshot_download

        model_path = "/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"
        model_dir = "/runpod-volume/models"
        model_repo_id = "unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF"
        allow_patterns = ["*UD-Q4_K_XL*"]
        volume_cache = "/runpod-volume/cache/llama-server"
        _clean_binary = (payload or {}).get("clean_binary", False)
        _clean_model = (payload or {}).get("clean_model", False)

        if _clean_binary and os.path.exists(volume_cache):
            os.remove(volume_cache)

        if _clean_model and os.path.isdir(model_dir):
            shutil.rmtree(model_dir)

        os.makedirs(model_dir, exist_ok=True)

        # Build and cache llama-server binary to volume so inference workers
        # never need to compile on cold start. Idempotent: skips if already cached.
        binary_was_cached = os.path.exists(volume_cache)
        if not binary_was_cached:
            subprocess.run(
                ["bash", "/app/patches/install_llama_server.sh"],
                check=True,
            )

        model_was_present = os.path.exists(model_path)
        if not model_was_present:
            snapshot_download(
                repo_id=model_repo_id,
                allow_patterns=allow_patterns,
                local_dir=model_dir,
                token=os.environ["HF_TOKEN"],
            )

        return {
            "binary": "rebuilt" if not binary_was_cached else "cached",
            "model": "already_present" if model_was_present else "downloaded",
            "model_path": model_path,
        }

    return Endpoint(
        name=temp_seed_name,
        # Must be the same GPU type as the inference workers — same GPU = same CUDA driver
        # stack, so the compiled llama-server binary runs without compatibility issues.
        # install_llama_server.sh builds for sm_90;100;120 (H200/B200/RTX Pro 6000 Blackwell).
        # If you change the inference GPU, change this to match and re-run seed --clean-binary.
        gpu=[GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_SERVER_EDITION],
        dependencies=["huggingface_hub>=0.32.0"],
        volume=make_volume(),
        env={"HF_TOKEN": hf_token},
        execution_timeout_ms=6 * 60 * 60 * 1000,
        idle_timeout=60,
        workers=(0, 1),
    )(seed_model)


async def seed_model_once(clean_binary: bool = False, clean_model: bool = False) -> dict:
    # Load .env if present so `python nemotron.py seed` works without env prefix.
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        raise SystemExit(
            "HF_TOKEN is required. Set it in .env or prefix: HF_TOKEN=hf_... python nemotron.py seed"
        )

    print(f"Seeding volume '{VOLUME_NAME}'")
    if clean_binary:
        print("  --clean-binary: cached llama-server binary will be removed and rebuilt")
    if clean_model:
        print("  --clean-model:  model files will be removed and re-downloaded (~84 GB)")

    seed_runner = make_seed_runner(hf_token)
    result = await seed_runner({"clean_binary": clean_binary, "clean_model": clean_model})

    print()
    print(f"Binary: {result['binary']}")
    print(f"Model:  {result['model']}  ({result['model_path']})")
    print()
    print("Next step: flash deploy")

    return result


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    if not args:
        print(__doc__.strip())
        return 0

    if args and args[0] == "seed":
        flags = set(args[1:])
        unknown = flags - {"--clean-binary", "--clean-model"}
        if unknown:
            print(f"Unknown flag(s): {' '.join(unknown)}")
            print("Usage: HF_TOKEN=hf_... python nemotron.py seed [--clean-binary] [--clean-model]")
            return 1
        asyncio.run(seed_model_once(
            clean_binary="--clean-binary" in flags,
            clean_model="--clean-model" in flags,
        ))
        return 0

    print("Unknown command.")
    print("Usage:")
    print("  HF_TOKEN=hf_... python nemotron.py seed [--clean-binary] [--clean-model]")
    print("  flash deploy")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
