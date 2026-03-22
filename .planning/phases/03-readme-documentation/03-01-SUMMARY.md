---
plan: 03-01
phase: 03-readme-documentation
status: complete
completed: 2026-03-21
commit: f7649ec
---

# Summary: 03-01 README Reconciliation

## What Was Done

Updated README.md to match the current repository implementation.

### Task 1: Quickstart and architecture sections

- Updated "What You Get" from `A100 80GB` to `RTX Pro 6000 Blackwell (97 GB VRAM)` — A100/H100 80GB OOM on this model; architecture changed during live debugging
- Confirmed `python nemotron.py seed` and `flash deploy` commands are accurate
- Confirmed single endpoint architecture (no CPU/GPU split in current code)
- Confirmed `llama-server` subprocess approach is accurately documented

### Task 2: Operational guidance and limitations

- Added **Known Limitations** section explicitly noting:
  - Live deployment not yet fully verified (active debugging)
  - LICENSE file not yet added (planned MIT)
  - Streaming not supported through Flash LB
  - EU-RO-1 datacenter restriction

## Verification

- `rg -n "flash deploy$|python nemotron.py seed|CPU|GPU|chat/completions" README.md` ✓
- `rg -n "cold start|cost|license|limitation" README.md` ✓
- No `flash deploy nemotron.py` pattern in README ✓
- No stale llama-server proxy architecture claims ✓

## Files Modified

- `README.md` — reconciled to current code, added Known Limitations section
