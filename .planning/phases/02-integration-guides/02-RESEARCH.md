# Phase 2: Integration Guides - Research

**Date:** 2026-03-20
**Phase:** 2
**Requirements:** INTG-01, INTG-02, INTG-03
**Status:** Complete

## Objective

Answer: what do we need to know to plan and execute Phase 2 well?

Phase 2 must ship copy-paste integration guidance for Claude Code, OpenCode, and Mistral Vibe against the RunPod-hosted Nemotron endpoint from Phase 1.

## Key Findings

### 1. Claude Code is not a direct OpenAI-compatible client

- Claude Code settings live in `~/.claude/settings.json`, `.claude/settings.json`, or `.claude/settings.local.json`.
- Claude Code supports an `env` block in `settings.json`, plus auth helpers like `apiKeyHelper`.
- Anthropic's LLM gateway docs require the gateway to expose Anthropic Messages format, Bedrock, or Vertex-compatible endpoints.
- Anthropic documents `ANTHROPIC_BASE_URL` for a gateway URL and `ANTHROPIC_AUTH_TOKEN` for static auth.
- This means the Phase 1 RunPod endpoint cannot be pointed at Claude Code directly if it only exposes `/v1/chat/completions`.

**Planning implication:** INTG-01 needs a documented gateway shim. The lowest-friction path is a LiteLLM proxy config that exposes Anthropic-format endpoints to Claude Code while forwarding to the RunPod OpenAI-compatible backend.

### 2. OpenCode supports custom OpenAI-compatible providers directly

- Current OpenCode docs use `~/.config/opencode/opencode.json` for global config, not `~/.config/opencode/config.json`.
- OpenCode supports a custom provider with `npm: "@ai-sdk/openai-compatible"`.
- The required config fields are `options.baseURL`, optional `options.apiKey`, and model definitions under `provider.<id>.models`.
- OpenCode also supports environment interpolation syntax like `{env:RUNPOD_API_KEY}`.

**Planning implication:** execution must correct the stale requirement/roadmap path in the user-facing docs and use the current file location from upstream docs.

### 3. Mistral Vibe supports generic OpenAI-style providers through TOML config

- Vibe loads `config.toml` from `./.vibe/config.toml` first, then `~/.vibe/config.toml`.
- Provider credentials can come from environment variables or `~/.vibe/.env`.
- Custom providers are declared with `[[providers]]`, using `api_base`, `api_key_env_var`, `api_style = "openai"`, and `backend = "generic"`.
- Models are declared with `[[models]]`, then selected via `active_model`.

**Planning implication:** INTG-03 is viable with a small TOML snippet plus env var exports for endpoint and API key. This is a direct integration, no gateway needed.

### 4. Shared snippet design should use consistent placeholders

Recommended shared placeholders:

- `RUNPOD_BASE_URL` -> RunPod endpoint root, normalized consistently per client
- `RUNPOD_API_KEY` -> auth token if the deployed endpoint is protected
- `RUNPOD_MODEL` -> served model identifier or alias used by the client config

Tool-specific derived values:

- Claude Code: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, plus LiteLLM config pointing at RunPod
- OpenCode: provider `options.baseURL` and `{env:RUNPOD_API_KEY}`
- Mistral Vibe: `api_base` and `api_key_env_var = "RUNPOD_API_KEY"`

### 5. Verification should be mostly automated even though Phase 2 is documentation

- We can verify file existence and required snippet tokens with `rg`.
- We can verify structural correctness of example JSON/TOML/YAML snippets by storing them in standalone example files and parsing them during execution.
- Manual verification is still needed for end-to-end smoke checks inside each client because the repo cannot execute Claude Code, OpenCode, or Vibe itself during CI.

## Recommended Deliverables

Phase 2 should produce:

- `docs/integrations/claude-code.md`
- `docs/integrations/opencode.md`
- `docs/integrations/mistral-vibe.md`
- `examples/claude-code/litellm.config.yaml`
- `examples/opencode/opencode.json`
- `examples/mistral-vibe/config.toml`

This keeps the user-facing docs small while giving execution a concrete set of machine-checkable example files.

## Execution Risks

### Risk 1: Phase wording currently implies direct Claude Code support

The roadmap and requirements read as though Claude Code can point straight at the RunPod endpoint. Current Anthropic docs do not support that assumption.

**Mitigation:** make the guide explicit that Claude Code uses a local or self-hosted LiteLLM gateway in front of RunPod, and call out why.

### Risk 2: OpenCode path in requirements is stale

The requirement currently says `~/.config/opencode/config.json`, but current docs show `~/.config/opencode/opencode.json`.

**Mitigation:** execution should use the current upstream path in all shipped snippets and, if Phase 2 updates planning docs, note the discrepancy directly.

### Risk 3: RunPod model naming may differ from client alias naming

Some clients need a configured model alias rather than the raw served model identifier.

**Mitigation:** example files should define a stable local alias such as `nemotron-runpod`, while the docs explain where to swap in the actual upstream model name if needed.

## Validation Architecture

Phase 2 is docs-heavy, but it can still satisfy Nyquist if execution creates parseable example config files and validates them with quick shell commands.

### Automated Checks

- `python3 -c "import json; json.load(open('examples/opencode/opencode.json'))"` for OpenCode JSON
- `python3 - <<'PY' ... tomllib.load(...)` for Vibe TOML
- `python3 - <<'PY' ... yaml.safe_load(...)` or a lighter grep-based check for LiteLLM YAML, depending on available deps
- `rg` checks for required tokens:
  - Claude Code: `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `apiKeyHelper` or explicit auth guidance, `litellm`
  - OpenCode: `@ai-sdk/openai-compatible`, `baseURL`, `RUNPOD_API_KEY`
  - Vibe: `api_style = "openai"`, `backend = "generic"`, `api_key_env_var = "RUNPOD_API_KEY"`

### Manual Checks

- Copy-paste each snippet into a clean local config location.
- Confirm each client surfaces the configured model/provider.
- Run one prompt against the live endpoint or gateway and confirm the response succeeds.

### Sampling Strategy

- After each documentation/example task: run targeted parse and grep checks.
- After the full plan: run all snippet parsing commands and a final required-token sweep.

## Sources

- Anthropic Claude Code settings: `https://code.claude.com/docs/en/settings`
- Anthropic Claude Code LLM gateway: `https://code.claude.com/docs/en/llm-gateway`
- OpenCode config docs: `https://opencode.ai/docs/config/`
- OpenCode providers docs: `https://opencode.ai/docs/providers/`
- Mistral Vibe configuration docs: `https://docs.mistral.ai/mistral-vibe/introduction/configuration`
