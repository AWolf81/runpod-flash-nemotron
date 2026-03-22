# Streaming Support

SSE streaming is confirmed working through the Flash LB. When `stream: true` is set, `chat_completions` proxies llama-server's SSE stream directly to the client via FastAPI `StreamingResponse`. No buffering occurs in the Flash worker.

## How It Works

The Flash LB is a FastAPI app. The `chat_completions` handler checks the `stream` parameter:

- **`stream: true`** — opens an `httpx` streaming connection to llama-server and yields raw SSE bytes to the client as they arrive via `StreamingResponse`.
- **`stream: false` (default)** — waits for the full response and returns buffered JSON (unchanged behavior).

## Client Configuration

### curl

```bash
curl -N -X POST "${RUNPOD_ENDPOINT_URL}/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -d '{"model":"nemotron","messages":[{"role":"user","content":"Hello"}],"stream":true}'
```

The `-N` flag disables curl's own output buffering so you see chunks as they arrive.

### Claude Code

Claude Code sends `stream: true` by default to OpenAI-compatible endpoints. No extra configuration needed — streaming works out of the box with the standard `~/.claude/settings.json` setup.

### OpenCode

OpenCode sends `stream: true` by default to OpenAI-compatible endpoints. The config in `docs/integrations/opencode.md` works without modification.

### Python / httpx

```python
import httpx

async with httpx.AsyncClient(timeout=1800) as client:
    async with client.stream(
        "POST",
        f"{endpoint_url}/v1/chat/completions",
        json={"model": "nemotron", "messages": [...], "stream": True},
    ) as r:
        async for chunk in r.aiter_bytes():
            print(chunk.decode(), end="", flush=True)
```

## Known Limitation

The `X-Accel-Buffering: no` header is set to prevent proxy buffering. However, if RunPod's load balancer introduces its own buffer layer, tokens may arrive in batches rather than one-by-one. Test with `curl -N` to observe whether chunks arrive progressively.

## Fallback

If streaming causes issues (proxy buffering, timeout), set `stream: false` in your client config to use buffered mode. Both modes are supported.
