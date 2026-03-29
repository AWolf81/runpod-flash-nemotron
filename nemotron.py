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
from runpod_flash.core.resources.serverless import ServerlessResource
from runpod_flash.core.resources.template import PodTemplate


def _auto_start():
    """Run install script and start llama-server in background at app startup."""
    subprocess.Popen(["bash", "/app/patches/install_llama_server.sh"])


if os.path.exists("/app/patches/install_llama_server.sh"):
    threading.Thread(target=_auto_start, daemon=True).start()


def _patch_flash_template_update_payload() -> None:
    """Ensure deploy updates keep template ports/startScript fields."""
    if getattr(ServerlessResource, "_nemotron_template_patch_applied", False):
        return

    original = ServerlessResource._build_template_update_payload

    def patched(template: PodTemplate, template_id: str) -> dict:
        payload = original(template, template_id)
        try:
            template_data = template.model_dump(exclude_none=True, mode="json")
            if "ports" in template_data:
                payload["ports"] = template_data["ports"]
            if "startScript" in template_data:
                payload["startScript"] = template_data["startScript"]
        except Exception:
            pass
        return payload

    ServerlessResource._build_template_update_payload = staticmethod(patched)
    ServerlessResource._nemotron_template_patch_applied = True


_patch_flash_template_update_payload()


def _patch_flash_manifest_template_ports() -> None:
    """Ensure flash build manifest keeps template ports from Endpoint config."""
    try:
        from runpod_flash.cli.commands.build_utils.manifest import ManifestBuilder
    except Exception:
        return

    if getattr(ManifestBuilder, "_nemotron_manifest_ports_patch_applied", False):
        return

    original = ManifestBuilder._extract_config_properties

    def patched(config: dict, resource_config) -> None:
        original(config, resource_config)
        try:
            template_obj = getattr(resource_config, "template", None)
            if not template_obj:
                return
            ports = getattr(template_obj, "ports", None)
            if ports:
                config.setdefault("template", {})
                config["template"]["ports"] = ports
        except Exception:
            pass

    ManifestBuilder._extract_config_properties = staticmethod(patched)
    ManifestBuilder._nemotron_manifest_ports_patch_applied = True


_patch_flash_manifest_template_ports()


def _patch_flash_resource_provisioning_template() -> None:
    """Ensure deploy provisioning uses manifest template fields (including ports)."""
    try:
        import runpod_flash.runtime.resource_provisioner as provisioner
    except Exception:
        return

    if getattr(provisioner, "_nemotron_template_provision_patch_applied", False):
        return

    original = provisioner.create_resource_from_manifest

    def patched(resource_name, resource_data, *args, **kwargs):
        resource = original(resource_name, resource_data, *args, **kwargs)
        try:
            template_data = (resource_data or {}).get("template")
            if isinstance(template_data, dict) and template_data:
                template_payload = dict(template_data)
                # saveTemplate requires imageName; inherit from resource when missing.
                if not template_payload.get("imageName"):
                    template_payload["imageName"] = getattr(resource, "imageName", "")
                if "name" not in template_payload:
                    template_payload["name"] = ""
                if not template_payload.get("env"):
                    env_dict = dict(getattr(resource, "env", {}) or {})
                    # Ensure port env is always present on LB templates.
                    env_dict.setdefault("PORT", "80")
                    env_dict.setdefault("PORT_HEALTH", env_dict["PORT"])
                    template_payload["env"] = [
                        {"key": str(k), "value": str(v)} for k, v in env_dict.items()
                    ]
                # Preserve explicit template config from manifest; needed for ports.
                resource.template = PodTemplate(**template_payload)
        except Exception:
            pass
        return resource

    provisioner.create_resource_from_manifest = patched
    # deployment.py imports the function symbol directly; patch that alias too.
    try:
        import runpod_flash.cli.utils.deployment as deploy_utils

        deploy_utils.create_resource_from_manifest = patched
    except Exception:
        pass

    provisioner._nemotron_template_provision_patch_applied = True


