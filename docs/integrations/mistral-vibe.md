# Mistral Vibe

Mistral Vibe can use the RunPod deployment as a generic OpenAI-style provider. Store the config in `~/.vibe/config.toml` for a global setup or `./.vibe/config.toml` for a repo-local override.

Credentials can come from normal environment variables or from `~/.vibe/.env`. The example below expects `RUNPOD_API_KEY` and `RUNPOD_MODEL` to be available.

```bash
export RUNPOD_API_KEY="rp_your_key_here"
export RUNPOD_MODEL="nemotron"
```

Copy this into `~/.vibe/config.toml`:

```toml
[env]
RUNPOD_BASE_URL = "https://api.runpod.example/v1"

[[providers]]
name = "runpod"
backend = "generic"
api_base = "${RUNPOD_BASE_URL}"
api_key_env_var = "RUNPOD_API_KEY"
api_style = "openai"

[[models]]
name = "nemotron-runpod"
provider = "runpod"
model_name = "${RUNPOD_MODEL}"

active_model = "nemotron-runpod"
```

Replace `RUNPOD_BASE_URL` with your deployed endpoint root plus `/v1`, start Vibe, and run a short prompt such as `Reply with OK`. If the request succeeds and the `nemotron-runpod` model is active, the integration is wired correctly.
