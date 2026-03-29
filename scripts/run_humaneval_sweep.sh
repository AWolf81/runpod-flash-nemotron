#!/usr/bin/env bash
set -euo pipefail

# Runs a benchmark sweep across llama-server runtime settings by redeploying
# with different LLAMA_PARALLEL / LLAMA_CTX_SIZE values.
#
# Usage:
#   bash scripts/run_humaneval_sweep.sh [endpoint-id]
#
# Env:
#   RUNPOD_API_KEY=...
#   BENCH_ENV=production
#   BENCH_N=20
#   BENCH_WORKERS=1
#   BENCH_MODEL=nemotron-super-120b-iq4
#   BENCH_SCALER_VALUE=4
#   BENCH_UPSCALE_TRIGGER_REQUESTS=0
#   BENCH_UPSCALE_TRIGGER_MAX_TOKENS=64
#   BENCH_UPSCALE_TRIGGER_SLEEP=12
#   BENCH_PROFILE=standard|limits
#   BENCH_CTX_SAFE_MAX=100000
#   BENCH_CTX_EXPERIMENTAL_MAX=131072
#   BENCH_ALLOW_EXPERIMENTAL=1
#   SWEEP_MATRIX="1:32768:p1-ctx32768,2:32768:p2-ctx32768,2:24576:p2-ctx24576,2:16384:p2-ctx16384"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

if [[ -z "${RUNPOD_API_KEY:-}" ]] && [[ -f ".env" ]]; then
  # shellcheck source=.env
  set -a; source .env; set +a
fi

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
  echo "RUNPOD_API_KEY is required."
  exit 1
fi

ENDPOINT_ID="${1:-c1fb77ul6l2dw2}"
BENCH_ENV="${BENCH_ENV:-production}"
BENCH_N="${BENCH_N:-20}"
BENCH_WORKERS="${BENCH_WORKERS:-1}"
BENCH_MODEL="${BENCH_MODEL:-nemotron-super-120b-iq4}"
BENCH_SCALER_VALUE="${BENCH_SCALER_VALUE:-4}"
BENCH_UPSCALE_TRIGGER_REQUESTS="${BENCH_UPSCALE_TRIGGER_REQUESTS:-0}"
BENCH_UPSCALE_TRIGGER_MAX_TOKENS="${BENCH_UPSCALE_TRIGGER_MAX_TOKENS:-64}"
BENCH_UPSCALE_TRIGGER_SLEEP="${BENCH_UPSCALE_TRIGGER_SLEEP:-12}"
BENCH_PROFILE="${BENCH_PROFILE:-standard}"
BENCH_CTX_SAFE_MAX="${BENCH_CTX_SAFE_MAX:-100000}"
BENCH_CTX_EXPERIMENTAL_MAX="${BENCH_CTX_EXPERIMENTAL_MAX:-131072}"
BENCH_ALLOW_EXPERIMENTAL="${BENCH_ALLOW_EXPERIMENTAL:-1}"

if [[ -z "${SWEEP_MATRIX:-}" ]]; then
  if [[ "${BENCH_PROFILE}" == "limits" ]]; then
    SWEEP_MATRIX="1:100000:p1-ctx100k-safe,1:131072:p1-ctx131072-exp"
  else
    SWEEP_MATRIX="1:32768:p1-ctx32768,2:32768:p2-ctx32768,2:24576:p2-ctx24576,2:16384:p2-ctx16384"
  fi
fi

mkdir -p docs/benchmarks

set_scaler_value() {
  local value="$1"
  [[ -z "${value}" ]] && return 0

  local payload
  payload="{\"scalerType\":\"REQUEST_COUNT\",\"scalerValue\":${value}}"
  local resp
  resp="$(curl -sS --connect-timeout 5 --max-time 20 -X PATCH "https://rest.runpod.io/v1/endpoints/${ENDPOINT_ID}" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
    -d "${payload}" || true)"

  local actual
  actual="$(echo "${resp}" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("scalerValue","?"))' 2>/dev/null || echo "?")"
  echo "Scaler target: requested=${value}, actual=${actual}"
}

