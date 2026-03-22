# Pitfalls Research

**Domain:** RunPod Flash LLM deployment hardening (v0.2.0)
**Researched:** 2026-03-22
**Confidence:** HIGH (llama.cpp issues), MEDIUM (RunPod-specific), HIGH (SSE testing)

## Critical Pitfalls

### Pitfall 1: NemotronH SSM State Multiplies Per Slot at --parallel 2+

**What goes wrong:**
NemotronH uses Mamba/SSM layers with recurrent state. Unlike attention KV cache (which is small due
to MQA), the SSM state memory scales linearly with `--parallel N`. With N=2, SSM state doubles.
This is separate from the KV cache math and can cause unexpected OOM.

**Why it happens:**
Developers calculate only attention KV cache VRAM (easy math: 48 attn layers × MQA) and forget
that Mamba recurrent state is also per-slot. The SSM state per slot is ~200MB, so N=2 adds ~400MB
— likely fine on 96GB, but needs to be measured, not assumed.

**How to avoid:**
Test `--parallel 2` empirically and monitor VRAM with `nvidia-smi` or `gpustat --watch 1`. Don't
rely purely on theoretical calculations. Check llama.cpp issue #19552 / PR #19559 for NemotronH
SSM slot allocation details.

**Warning signs:**
CUDA out-of-memory error in llama-server logs when first request arrives after raising `--parallel`.

**Phase to address:** v0.2.0 — parallel slots investigation

---

### Pitfall 2: --ctx-size is a Pool, Not Per-Slot

**What goes wrong:**
Setting `--parallel 2` with `--ctx-size 32768` gives each slot only 16K context — half of what
users expect. README says "32K context" but this is only true with `--parallel 1`.

**Why it happens:**
llama-server `--ctx-size` sets the total KV budget shared across ALL slots. Most documentation
presents `--ctx-size` as the context window size, not the total pool. See llama.cpp issue #11681.

**How to avoid:**
When raising `--parallel`, also raise `--ctx-size` proportionally: `--ctx-size = parallel × target_context`.
For `--parallel 2` with 32K context per slot: `--ctx-size 65536`.
Document this trade-off explicitly in README.

**Warning signs:**
Long conversations get truncated unexpectedly when `--parallel` > 1; token count errors in responses.

**Phase to address:** v0.2.0 — parallel slots investigation + README update

---

### Pitfall 3: Slot Priming Only Covers Slot 0 With --parallel 2+

**What goes wrong:**
The current `_slot_primed` implementation sends one warmup request, priming only slot 0. With
`--parallel 2`, the first real request that hits slot 1 still has uninitialized KV cache and may
time out.

**Why it happens:**
The warmup was designed for `--parallel 1`. llama-server assigns requests to slots round-robin or
based on availability — slot 1 may not be touched by a single warmup request.

**How to avoid:**
When raising `--parallel N`, send N concurrent warmup requests during health check to prime all
slots. Or use llama-server's `/slots` endpoint to verify all slots are initialized.

**Warning signs:**
First request after health check succeeds, but second concurrent request times out.

**Phase to address:** v0.2.0 — parallel slots implementation

---

### Pitfall 4: E2E Verification Against Warm Worker Masks Cold Start Bugs

**What goes wrong:**
Testing against a running worker with model already loaded in VRAM passes all checks, but a
"fresh volume" cold start (new user, clean state) fails because the binary-restore or model-load
step has a bug that's not exercised in warm tests.

**Why it happens:**
The warm path (binary already cached, model already loaded) skips most of the seed/restore code.
Bugs in seed output format, binary path, or cold start sequence are invisible.

**How to avoid:**
True E2E verification requires wiping the volume or using a separate test volume, then running the
full deploy → seed → first cold start sequence. This is the only way to confirm a stranger can
clone and use the repo.

**Warning signs:**
Tests pass but README disclaimer "not fully verified" is still accurate.

**Phase to address:** v0.2.0 — E2E verification

---

### Pitfall 5: RunPod Flash ~600s Hard HTTP Timeout

**What goes wrong:**
RunPod Flash has a hard HTTP timeout (~600 seconds) on the load balancer. Requests exceeding this
are terminated with a 504 error regardless of `execution_timeout` in `nemotron.py`. Very long
generations (or slow first requests after cold start) can hit this.

**Why it happens:**
The configured `execution_timeout` controls worker lifecycle, not per-request HTTP timeout. The LB
timeout is a separate, platform-enforced limit.

**How to avoid:**
Keep `max_tokens` reasonable in integration tests. Document the platform timeout in README for
users who want very long generations. For streaming, connection is kept alive by token delivery —
this mainly affects non-streaming requests with very long completions.

**Warning signs:**
504 errors on long non-streaming requests; errors not reproducible with streaming or short requests.

**Phase to address:** v0.2.0 — documentation

---

### Pitfall 6: curl Buffers SSE by Default (Missing -N)

**What goes wrong:**
Testing streaming with `curl` without the `-N` / `--no-buffer` flag causes curl to buffer the
entire response before displaying it. Streaming appears to "not work" when it actually does.

**Why it happens:**
curl's default behavior buffers output for efficiency. Without `-N`, SSE tokens accumulate
silently and are printed all at once when the connection closes.

**How to avoid:**
Always use `curl -N` for SSE tests. Document this in testing instructions and README examples.

**Warning signs:**
curl output appears after a long delay, all at once, rather than token-by-token.

