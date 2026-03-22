---
phase: 2
slug: integration-guides
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-03-20
---

# Phase 2 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | shell + Python stdlib parsing |
| **Config file** | none - direct command verification |
| **Quick run command** | `rg -n "ANTHROPIC_BASE_URL|@ai-sdk/openai-compatible|api_style = \\\"openai\\\"" docs examples` |
| **Full suite command** | `python3 -c "import json; json.load(open('examples/opencode/opencode.json'))" && python3 -c "import tomllib; tomllib.load(open('examples/mistral-vibe/config.toml','rb'))"` |
| **Estimated runtime** | ~3 seconds |

---

## Sampling Rate

- **After every task commit:** Run `rg -n "ANTHROPIC_BASE_URL|@ai-sdk/openai-compatible|api_style = \\\"openai\\\"" docs examples`
- **After every plan wave:** Run `python3 -c "import json; json.load(open('examples/opencode/opencode.json'))" && python3 -c "import tomllib; tomllib.load(open('examples/mistral-vibe/config.toml','rb'))"`
- **Before `$gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | INTG-01 | grep/manual | `rg -n "ANTHROPIC_BASE_URL|ANTHROPIC_AUTH_TOKEN|litellm" docs/integrations/claude-code.md examples/claude-code` | ❌ W0 | ⬜ pending |
| 2-01-02 | 01 | 1 | INTG-02 | parse + grep | `python3 -c "import json; json.load(open('examples/opencode/opencode.json'))" && rg -n "@ai-sdk/openai-compatible|baseURL|RUNPOD_API_KEY" docs/integrations/opencode.md examples/opencode/opencode.json` | ❌ W0 | ⬜ pending |
| 2-01-03 | 01 | 1 | INTG-03 | parse + grep | `python3 -c "import tomllib; tomllib.load(open('examples/mistral-vibe/config.toml','rb'))" && rg -n "api_style = \\\"openai\\\"|backend = \\\"generic\\\"|RUNPOD_API_KEY" docs/integrations/mistral-vibe.md examples/mistral-vibe/config.toml` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `docs/integrations/claude-code.md` - Claude Code integration guide
- [ ] `docs/integrations/opencode.md` - OpenCode integration guide
- [ ] `docs/integrations/mistral-vibe.md` - Mistral Vibe integration guide
- [ ] `examples/claude-code/litellm.config.yaml` - parseable gateway example
- [ ] `examples/opencode/opencode.json` - parseable OpenCode config
- [ ] `examples/mistral-vibe/config.toml` - parseable Vibe config

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Claude Code can send a prompt through the LiteLLM shim to RunPod | INTG-01 | Requires installed Claude Code and live endpoint | Start LiteLLM with the example config, export Claude env vars, run a one-line prompt, confirm response |
| OpenCode shows the configured custom provider/model and can answer one prompt | INTG-02 | Requires local OpenCode install and live endpoint | Place example config, launch OpenCode, select `nemotron-runpod`, send a prompt |
| Mistral Vibe accepts the custom provider/model and answers one prompt | INTG-03 | Requires local Vibe install and live endpoint | Place example config, export API key env var, run Vibe with the configured model, confirm response |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 5s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-03-20
