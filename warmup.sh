#!/usr/bin/env bash
# warmup.sh — Warm up the nemotron endpoint and keep it alive.
#
# Keep this script running in a terminal for the duration of your session.
# Press Ctrl+C when done — it will automatically scale the endpoint to 0 workers.
#
# Usage:
#   bash warmup.sh                              # uses default endpoint ID, loads RUNPOD_API_KEY from .env
#   bash warmup.sh <endpoint-id>               # specify a different endpoint ID
#   RUNPOD_API_KEY=rp_... bash warmup.sh       # pass API key inline
#   RUNPOD_API_KEY=rp_... bash warmup.sh <id>  # both

set -euo pipefail

# Load .env if present and RUNPOD_API_KEY is not already set
if [[ -z "${RUNPOD_API_KEY:-}" ]] && [[ -f "$(dirname "$0")/.env" ]]; then
    # shellcheck source=.env
    set -a; source "$(dirname "$0")/.env"; set +a
fi

DEFAULT_ENDPOINT_ID="hf1ui3wrdsa31u"
ENDPOINT_ID="${1:-${DEFAULT_ENDPOINT_ID}}"
ENDPOINT="https://${ENDPOINT_ID}.api.runpod.ai"
RUNPOD_REST_API="https://rest.runpod.io/v1"
RUNPOD_GRAPHQL_API="https://api.runpod.io/graphql"
# GPU types are read from nemotron.py at runtime — single source of truth
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
mapfile -t GPU_TYPES < <(python3 "${SCRIPT_DIR}/nemotron.py" gpu-types 2>/dev/null || true)

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    echo "Error: RUNPOD_API_KEY is not set."
    echo "Usage: RUNPOD_API_KEY=rp_... bash warmup.sh"
    exit 1
fi

scale() {
    local min=$1 max=$2
    local result
    result=$(curl -s -X PATCH "${RUNPOD_REST_API}/endpoints/${ENDPOINT_ID}" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
        -d "{\"workersMin\": ${min}, \"workersMax\": ${max}}")
    local actual_min actual_max
    actual_min=$(echo "${result}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['workersMin'])" 2>/dev/null || echo "?")
    actual_max=$(echo "${result}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['workersMax'])" 2>/dev/null || echo "?")
    echo "    workers: min=${actual_min} max=${actual_max}"
}

_scaled_down=false
scale_down() {
    [[ "${_scaled_down}" == "true" ]] && return
    _scaled_down=true
    echo ""
    echo "==> Scaling endpoint to 0 workers..."
    scale 0 2
    echo "==> Endpoint scaled to 0. Goodbye!"
}

trap scale_down INT TERM EXIT

echo "==> Checking GPU stock availability..."
if [[ "${#GPU_TYPES[@]}" -eq 0 ]]; then
    echo "    (could not read GPU types from nemotron.py)"
else
    for _gpu in "${GPU_TYPES[@]}"; do
        _stock=$(curl -s -X POST "${RUNPOD_GRAPHQL_API}?api_key=${RUNPOD_API_KEY}" \
            -H "Content-Type: application/json" \
            -d "{\"query\":\"{ gpuTypes(input: {id: \\\"${_gpu}\\\"}) { lowestPrice(input: {gpuCount: 1, minMemoryInGb: 8, minVcpuCount: 2, secureCloud: false}) { stockStatus } } }\"}" \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['data']['gpuTypes'][0]['lowestPrice']['stockStatus'])" 2>/dev/null || echo "unknown")
        if [[ "${_stock}" == "Low" ]]; then
            echo "    ${_gpu} — stock: Low (expect longer wait, may take 10–20+ min)"
        elif [[ "${_stock}" == "High" ]]; then
            echo "    ${_gpu} — stock: High (worker should start within 2–5 min)"
        else
            echo "    ${_gpu} — stock: ${_stock}"
        fi
    done
fi

echo "==> Scaling endpoint to 1 worker (max 2 for overflow)..."
scale 1 2

_wait_start=$(date +%s)
echo "==> Waiting for worker to start, then triggering warmup (polling every 10s)..."
echo "    Started waiting at $(date +%H:%M:%S) — GPU allocation typically takes 2–5 min, then model load ~5–10 min"

ready=false
warmup_sent=false

while true; do
    http_code=$(curl -s -o /dev/null -w "%{http_code}" "${ENDPOINT}/health" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" 2>/dev/null || echo "000")

    if [[ "${http_code}" == "502" || "${http_code}" == "503" || "${http_code}" == "504" || "${http_code}" == "000" ]]; then
        status="starting"
    else
        status=$(curl -s "${ENDPOINT}/health" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            | python3 -c "
import sys, json
try: print(json.load(sys.stdin).get('status', 'unknown'))
except: print('unknown')
" 2>/dev/null || echo "unknown")
    fi

    # Send warmup once the worker is reachable but not yet ready
    if [[ "${warmup_sent}" == "false" && "${status}" != "starting" ]]; then
        echo "    $(date +%H:%M:%S) — worker up, triggering warmup..."
        curl -s -X POST "${ENDPOINT}/warmup" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            -H "Content-Type: application/json" \
            -d '{}' > /dev/null
        warmup_sent=true
    fi

    if [[ "${ready}" == "false" ]]; then
        _elapsed=$(( $(date +%s) - _wait_start ))
        _elapsed_fmt=$(printf "%dm%02ds" $(( _elapsed / 60 )) $(( _elapsed % 60 )))
        echo "    $(date +%H:%M:%S) [${_elapsed_fmt}] — ${status}"
    fi

    if [[ "${status}" == "ready" ]] && [[ "${ready}" == "false" ]]; then
        ready=true
        echo ""
        echo "==> Ready! Nemotron is loaded and serving requests."
        echo "    Keep this terminal open — Ctrl+C will scale down the endpoint and stop billing."
        echo ""
    fi

    if [[ "${ready}" == "false" ]]; then
        # Keep the LB scaler from scaling to zero while model is still loading
        curl -s -X POST "${ENDPOINT}/keepalive" \
            -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
            -H "Content-Type: application/json" \
            -d '{}' > /dev/null 2>&1 || true
    fi

    sleep 10
done
