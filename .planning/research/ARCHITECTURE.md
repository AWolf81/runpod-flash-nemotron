# Architecture Research

**Domain:** RunPod Flash LLM deployment hardening (v0.2.0)
**Researched:** 2026-03-22
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Claude Code │  │  OpenCode    │  │ Mistral Vibe │       │
│  │ (via LiteLLM)│  │ (direct OAI) │  │ (direct OAI) │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
└─────────┼─────────────────┼─────────────────┼───────────────┘
          │                 │                 │
          ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│               RunPod Flash Load Balancer                     │
│  (HTTP proxy — passes SSE through unchanged)                 │
│  X-Accel-Buffering: no ensures no nginx buffering            │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   FastAPI Worker (nemotron.py)               │
│                                                              │
│  POST /v1/chat/completions                                   │
│      └─> StreamingResponse (media_type="text/event-stream")  │
│              └─> httpx.AsyncClient.aiter_bytes()             │
│                                                              │
│  GET /health                                                 │
│      └─> slot priming (_slot_primed flag)                    │
│                                                              │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│               llama-server (port 8080)                       │
│                                                              │
│  --model /runpod-volume/models/nemotron.gguf                 │
│  --parallel N   (KV slots — currently 1)                     │
│  --ctx-size X   (total KV budget shared across all slots)    │
│  --port 8080                                                 │
│                                                              │
│  /v1/chat/completions  →  SSE token stream                   │
│  /v1/models            →  model list                         │
└─────────────────────────────┬───────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│          RunPod Network Volume (persistent)                  │
│  /runpod-volume/llama-server/  — compiled binary (seed)      │
│  /runpod-volume/models/        — GGUF weights (~79GB)        │
└─────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Notes |
|-----------|----------------|-------|
| RunPod Flash LB | Route requests to workers, pass SSE through | HTTP proxy; `X-Accel-Buffering: no` prevents nginx buffering |
| FastAPI worker | Translate RunPod Flash format → llama-server, stream response | `StreamingResponse` + `httpx.aiter_bytes()` |
| llama-server | GGUF inference, KV cache management, OpenAI API | `--parallel` controls concurrency; `--ctx-size` is total KV budget |
| Network volume | Binary caching (llama-server binary) + model weights | Seed worker builds binary; inference workers restore from cache |
| _slot_primed flag | Absorb NemotronH KV cache init penalty on health check | Prevents first real request from timing out |

---

## Parallel Slots: Memory Math

### Model Architecture (from Nemotron-3-Super config.json)

- 88 total layers: **40 Mamba layers** (no KV cache) + **48 attention layers** (KV cache)
- `num_key_value_heads = 2` — extremely aggressive Multi-Query Attention (MQA)
- `head_dim = 128`
- KV dtype: FP16 (2 bytes)

### KV Cache Bytes Per Token

```
bytes_per_token = num_kv_heads × head_dim × 2 (K+V) × dtype_bytes × attn_layers
               = 2 × 128 × 2 × 2 × 48
               = 49,152 bytes/token  (~48 KB/token)
```

This is ~10–30× smaller than a comparable dense transformer (e.g. Llama 405B), because Mamba
layers use fixed ~200MB recurrent state that does NOT scale with context or slot count.

### VRAM Budget for KV Cache

| Component | VRAM |
|-----------|------|
| Model weights (UD-Q4_K_XL) | ~79.0 GiB |
| Compute buffers | ~2.5 GiB |
| **Available for KV cache** | **~14.5 GiB** |

### --parallel + --ctx-size Scenarios (RTX Pro 6000 Blackwell 96GB)

| `--parallel` | `--ctx-size` (total) | KV per slot | KV total GiB | VRAM remaining | Feasible? |
|---|---|---|---|---|---|
| 1 | 32768 (current) | 32768 | 1.50 GiB | 13.0 GiB | ✓ Current |
| 2 | 65536 (recommended) | 32768 | 6.00 GiB | 8.5 GiB | ✓ Recommended |
| 2 | 32768 | 16384 | 3.00 GiB | 11.5 GiB | ✓ Half context |
| 4 | 32768 | 8192 | 6.00 GiB | 8.5 GiB | ✓ Quarter context |
| 8 | 32768 | 4096 | 12.00 GiB | 2.5 GiB | ⚠ Tight |
| 9 | 32768 | 3641 | 13.5 GiB | ~1.0 GiB | ✗ OOM risk |

**Key insight:** `--ctx-size` is the TOTAL KV budget shared across all slots. To maintain 32K
context per slot with `--parallel 2`, set `--ctx-size 65536`. The trade-off: more concurrency =
less context per slot OR more total VRAM.