_patch_flash_resource_provisioning_template()

def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    return value or default


def _env_csv(name: str, default: str) -> list[str]:
    raw = _env_str(name, default)
    return [part.strip() for part in raw.split(",") if part.strip()]


# Defaults target IQ4_XS to match the currently deployed benchmark model.
VOLUME_NAME = _env_str("NEMOTRON_VOLUME_NAME", "nemotron-iq4xs-cache")
MODEL_DIR = _env_str("NEMOTRON_MODEL_DIR", "/runpod-volume/models/UD-IQ4_XS")
MODEL_FILENAME = _env_str(
    "NEMOTRON_MODEL_FILENAME",
    "NVIDIA-Nemotron-3-Super-120B-A12B-UD-IQ4_XS-00001-of-00003.gguf",
)
MODEL_PATH = f"{MODEL_DIR}/{MODEL_FILENAME}"
GPU_INFERENCE_ENDPOINT_NAME = _env_str("NEMOTRON_ENDPOINT_NAME", "nemotron-iq4xs")
OPENAI_MODEL_ID = _env_str("NEMOTRON_OPENAI_MODEL_ID", "nemotron-super-120b-iq4")
MODEL_REPO_ID = _env_str("NEMOTRON_HF_REPO_ID", "unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF")
MODEL_ALLOW_PATTERNS = _env_csv("NEMOTRON_HF_ALLOW_PATTERNS", "*UD-IQ4_XS*")

# ── Cached Model Configuration ────────────────────────────────────────────────
# RunPod cached models mounts the HF repo at:
#   /runpod-volume/huggingface-cache/hub/models--org--repo/snapshots/{hash}/
# Set CACHED_REPO_ID to your private single-quant repo (org/repo-name).
# Leave as empty string to fall back to the network volume path (MODEL_PATH).
CACHED_REPO_ID = _env_str("NEMOTRON_CACHED_REPO_ID", "")  # e.g. "your-org/nemotron-q4-xl"
CACHED_CACHE_BASE = _env_str("NEMOTRON_CACHED_CACHE_BASE", "/runpod-volume/huggingface-cache/hub")


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


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except Exception:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _llama_runtime_config() -> dict[str, int | str]:
    return {
        "n_gpu_layers": _env_int("LLAMA_N_GPU_LAYERS", 99, minimum=1),
        "parallel": _env_int("LLAMA_PARALLEL", 1, minimum=1, maximum=8),
        "ctx_size": _env_int("LLAMA_CTX_SIZE", 32768, minimum=4096, maximum=131072),
        "flash_attn": os.environ.get("LLAMA_FLASH_ATTN", "on"),
    }


gpu_api = Endpoint(
    name=GPU_INFERENCE_ENDPOINT_NAME,
    # Requires >90GB VRAM: model weights are 78 GiB and compute buffers push
    # total usage past 80GB, causing OOM on A100 80GB and H100 80GB HBM3.
    # RTX Pro 6000 Blackwell (97GB) at $1.69/hr — best value for this model.
    # H200/B200 have more VRAM but cost 3-4x more with no benefit here.
    gpu=[
        # All three Blackwell RTX PRO 6000 variants have 96GB VRAM at the same
        # price ($1.69/hr). List all so RunPod picks whichever has availability.
        GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_SERVER_EDITION,
        GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_WORKSTATION_EDITION,
        GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_MAX_Q_WORKSTATION_EDITION,
    ],
    env={
        "PORT": "80",
        "PORT_HEALTH": "80",
        "LLAMA_PARALLEL": _env_str("LLAMA_PARALLEL", "1"),
        "LLAMA_CTX_SIZE": _env_str("LLAMA_CTX_SIZE", "32768"),
        "LLAMA_N_GPU_LAYERS": _env_str("LLAMA_N_GPU_LAYERS", "99"),
        "LLAMA_FLASH_ATTN": _env_str("LLAMA_FLASH_ATTN", "on"),
    },
    dependencies=["httpx"],
    volume=make_volume(),
    template=PodTemplate(
        containerDiskInGb=64,
        ports="80/http",
        # startScript appears not to run reliably in Flash LB workers.
        # Auto-warmup is handled by the _auto_start thread in nemotron.py instead.
        # startScript="bash /app/patches/install_llama_server.sh",
    ),
    flashboot=False,  # Flash LB force-kills workers at ~5min, preventing snapshot write.
    execution_timeout_ms=1800 * 1000,  # Per-slot timeout. Set high so multi-turn sessions don't hit LB cutoff mid-conversation.
    idle_timeout=1800,
    workers=(0, 2),
)