**Phase to address:** v0.2.0 — streaming verification + docs

---

### Pitfall 7: Proxy Buffering Masks SSE Failure Under Parallel Load

**What goes wrong:**
SSE streaming appears to work in isolation but fails under concurrent load because a proxy or
middleware layer starts buffering when multiple connections are open simultaneously.

**Why it happens:**
Some nginx configurations only disable buffering for the first N connections. Under `--parallel 2`
with concurrent streaming requests, one connection may be buffered by an intermediate layer.

**How to avoid:**
Test streaming with two concurrent clients simultaneously, not just serially. The `X-Accel-Buffering: no`
header must be present on every response, verified under concurrent load.

**Warning signs:**
Streaming works in isolation; second concurrent streaming request hangs then delivers all at once.

**Phase to address:** v0.2.0 — streaming e2e verification

---

### Pitfall 8: "Fresh Volume" vs "Worker Restart" Are Different Things

**What goes wrong:**
Testing a worker restart (container stops/starts with volume intact) is confused with a "fresh
volume" cold start (new user with no cached binary). These exercise completely different code paths.

**Why it happens:**
Worker restart: binary already on volume → restore in seconds → load model.
Fresh volume: binary missing → must trigger seed first → 30-90 min build → then inference workers work.
Developers test the restart path and declare E2E "verified" without testing the fresh path.

**How to avoid:**
For true E2E verification, use a separate RunPod volume with no pre-cached binary. Follow the
seed → deploy → cold start sequence documented in README. Verify the README's "quickstart" steps
produce a working endpoint from a clean state.

**Warning signs:**
README quickstart says "run `python nemotron.py seed` first" but this step has never been tested
end-to-end on a fresh volume.

**Phase to address:** v0.2.0 — E2E verification

---

### Pitfall 9: RunPod SDK Routing Bug Serializes Requests to One Worker

**What goes wrong:**
RunPod SDK versions 1.7.11–1.7.12 contained a routing bug that sent all requests to the same
worker even when multiple workers were available. Parallel slot tests appear to show correct
concurrency, but requests are actually being serialized.

**Why it happens:**
The bug was in RunPod's request routing layer. Symptoms look like `--parallel 1` even with
`--parallel 2` because the single active worker handles all requests sequentially.

**How to avoid:**
Pin `runpod-flash>=1.8.1` (already in project). Verify by checking worker logs — both requests
should appear in llama-server logs with overlapping timestamps.

**Warning signs:**
Concurrent requests take 2× single-request time despite `--parallel 2`; both requests appear in
the same worker's llama-server logs sequentially rather than overlapping.

**Phase to address:** v0.2.0 — parallel slots investigation

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Testing only warm path | Fast iteration | "Works for me" but fails for new users | Never — E2E requires fresh volume test |
| `--parallel 1` default | Zero OOM risk | Single request at a time; queuing for concurrent users | Acceptable for v0.1.0; document and investigate in v0.2.0 |
| Keeping `download_model.py` | Existing users may reference it | Confusion about which script to use; stale code | Remove in v0.2.0 cleanup |

## "Looks Done But Isn't" Checklist

- [ ] **E2E verification:** Tested warm path only — verify with actual fresh volume cold start
- [ ] **Parallel slots:** `--parallel 2` set but slot priming only covers slot 0 — verify all N slots primed
- [ ] **Streaming:** Tested non-streaming only — verify `curl -N` shows incremental tokens
- [ ] **Streaming:** Tested serial only — verify two concurrent streaming requests both stream
- [ ] **Cleanup:** `download_model.py` removed from repo (superseded by `python nemotron.py seed`)
- [ ] **README disclaimer:** "under active debugging / not fully verified" still present — remove only after fresh volume E2E passes

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|-----------------|--------------|
| NemotronH SSM state per slot | v0.2.0 parallel investigation | `nvidia-smi` shows no OOM at `--parallel 2` |
| --ctx-size pool vs per-slot | v0.2.0 parallel investigation | README documents trade-off; `--ctx-size` set correctly |
| Slot priming N slots | v0.2.0 parallel implementation | All N warmup requests complete before health returns ok |
| Warm worker masks cold start bugs | v0.2.0 E2E verification | Fresh volume test passes all steps |
| RunPod 600s timeout | v0.2.0 documentation | README mentions platform timeout limit |
| curl -N for SSE | v0.2.0 streaming verification | README examples use `curl -N` |
| Proxy buffering under load | v0.2.0 streaming verification | Concurrent streaming test both deliver tokens incrementally |
| Fresh volume vs worker restart | v0.2.0 E2E verification | Test procedure uses separate clean volume |
| RunPod SDK routing bug | Already mitigated (pinned >=1.8.1) | Verify version in requirements |

## Sources

- llama.cpp issue #19552 / PR #19559 — NemotronH SSM slot allocation (HIGH confidence)
- llama.cpp issue #11681 — `--ctx-size` as total pool clarification (HIGH confidence)
- RunPod community forum / Discord — 600s LB timeout reports (MEDIUM confidence)
- curl man page — `--no-buffer` / `-N` flag (HIGH confidence)
- RunPod Flash changelog — SDK 1.7.11–1.7.12 routing bug (MEDIUM confidence — community reports)

---
*Pitfalls research for: RunPod Flash LLM deployment hardening (v0.2.0)*
*Researched: 2026-03-22*
