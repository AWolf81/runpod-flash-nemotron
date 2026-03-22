# Stack Research

**Domain:** RunPod Flash LLM deployment hardening (v0.2.0)
**Researched:** 2026-03-22
**Confidence:** HIGH

## Recommended Stack for v0.2.0 Testing & Hardening

### Core Testing Libraries

| Library | Version | Purpose | Why Recommended |
|---------|---------|---------|-----------------|
| `pytest` | >=8.1 | Test runner | Standard Python test framework; excellent async support |
| `pytest-asyncio` | >=0.23 | Async test support | Required for async httpx tests; set `asyncio_mode = "auto"` in pyproject.toml |
| `httpx` | >=0.27 | HTTP client (already in project) | Async streaming client; same library used in production code |
| `httpx-sse` | >=0.4.3 | SSE parsing | Spec-correct SSE parsing via `aconnect_sse()` / `aiter_sse()`; parses `data:` lines correctly |
| `openai` | >=1.30 | OpenAI client | `AsyncOpenAI(base_url=..., api_key="x")` works against llama-server; `.stream()` yields typed chunks; same client Claude Code uses |
| `python-dotenv` | >=1.0 | Env var loading | Loads `RUNPOD_ENDPOINT_URL` / `LLAMA_API_KEY` from `.env` without polluting shell |

### VRAM Monitoring Tools

| Tool | Purpose | Command |
|------|---------|---------|
| `nvitop` | Interactive top-like GPU view | `nvitop` (run in second terminal) |
| `gpustat` | Compact one-line-per-GPU watch | `gpustat --watch 1` |
| `nvidia-smi` | Scriptable MiB values | `nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader,nounits` |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `curl -N` | Test SSE streaming without buffering | `-N` / `--no-buffer` is critical; without it, client buffers response |
| `jq` | Parse JSON responses in shell | Useful for smoke tests and quick endpoint checks |
| `python-dotenv` | Manage `.env` for endpoint URL/key | Never hardcode `RUNPOD_ENDPOINT_URL` in test files |

---

## Installation

```bash
# Test dependencies (add to requirements-test.txt or pyproject.toml [test] group)
pip install pytest>=8.1 pytest-asyncio>=0.23 httpx-sse>=0.4.3 openai>=1.30 python-dotenv>=1.0

# VRAM monitoring (on the RunPod worker, or locally via RunPod SSH)
pip install nvitop gpustat

# pyproject.toml configuration
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## Key Patterns

### E2E Smoke Test Pattern

```python
import pytest
from openai import AsyncOpenAI
import os
from dotenv import load_dotenv

load_dotenv()

@pytest.fixture
def client():
    return AsyncOpenAI(
        base_url=os.environ["RUNPOD_ENDPOINT_URL"],
        api_key=os.environ["LLAMA_API_KEY"],
    )

async def test_non_streaming(client):
    resp = await client.chat.completions.create(
        model="nemotron",
        messages=[{"role": "user", "content": "Say hello."}],
        max_tokens=20,
    )
    assert resp.choices[0].message.content

async def test_streaming(client):
    chunks = []
    async with client.chat.completions.stream(
        model="nemotron",
        messages=[{"role": "user", "content": "Count to 3."}],
        max_tokens=30,
    ) as stream:
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)
    assert len(chunks) > 1  # Received multiple chunks (true streaming)
```

### Parallel Slots Concurrency Test Pattern

```python
import asyncio
import time

async def test_parallel_slots(client):
    """Fire 2 requests simultaneously; both should complete without queueing."""
    start = time.monotonic()
    results = await asyncio.gather(
        client.chat.completions.create(
            model="nemotron",
            messages=[{"role": "user", "content": "Say A."}],
            max_tokens=10,
        ),
        client.chat.completions.create(
            model="nemotron",
            messages=[{"role": "user", "content": "Say B."}],
            max_tokens=10,
        ),
    )
    elapsed = time.monotonic() - start
    # With --parallel 2: elapsed ≈ single request time
    # With --parallel 1: elapsed ≈ 2× single request time (queued)
    assert all(r.choices[0].message.content for r in results)
    print(f"Parallel elapsed: {elapsed:.2f}s")
```

### Streaming SSE Verification with httpx-sse

```python
from httpx_sse import aconnect_sse
import httpx

async def test_sse_raw(endpoint_url, api_key):
    """Verify SSE protocol: Content-Type header, incremental delivery, [DONE] termination."""
    async with httpx.AsyncClient() as client:
        async with aconnect_sse(
            client, "POST", f"{endpoint_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "nemotron", "messages": [...], "stream": True},
        ) as event_source:
            assert "text/event-stream" in event_source.response.headers["content-type"]
            events = []
            async for sse in event_source.aiter_sse():
                events.append(sse.data)
                if sse.data == "[DONE]":
                    break
    assert events[-1] == "[DONE]"
    assert len(events) > 2  # Multiple chunks before [DONE]
```

---

## Alternatives Considered

| Recommended | Alternative | Why Not |
|-------------|-------------|---------|
| `openai` SDK | Raw `httpx` | OpenAI SDK gives typed responses, handles SSE framing; same client Claude Code uses — tests are more realistic |
| `httpx-sse` | Manual SSE parsing | `httpx-sse` handles edge cases (multi-line data, comments, retry); manual parsing misses spec details |
| `pytest-asyncio` | `asyncio.run()` in tests | pytest-asyncio integrates with fixtures and parametrize properly |
| `gpustat` / `nvidia-smi` | `torch.memory_allocated()` | `torch` reports wrong process's VRAM; nvidia-smi queries the actual GPU driver |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `sseclient` | Uses `requests` (sync), wrong transport layer | `httpx-sse` with async httpx |
| `locust` / `k6` | Overkill for 1-2 worker endpoint; adds setup complexity | `asyncio.gather()` in pytest |
| `respx` / `pytest-httpx` | Mocking defeats the purpose of E2E verification | Real endpoint tests |
| `torch.memory_allocated()` | Reports wrong process's VRAM | `nvidia-smi` or `gpustat` |

---

## Cold Start Verification Stack

For verifying the seed → deploy → cold start → inference flow:

```bash
# 1. Check endpoint health
curl -s "${RUNPOD_ENDPOINT_URL}/health" | jq .

# 2. List models
curl -s "${RUNPOD_ENDPOINT_URL}/v1/models" \
  -H "Authorization: Bearer ${LLAMA_API_KEY}" | jq .

# 3. Non-streaming inference
curl -s "${RUNPOD_ENDPOINT_URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${LLAMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron","messages":[{"role":"user","content":"Hello"}],"max_tokens":20}' | jq .

# 4. Streaming inference (note -N for no buffering)
curl -N "${RUNPOD_ENDPOINT_URL}/v1/chat/completions" \
  -H "Authorization: Bearer ${LLAMA_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron","messages":[{"role":"user","content":"Count to 5"}],"stream":true,"max_tokens":50}'
```

---

## Sources

- pytest-asyncio docs — `asyncio_mode = "auto"` configuration (HIGH confidence)
- httpx-sse PyPI / GitHub — `aconnect_sse`, `aiter_sse` API (HIGH confidence)
- OpenAI Python SDK docs — `AsyncOpenAI`, `.stream()` context manager (HIGH confidence)
- nvidia-smi documentation — `--query-gpu` flag for scriptable VRAM monitoring (HIGH confidence)
- llama.cpp issues / community — parallel slot testing methodology (MEDIUM confidence)

---
*Stack research for: RunPod Flash LLM deployment hardening (v0.2.0)*
*Researched: 2026-03-22*