**Recommended for v0.2.0 investigation:** Start with `--parallel 2 --ctx-size 65536` (doubles
concurrency, maintains 32K context per slot, uses ~6 GiB KV — well within 14.5 GiB headroom).

---

## SSE Streaming Architecture

### Request Flow (Streaming)

```
Client
  │  POST /v1/chat/completions {"stream": true}
  ▼
RunPod Flash LB
  │  (HTTP proxy, passes bytes through — X-Accel-Buffering: no)
  ▼
FastAPI StreamingResponse
  │  media_type="text/event-stream"
  │  headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"}
  │  async generator
  ▼
httpx.AsyncClient (async context manager)
  │  stream=True → response.aiter_bytes()
  ▼
llama-server /v1/chat/completions
  │  Yields SSE chunks:
  │    data: {"id":"...","choices":[{"delta":{"content":"Hello"}}]}\n\n
  │    data: {"id":"...","choices":[{"delta":{"content":" world"}}]}\n\n
  │    data: [DONE]\n\n
  ▼
(bytes pass back up the chain unchanged)
```

### Critical Headers for SSE Pass-Through

```python
headers = {
    "X-Accel-Buffering": "no",   # Prevents nginx from buffering
    "Cache-Control": "no-cache", # Prevents proxy caching
    "Connection": "keep-alive",  # Maintains long-lived connection
}
```

### State Management: _slot_primed Flag

```
/health request
    ↓
_slot_primed == False?
    ↓ Yes
Send warmup request to llama-server (forces KV cache init)
    ↓
_slot_primed = True
    ↓
Return {"status": "ok"}

Subsequent /health requests → immediate return (flag is True)
```

This pattern is essential for NemotronH's hybrid attention architecture — the KV cache for
attention layers must be initialized before the first real inference request to prevent timeouts.

---

## Data Flow: Cold Start Sequence

```
flash deploy
    ↓
Seed worker starts (workers=(0,1) scale-to-zero default)
    ↓
nemotron.py seed:
  1. Build llama-server from source (~30-90 min first time)
  2. Cache binary to /runpod-volume/llama-server/
  3. Model already downloaded to /runpod-volume/models/
    ↓
Inference worker receives first request (8m45s cold start):
  1. Restore llama-server binary from volume (~few seconds)
  2. Load GGUF into VRAM (~8 min)
  3. Start llama-server process
  4. /health triggers slot priming
  5. Ready for requests
```

---

## Anti-Patterns

### Anti-Pattern 1: Synchronous Streaming Proxy

**What people do:** Use `requests` library or synchronous `httpx` to stream from llama-server.
**Why it's wrong:** Blocks the FastAPI event loop, serializes requests, defeats async concurrency.
**Do this instead:** `httpx.AsyncClient` with `async with client.stream(...)` and `aiter_bytes()`.

### Anti-Pattern 2: Wrong --ctx-size for --parallel

**What people do:** Set `--parallel 2` without increasing `--ctx-size`.
**Why it's wrong:** Context is split across slots — with `--parallel 2 --ctx-size 32768`, each
slot gets only 16K context, halving effective context window without user awareness.
**Do this instead:** Set `--ctx-size = parallel × desired_context_per_slot`.

### Anti-Pattern 3: Testing Streaming via Buffering Client

**What people do:** Test SSE with `requests.get()` or `curl` without `-N` flag.
**Why it's wrong:** Client buffers the response, making it appear non-streaming. Can mask issues
where streaming works client-side but not end-to-end.
**Do this instead:** `curl -N` (no buffering) or `httpx` async client with streaming enabled.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| RunPod Flash LB | HTTP proxy | Passes SSE through; `X-Accel-Buffering: no` is required |
| HuggingFace | wget/curl model download | `HF_TOKEN` required; unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF |
| LiteLLM gateway | Anthropic → OpenAI format translation | Required for Claude Code (expects Anthropic-format traffic) |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| FastAPI ↔ llama-server | HTTP (localhost:8080) | Async httpx streaming |
| Seed ↔ Inference workers | Network volume | Binary + model shared via persistent volume |
| RunPod Flash ↔ FastAPI | HTTP | Flash calls worker handler function |

---

## Sources

- llama.cpp GitHub — `--parallel` and `--ctx-size` documentation (HIGH confidence)
- Nemotron-3-Super model config.json on HuggingFace — layer counts, KV head config (HIGH confidence)
- FastAPI StreamingResponse docs — SSE implementation pattern (HIGH confidence)
- httpx async streaming docs — `aiter_bytes()` pattern (HIGH confidence)
- RunPod Flash docs — LB pass-through behavior (MEDIUM confidence — confirmed by live testing in v0.1.0)

---
*Architecture research for: RunPod Flash LLM deployment hardening*
*Researched: 2026-03-22*
