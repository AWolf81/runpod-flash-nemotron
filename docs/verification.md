# E2E Verification Checklist

## Overview

This checklist verifies the full deploy flow from a blank volume — seed → deploy → warmup → inference. Every step has the exact command, expected output, and fields to record timing and results.

**Important:** You must use a **fresh/clean volume** — re-running on a volume that already has the binary and model cached will NOT test the cold start path and will mask any initialization bugs. Either delete the cache files via SSH or create a new network volume before running this checklist.

## Prerequisites

- RunPod account with Flash access and credits
- HuggingFace token with access to `unsloth/NVIDIA-Nemotron-3-Super-120B-A12B-GGUF`
- Python 3.11+ with `runpod-flash` installed (`pip install runpod-flash`)
- A **fresh** RunPod network volume (no existing `/runpod-volume/cache/` or model files)

To verify your volume is clean (via SSH into a worker):

```bash
ls /runpod-volume/cache/llama-server   # should: No such file or directory
ls /runpod-volume/models/              # should: No such file or directory
```

## Verification Steps

### Step 1: Export credentials

**Command:**
```bash
export RUNPOD_API_KEY="rp_your_runpod_key"
export HF_TOKEN="hf_your_huggingface_token"
```

**Expected:** No output. Verify with `echo $RUNPOD_API_KEY` and `echo $HF_TOKEN`.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________

---

### Step 2: Seed the volume

**Command:**
```bash
HF_TOKEN=$HF_TOKEN python nemotron.py seed
```

**Expected output:**
```
Seeding volume 'nemotron-model-cache'

Binary: rebuilt
Model:  downloaded  (/runpod-volume/models/UD-Q4_K_XL/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf)

Next step: flash deploy
```

First-time seed: builds `llama-server` from source (~5–10 min) then downloads model shards (~84 GB, ~20–30 min). Both steps are idempotent — re-running skips anything already present.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________
- Time: ___________________________

---

### Step 3: Verify volume contents

After seed completes, confirm the binary and model are present. Options:

**Option A — via /health after deploy (Step 4 first, then return here):**
```bash
curl https://<endpoint-id>.api.runpod.ai/health -H "Authorization: Bearer $RUNPOD_API_KEY"
```
Expected: `{"status":"cold"}` — confirms binary and model exist (if either were missing, /health returns `missing_binary` or `missing_model`).

**Option B — via SSH:**
1. Go to [console.runpod.io](https://console.runpod.io)
2. Navigate to **Serverless** → find **nemotron-super-120b** → **Workers** tab
3. Find a running worker → click it → **Connect** tab → copy SSH command
4. Run:
```bash
ls -lh /runpod-volume/cache/llama-server          # should exist, ~300 MB
ls /runpod-volume/models/UD-Q4_K_XL/*.gguf        # should list 3 shards
```

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________

---

### Step 4: Deploy

**Command:**
```bash
flash deploy --env production
```

**Expected:** Deploy succeeds, endpoint ID printed (e.g. `hf1ui3wrdsa31u`). Record the endpoint ID.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________
- Endpoint ID: ___________________________

---

### Step 5: Poll /health until cold

**Command:**
```bash
curl https://<endpoint-id>.api.runpod.ai/health -H "Authorization: Bearer $RUNPOD_API_KEY"
```

**Expected:** `{"status":"cold"}` — worker up but warmup not yet triggered.

If you get `missing_binary` or `missing_model`, the seed step (Step 2) did not complete correctly — re-run seed.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________

---

### Step 6: Run warmup

**Command:**
```bash
time bash warmup.sh <endpoint-id>
```

Or, if `DEFAULT_ENDPOINT_ID` in `warmup.sh` already matches your endpoint:
```bash
time bash warmup.sh
```

**Expected output sequence:**
```
==> Scaling endpoint to 1 worker (max 2 for overflow)...
==> Triggering warmup...
==> Waiting for model to load (polling every 10s, keeping worker alive)...
    HH:MM:SS — cold
    HH:MM:SS — warming_up
    HH:MM:SS — warming_up
    ...
    HH:MM:SS — ready

==> Ready! Nemotron is loaded and serving requests.
    Keep this terminal open — Ctrl+C will scale down the endpoint and stop billing.
```

Expected time: ~8m45s (binary restore from volume cache + preload optimization).

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________
- Time: ___________________________

---

### Step 7: Send test inference (first request)

**Command:**
```bash
time curl https://<endpoint-id>.api.runpod.ai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d '{"model":"nemotron","messages":[{"role":"user","content":"Say hello in one sentence."}],"max_tokens":50}'
```

**Expected:** JSON response with `choices[0].message.content` containing a short greeting. The first request after warmup triggers slot priming (a hidden warmup inference) and may take 3–10s.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________
- Time to response: ___________________________
- Response content (brief quote): ___________________________

---

### Step 8: Send second inference (verify slot priming worked)

**Command:** Same curl as Step 7, repeated immediately.

```bash
time curl https://<endpoint-id>.api.runpod.ai/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -d '{"model":"nemotron","messages":[{"role":"user","content":"Say hello in one sentence."}],"max_tokens":50}'
```

**Expected:** Second request responds without timeout. Slot priming (which happens during the /health ready check) pre-initializes the NemotronH SSM recurrent state so the second request doesn't hit a long first-KV-init delay.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________
- Time to response: ___________________________

---

### Step 9: Scale down

**Command:** Press `Ctrl+C` in the warmup.sh terminal.

**Expected output:**
```
==> Scaling endpoint to 0 workers...
==> Endpoint scaled to 0. Goodbye!
```

Verify in the RunPod console that the endpoint returns to 0 active workers and billing stops.

- Result: [ ] Pass  [ ] Fail  Notes: ___________________________

---

## Results Summary

| Step | Description | Status | Notes | Time |
|------|-------------|--------|-------|------|
| 1 | Export credentials | | | — |
| 2 | Seed volume | | | |
| 3 | Verify volume contents | | | — |
| 4 | Deploy | | | — |
| 5 | Poll /health until cold | | | — |
| 6 | Run warmup | | | |
| 7 | First inference | | | |
| 8 | Second inference (slot priming) | | | |
| 9 | Scale down | | | — |

**Overall:** [ ] PASS  [ ] FAIL

---

## Observed Cold Start Timing

| Stage | Expected | Observed |
|-------|----------|----------|
| Seed: llama-server build | ~5–10 min | ___ |
| Seed: model download (~84 GB) | ~20–30 min | ___ |
| Total first seed | ~25–40 min | ___ |
| Cold start: binary restore + model load | ~8m45s | ___ |
| Time to first token (after ready) | ~3–10s | ___ |
| Time to second token (slot primed) | ~3–5s | ___ |

---

## Verification Date

- Date: ___
- Executor: ___
- Volume: fresh (no prior cache) / [describe if otherwise]