_slot_primed = False      # True once priming has been triggered
_slot_prime_done = False  # True once priming request completed (VRAM fully warm)
_llama_start_lock = threading.Lock()


def _start_llama_server_once() -> str:
    """Start llama-server only if it is not already running/loading."""
    import httpx

    llama_bin = "/app/llama-server"
    model_path = MODEL_PATH
    server_url = "http://127.0.0.1:8081/health"

    with _llama_start_lock:
        try:
            with httpx.Client(timeout=1.5) as client:
                r = client.get(server_url)
            if r.status_code in (200, 503):
                return "already_running"
        except Exception:
            pass

        # Guard against duplicate process launch if health probe races.
        if subprocess.run(["pgrep", "-x", "llama-server"], capture_output=True).returncode == 0:
            return "already_running"

        cfg = _llama_runtime_config()

        subprocess.Popen([
            llama_bin,
            "--model", model_path,
            "--host", "127.0.0.1",
            "--port", "8081",
            "--n-gpu-layers", str(cfg["n_gpu_layers"]),
            "--parallel", str(cfg["parallel"]),
            "--ctx-size", str(cfg["ctx_size"]),
            "--flash-attn", str(cfg["flash_attn"]),
        ])
        return "started"


async def _prime_slot():
    """Fire a single 1-token request to absorb NemotronH first-request KV cache init.
    Runs in the background so it never blocks health checks.
    Sets _slot_prime_done when complete so /health can report fully warm."""
    global _slot_prime_done
    import httpx
    import logging
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            await client.post(
                "http://127.0.0.1:8081/v1/chat/completions",
                json={
                    "model": OPENAI_MODEL_ID,
                    "messages": [{"role": "user", "content": "hi"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
            )
        _slot_prime_done = True
    except Exception as e:
        logging.getLogger(__name__).warning("Slot priming failed (non-fatal): %s", e)
        _slot_prime_done = True  # mark done anyway so health doesn't stay stuck


@gpu_api.post("/v1/chat/completions")
async def chat_completions(
    messages: list,
    model: str = OPENAI_MODEL_ID,
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
    model_path = MODEL_PATH
    server_url = "http://127.0.0.1:8081"

    # Check if server is already running
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{server_url}/health", timeout=2)
            server_ready = r.status_code == 200
        except Exception:
            server_ready = False

    if not server_ready:
        if not os.path.exists(llama_bin):
            raise RuntimeError(
                f"llama-server binary not found at {llama_bin}. "
                "The startScript may not have run. Install it via:\n"
                "  POST /admin/install\n"
                "or via SSH: bash /app/patches/install_llama_server.sh"
            )

        _start_llama_server_once()
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
        "data": [{"id": OPENAI_MODEL_ID, "object": "model", "owned_by": "runpod-flash-nemotron"}],
    }


@gpu_api.get("/admin/debug")
async def admin_debug() -> dict:
    import os
    return {
        "patch_exists": os.path.exists("/app/patches/install_llama_server.sh"),
        "binary_exists": os.path.exists("/app/llama-server"),
        "volume_cache_exists": os.path.exists("/runpod-volume/cache/llama-server"),
        "local_model_exists": os.path.exists(f"/local-model/{MODEL_FILENAME}"),
        "runpod_pod_id": os.environ.get("RUNPOD_POD_ID"),
        "env_keys": [k for k in os.environ if "RUNPOD" in k],
        "llama_runtime_config": _llama_runtime_config(),
        "model_path": MODEL_PATH,
        "model_filename": MODEL_FILENAME,
        "openai_model_id": OPENAI_MODEL_ID,
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
    model_path = MODEL_PATH

    if not os.path.exists(llama_bin):
        return {
            "status": "error",
            "message": f"Binary not found at {llama_bin}. Run POST /admin/install first.",
        }

    launch = _start_llama_server_once()
    return {
        "status": "warming_up",
        "launch": launch,
        "message": "Poll GET /health until llama_server_ready=true, then send requests.",
    }


@gpu_api.post("/keepalive")
async def keepalive() -> dict:
    """Lightweight POST to keep the LB scaler from scaling to zero during warmup."""
    return {"alive": True}


@gpu_api.get("/health")
async def gpu_health() -> dict:
    import os
    import httpx

    model_path = MODEL_PATH
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
        # Prime slot 0 in the background to absorb NemotronH hybrid-attention
        # first-request KV cache init (llama.cpp PR #13194).
        # Must NOT block here — health check must return fast or the Flash LB
        # times out and warmup.sh never sees "ready".
        global _slot_primed, _slot_prime_done
        if not _slot_primed:
            _slot_primed = True  # set immediately so concurrent health polls don't also trigger priming
            import asyncio
            asyncio.ensure_future(_prime_slot())
        if not _slot_prime_done:
            return {"status": "priming", "detail": "VRAM loading — slot prime in progress"}
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

        model_dir = MODEL_DIR
        model_path = MODEL_PATH
        model_repo_id = MODEL_REPO_ID
        allow_patterns = MODEL_ALLOW_PATTERNS
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
        #
        # NOTE: the seed function runs as a serialized closure — /app/patches/ does not
        # exist on the seed worker. Build steps are inlined here instead of calling the
        # shell script. Keep in sync with patches/install_llama_server.sh.
        binary_was_cached = os.path.exists(volume_cache)
        if not binary_was_cached:
            import sys
            build_dir = "/tmp/llama-cpp-build"
            install_dir = "/app"
            binary = f"{install_dir}/llama-server"

            # system cmake 3.22 (Ubuntu 22.04) is too old — need >=3.28
            subprocess.run([sys.executable, "-m", "pip", "install", "cmake>=3.28"], check=True)

            subprocess.run(["git", "clone", "--depth", "1",
                            "https://github.com/ggml-org/llama.cpp.git", build_dir], check=True)

            # sm_90=H200, sm_100=B200, sm_120=RTX Pro 6000 Blackwell
            subprocess.run(["cmake", build_dir, "-B", f"{build_dir}/build",
                            "-DBUILD_SHARED_LIBS=OFF", "-DGGML_CUDA=ON",
                            "-DCMAKE_CUDA_ARCHITECTURES=90;100;120"], check=True)

            subprocess.run(["cmake", "--build", f"{build_dir}/build",
                            "--config", "Release", f"-j{os.cpu_count() or 4}",
                            "--target", "llama-server"], check=True)

            os.makedirs(install_dir, exist_ok=True)
            shutil.copy(f"{build_dir}/build/bin/llama-server", binary)
            os.chmod(binary, 0o755)

            os.makedirs(os.path.dirname(volume_cache), exist_ok=True)
            shutil.copy(binary, volume_cache)
            os.chmod(volume_cache, 0o755)

            shutil.rmtree(build_dir, ignore_errors=True)

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
        # Must be same GPU family as inference workers — same CUDA arch = binary compatibility.
        # All three Blackwell variants share sm_120 arch, so the binary is compatible across them.
        # If you change the inference GPU family, update this list and re-run seed --clean-binary.
        gpu=[
            GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_SERVER_EDITION,
            GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_WORKSTATION_EDITION,
            GpuType.NVIDIA_RTX_PRO_6000_BLACKWELL_MAX_Q_WORKSTATION_EDITION,
        ],
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

    if args and args[0] == "gpu-types":
        for gpu in gpu_api._gpu:
            print(gpu.value)
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
