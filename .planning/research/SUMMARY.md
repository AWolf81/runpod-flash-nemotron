# Project Research Summary

**Project:** runpod-flash-nemotron
**Domain:** Serverless AI inference deployment tool (developer tooling / MLOps)
**Researched:** 2026-03-20
**Confidence:** HIGH

## Executive Summary

runpod-flash-nemotron is a developer tool in a niche but well-understood domain: one-command serverless LLM deployment for a specific model/hardware combination. The architecture is straightforward — a single Python file using the RunPod Flash SDK declares an endpoint, and a pre-built llama.cpp Docker image handles inference. No custom server code, no complex CI/CD. The main value is the opinionated configuration that makes it all work within a $20/month budget.

The critical technical insight driving this project is that Nemotron-3-Super-120B's 83.8 GB UD-Q4_K_XL weights exceed the A100's 80 GB VRAM, but the MoE architecture allows routing expert weights to CPU RAM via `--override-tensor "exps=CPU"`, making single-A100 deployment feasible at ~14 tokens/second. This community-discovered configuration is the core of the project's value — it's non-obvious and not documented by NVIDIA.

The primary risk is not technical complexity but developer experience: the model download prerequisite (pre-populating the network volume before first deploy) must be clearly communicated or users will hit a cold-start timeout loop and assume the project is broken. The README and quickstart structure are as important as the deployment script itself.

## Key Findings

### Recommended Stack

The stack is minimal and purpose-built. RunPod Flash SDK (`>=1.8.1`) handles all serverless orchestration via Python objects (`Endpoint`, `GpuGroup.AMPERE_80`, `NetworkVolume`). The official llama.cpp Docker image (`ghcr.io/ggml-org/llama.cpp:server-cuda`, build `>=b4900`) provides the inference server. No custom image is needed.

**Core technologies:**
- `runpod-flash>=1.8.1`: Serverless GPU orchestration — `GpuGroup.AMPERE_80` targets A100 80GB; handles worker scaling, cold-start, HTTP proxy
- `ghcr.io/ggml-org/llama.cpp:server-cuda` (build ≥ b4900): OpenAI-compatible inference server — pre-built with CUDA 12.4.0; supports GGUF natively
- `huggingface_hub>=0.32.0`: Model download — `snapshot_download` with `allow_patterns="UD-Q4_K_XL/*"` downloads all 3 split files; uses fast `hf_xet` chunked downloads
- Python 3.10–3.12: Runtime — 3.13+ not supported by runpod-flash

### Expected Features

The project's features are nearly fully defined by the PROJECT.md requirements. Research confirmed all are feasible and well-understood:

**Must have (table stakes for OSS developer tool):**
- Single-file deployment script (`nemotron.py`) — users expect one command
- OpenAI-compatible endpoint — mandatory for Claude Code / OpenCode / Mistral Vibe
- Integration config snippets for all three target tools — each has different config file format
- Cost breakdown with $20/month math — developers won't deploy without understanding cost
- Scale-to-zero documentation — core serverless value proposition

**Should have (differentiators):**
- Network Volume model caching — eliminates 83.8 GB re-download; required for scale-to-zero to be practical
- `--override-tensor "exps=CPU"` documented with explanation — non-obvious; this is expert knowledge
- FlashBoot (`flashboot=True`) — snapshot cold starts; easy win
- `idle_timeout` tuning guide — reduces billing for short sessions
- Explicit `execution_timeout=1800` with rationale — prevents 120B response truncation

**Anti-features to avoid:**
- vLLM/FP8 path — exceeds budget and hardware requirements
- Multi-user deployment, web UI, other models — scope creep per PROJECT.md

### Architecture Approach

Two-tier architecture: `nemotron.py` (local, declarative config) + RunPod worker running llama-server (remote, handles all inference). The RunPod proxy routes HTTPS traffic from clients directly to llama-server on port 8080. No custom handler code needed.

**Major components:**
1. `nemotron.py` — declares `Endpoint` with `GpuGroup.AMPERE_80`, `NetworkVolume(size=100)`, `flashboot=True`, `execution_timeout=1800`
2. `download_model.py` — one-time network volume seeding via `snapshot_download`
3. llama-server — runs inside the official Docker image; loads from `/runpod-volume/models/nemotron/`; exposes `/v1/chat/completions` on port 8080
4. README — quickstart, three integration guides, cost breakdown, known limitations

### Critical Pitfalls