trigger_upscale_burst() {
  local request_count="$1"
  if ! [[ "${request_count}" =~ ^[0-9]+$ ]] || (( request_count <= 0 )); then
    return 0
  fi

  echo "Triggering autoscale burst: ${request_count} concurrent requests"
  BENCH_UPSCALE_TRIGGER_REQUESTS="${request_count}" \
  BENCH_UPSCALE_TRIGGER_MAX_TOKENS="${BENCH_UPSCALE_TRIGGER_MAX_TOKENS}" \
  NEMOTRON_BENCH_ENDPOINT="https://${ENDPOINT_ID}.api.runpod.ai" \
  NEMOTRON_BENCH_MODEL="${BENCH_MODEL}" \
  python - <<'PY'
import concurrent.futures
import os
import time

from openai import OpenAI

n = int(os.environ.get("BENCH_UPSCALE_TRIGGER_REQUESTS", "0"))
max_tokens = int(os.environ.get("BENCH_UPSCALE_TRIGGER_MAX_TOKENS", "64"))
endpoint = os.environ["NEMOTRON_BENCH_ENDPOINT"]
model = os.environ["NEMOTRON_BENCH_MODEL"]
api_key = os.environ.get("RUNPOD_API_KEY", "dummy")

client = OpenAI(api_key=api_key, base_url=f"{endpoint}/v1")

def run_one(i: int):
    t0 = time.monotonic()
    try:
        client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": f"Autoscale trigger request {i}: print ok"}],
            max_tokens=max_tokens,
            temperature=0.0,
        )
        return True, time.monotonic() - t0
    except Exception as e:
        return False, f"{e.__class__.__name__}: {e}"

ok = 0
failed = 0
with concurrent.futures.ThreadPoolExecutor(max_workers=n) as pool:
    futures = [pool.submit(run_one, i) for i in range(n)]
    for f in concurrent.futures.as_completed(futures):
        success, _ = f.result()
        if success:
            ok += 1
        else:
            failed += 1

print(f"Autoscale burst done: ok={ok}, failed={failed}")
PY

  local sleep_s="${BENCH_UPSCALE_TRIGGER_SLEEP}"
  if [[ "${sleep_s}" =~ ^[0-9]+$ ]] && (( sleep_s > 0 )); then
    echo "Waiting ${sleep_s}s for scaler reaction..."
    sleep "${sleep_s}"
  fi
}

