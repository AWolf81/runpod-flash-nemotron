# Claude Code

Claude Code cannot talk directly to a pure OpenAI-compatible RunPod endpoint through `ANTHROPIC_BASE_URL`. It expects Anthropic-style request and response shapes, so you need a local gateway that translates Anthropic requests to the RunPod OpenAI-compatible backend. The smallest workable option is LiteLLM.

Save the example proxy config from [examples/claude-code/litellm.config.yaml](/media/alexander/code/projects/text-ai/runpod-flash-nemotron/examples/claude-code/litellm.config.yaml), then start LiteLLM locally or in Docker:

```bash
pip install litellm
export RUNPOD_BASE_URL="https://api.runpod.example/v1"
export RUNPOD_API_KEY="rp_your_key_here"
export RUNPOD_MODEL="nemotron"
litellm --config examples/claude-code/litellm.config.yaml --port 4000
```

Point Claude Code at the local LiteLLM gateway with environment variables:

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:4000"
export ANTHROPIC_AUTH_TOKEN="local-dev-token"
```

Or add the same values to `~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000",
    "ANTHROPIC_AUTH_TOKEN": "local-dev-token"
  }
}
```

After LiteLLM is running, start Claude Code and send a short prompt such as `Reply with OK`. If the request succeeds and LiteLLM logs a forwarded call to your RunPod `/v1` endpoint, the bridge is wired correctly.