1. **UD-Q4_K_XL fails on old llama.cpp** — must use build ≥ b4900 (PR #20411); pin the Docker image tag
2. **Cold start timeout loop** — 83.8 GB download exceeds RunPod's ~7-min worker init; network volume must be pre-populated before first deploy; this is the #1 developer experience failure mode
3. **VRAM OOM at context > 8192** — `--override-tensor "exps=CPU"` is mandatory, not optional; never omit `-c 8192` cap
4. **HF_TOKEN exposure** — must use `os.environ["HF_TOKEN"]` + RunPod Secrets, never hardcode
5. **Execution timeout** — default 600s insufficient for 120B model; set `execution_timeout=1800`
6. **Billing starts at worker init** — cold start overhead ~$0.14 per start; document `idle_timeout` tuning

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Core Deployment Script
**Rationale:** This is the entire product for most users — get it working and correct first.
**Delivers:** `nemotron.py` + `download_model.py` that deploy successfully
**Addresses:** Single-file deployment, OpenAI-compatible endpoint, network volume caching, FlashBoot, all critical llama-server flags
**Avoids:** Cold start loop (network volume + download script), VRAM OOM (correct flags), execution timeout (1800s), HF_TOKEN exposure (os.environ)

### Phase 2: Integration Guides
**Rationale:** The endpoint is useless without knowing how to point each tool at it.
**Delivers:** Tested config snippets for Claude Code, OpenCode, Mistral Vibe
**Uses:** RunPod proxy URL format `https://api.runpod.ai/v2/{id}/openai/v1`
**Implements:** Three separate config file formats; client timeout documentation

### Phase 3: README + Cost Documentation
**Rationale:** OSS success depends on the README. The quickstart must work in <5 minutes with no prior RunPod experience.
**Delivers:** Complete README with quickstart, prerequisites, cost table, known limitations, EU-RO-1 note
**Avoids:** User abandonment due to undocumented cold start; billing surprises; community GGUF caveat documented

### Phase Ordering Rationale

- Phase 1 before Phase 2: Can't test integrations without a working deployment
- Phase 3 is continuous but finalized last: README evolves as Phase 1/2 decisions solidify
- Each phase is small enough to execute in a single context window — no phase needs splitting

### Research Flags

Phases with standard patterns (skip research-phase):
- **Phase 1:** Core APIs are well-documented; runpod-flash SDK and llama-server flags are fully researched
- **Phase 2:** Integration config formats for all three tools are documented and stable
- **Phase 3:** README writing; no research needed

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Verified against official RunPod Flash docs, llama.cpp docs, HuggingFace model page |
| Features | HIGH | All requirements from PROJECT.md confirmed feasible; no unknowns |
| Architecture | HIGH | Two known-good reference implementations found (runpod/flash-examples, stanchino/runpod-llama.cpp) |
| Pitfalls | HIGH | UD-Q4_K_XL bug confirmed from HuggingFace model discussion; cold start math verified; billing model documented |

**Overall confidence:** HIGH

### Gaps to Address

- **Actual token throughput on A100 with CPU expert offloading:** ~14 t/s is community-reported; actual production throughput should be measured in Phase 1 verification
- **FlashBoot cold start time with network volume:** Estimated 2–3 min; measure in Phase 1 to document accurately
- **OpenCode exact config schema:** May have changed recently; verify against current OpenCode repo during Phase 2

## Sources

### Primary (HIGH confidence)
- `github.com/runpod/flash` — RunPod Flash SDK API, GpuGroup, NetworkVolume, Endpoint params
- `docs.runpod.io/flash/` — Custom Docker image patterns, execution_timeout, idle_timeout
- `github.com/ggml-org/llama.cpp` — Server CLI flags, Docker image registry
- `huggingface.co/unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF` — Model sizes, quant options, PR #20411 bug fix
- `developer.nvidia.com/blog/introducing-nemotron-3-super` — Architecture facts, recommended sampling params

### Secondary (MEDIUM confidence)
- `huggingface.co/blog/Doctor-Shotgun/llamacpp-moe-offload-guide` — `--override-tensor exps=CPU` pattern
- `github.com/ggml-org/llama.cpp/discussions/15396` — 120B on 80GB flag recommendations
- `carteakey.dev/blog/optimizing-gpt-oss-120b-local-inference/` — `--no-mmap`, `GGML_CUDA_GRAPH_OPT=1`
- `github.com/stanchino/runpod-llama.cpp` — Reference implementation of RunPod + llama.cpp deployment

---
*Research completed: 2026-03-20*
*Ready for roadmap: yes*