run_case() {
  local parallel="$1"
  local ctx="$2"
  local label="$3"
  local ctx_tier
  local wp=""

  if ! [[ "${ctx}" =~ ^[0-9]+$ ]]; then
    echo "Invalid ctx value for ${label}: ${ctx}"
    return 1
  fi
  if (( ctx <= 0 )); then
    echo "Invalid ctx value for ${label}: ${ctx}"
    return 1
  fi

  if (( ctx > BENCH_CTX_EXPERIMENTAL_MAX )); then
    echo "Context ${ctx} exceeds max supported cap ${BENCH_CTX_EXPERIMENTAL_MAX} for ${label}."
    return 1
  fi

  if (( ctx <= BENCH_CTX_SAFE_MAX )); then
    ctx_tier="safe"
  else
    ctx_tier="experimental"
    if [[ "${BENCH_ALLOW_EXPERIMENTAL}" != "1" ]]; then
      echo "Skipping ${label}: ctx=${ctx} is experimental (> ${BENCH_CTX_SAFE_MAX}). Set BENCH_ALLOW_EXPERIMENTAL=1 to run."
      return 1
    fi
  fi

  stop_warmup() {
    [[ -z "${wp}" ]] && return 0
    kill -INT "${wp}" 2>/dev/null || true
    sleep 1
    if kill -0 "${wp}" 2>/dev/null; then
      kill -TERM "${wp}" 2>/dev/null || true
      sleep 1
    fi
    if kill -0 "${wp}" 2>/dev/null; then
      kill -KILL "${wp}" 2>/dev/null || true
    fi
    wait "${wp}" 2>/dev/null || true
    wp=""
  }

  echo
  echo "=== CASE ${label} (parallel=${parallel}, ctx=${ctx}, tier=${ctx_tier}) ==="
  set_scaler_value "${BENCH_SCALER_VALUE}"
  LLAMA_PARALLEL="${parallel}" LLAMA_CTX_SIZE="${ctx}" flash deploy --env "${BENCH_ENV}"

  local stamp warmup_log warmup_out ready
  stamp="$(date +%Y-%m-%d-%H%M%S)"
  warmup_log="docs/benchmarks/warmup-${label}-${stamp}.log"
  warmup_out="/tmp/warmup-${label}.out"

  WARMUP_LOG_FILE="${warmup_log}" WARMUP_RECYCLE_ON_START=1 bash warmup.sh "${ENDPOINT_ID}" > "${warmup_out}" 2>&1 &
  wp=$!
  ready=0

  for _ in $(seq 1 180); do
    if grep -q "Ready and stable\." "${warmup_out}"; then
      ready=1
      break
    fi
    sleep 5
  done

  if [[ "${ready}" != "1" ]]; then
    echo "Warmup timeout for ${label}. Last log lines:"
    tail -n 40 "${warmup_out}" || true
    stop_warmup
    return 1
  fi

  echo "Warmup ready for ${label}"
  local runtime_json
  runtime_json="docs/benchmarks/runtime-${label}-${stamp}.json"
  curl -sS -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
    "https://${ENDPOINT_ID}.api.runpod.ai/admin/debug" \
    > "${runtime_json}"

  local actual_parallel actual_ctx
  read -r actual_parallel actual_ctx < <(
    python - "${runtime_json}" <<'PY'
import json
import sys

path = sys.argv[1]
try:
    data = json.load(open(path))
except Exception:
    print("unknown unknown")
    raise SystemExit(0)

cfg = data.get("llama_runtime_config") or {}
parallel = cfg.get("parallel", "unknown")
ctx = cfg.get("ctx_size", "unknown")
print(f"{parallel} {ctx}")
PY
  )

  if [[ "${actual_parallel}" != "${parallel}" || "${actual_ctx}" != "${ctx}" ]]; then
    echo "Runtime mismatch for ${label}: expected parallel=${parallel},ctx=${ctx} but got parallel=${actual_parallel},ctx=${actual_ctx}"
    echo "Not running benchmark for this case."
    python -m json.tool "${runtime_json}" | sed -n '1,120p' || true
    stop_warmup
    return 1
  fi

  echo "Runtime verified for ${label}: parallel=${actual_parallel}, ctx=${actual_ctx}"
  trigger_upscale_burst "${BENCH_UPSCALE_TRIGGER_REQUESTS}"

  NEMOTRON_BENCH_ENDPOINT="https://${ENDPOINT_ID}.api.runpod.ai" \
  NEMOTRON_BENCH_MODEL="${BENCH_MODEL}" \
  python scripts/humaneval.py --n "${BENCH_N}" --workers "${BENCH_WORKERS}" --failures --label "${label}" || true

  stop_warmup
  echo "Completed ${label}"
}

IFS=',' read -r -a CASES <<< "${SWEEP_MATRIX}"
for case in "${CASES[@]}"; do
  IFS=':' read -r parallel ctx label <<< "${case}"
  if [[ -z "${parallel:-}" || -z "${ctx:-}" || -z "${label:-}" ]]; then
    echo "Invalid matrix item: ${case}"
    exit 1
  fi
  run_case "${parallel}" "${ctx}" "${label}"
done

echo
echo "Sweep complete."
echo "Summary:"
sed -n '1,200p' docs/benchmarks/humaneval-summary.md
