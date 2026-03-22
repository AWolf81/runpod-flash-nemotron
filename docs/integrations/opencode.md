# OpenCode

OpenCode can talk to the RunPod endpoint directly through its OpenAI-compatible provider support. Put the global config at `~/.config/opencode/opencode.json`.

The older `~/.config/opencode/config.json` path mentioned in the roadmap is outdated. This guide intentionally uses the current upstream path and schema.

Set your endpoint details first:

```bash
export RUNPOD_API_KEY="rp_your_key_here"
export RUNPOD_MODEL="nemotron"
```

Copy this into `~/.config/opencode/opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "runpod": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "RunPod Nemotron",
      "options": {
        "baseURL": "https://api.runpod.example/v1",
        "apiKey": "{env:RUNPOD_API_KEY}"
      },
      "models": {
        "nemotron-runpod": {
          "name": "{env:RUNPOD_MODEL}"
        }
      }
    }
  },
  "model": "runpod:nemotron-runpod"
}
```

Replace `https://api.runpod.example/v1` with your RunPod endpoint root plus `/v1`, then launch OpenCode and confirm `runpod:nemotron-runpod` appears as the selected model. A quick smoke test is sending `Reply with OK` and checking that the request reaches your RunPod logs.
