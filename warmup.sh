#!/usr/bin/env bash
# warmup.sh — Warm up the nemotron endpoint and keep it alive.
#
# Keep this script running in a terminal for the duration of your session.
# Press Ctrl+C when done — it will automatically scale the endpoint to 0 workers.
#
# Usage:
#   bash warmup.sh                        # loads RUNPOD_API_KEY from .env
#   RUNPOD_API_KEY=rp_... bash warmup.sh  # or pass it inline

set -euo pipefail

# Load .env if present and RUNPOD_API_KEY is not already set
if [[ -z "${RUNPOD_API_KEY:-}" ]] && [[ -f "$(dirname "$0")/.env" ]]; then
    # shellcheck source=.env
    set -a; source "$(dirname "$0")/.env"; set +a
fi

ENDPOINT="https://hf1ui3wrdsa31u.api.runpod.ai"
ENDPOINT_ID="hf1ui3wrdsa31u"
RUNPOD_API="https://api.runpod.io/graphql"

if [[ -z "${RUNPOD_API_KEY:-}" ]]; then
    echo "Error: RUNPOD_API_KEY is not set."
    echo "Usage: RUNPOD_API_KEY=rp_... bash warmup.sh"
    exit 1
fi

scale_down() {
    echo ""
    echo "==> Scaling endpoint to 0 workers..."
    curl -s -X POST "${RUNPOD_API}" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
        -d "{\"query\":\"mutation { updateEndpoint(input: {id: \\\"${ENDPOINT_ID}\\\", workersMin: 0, workersMax: 2}) { id workersMin workersMax } }\"}" \
        > /dev/null
    echo "==> Endpoint scaled to 0. Goodbye!"
    exit 0
}

trap scale_down INT TERM

echo "==> Scaling endpoint to 1 worker (max 2 for overflow)..."
curl -s -X POST "${RUNPOD_API}" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
    -d "{\"query\":\"mutation { updateEndpoint(input: {id: \\\"${ENDPOINT_ID}\\\", workersMin: 1, workersMax: 2}) { id workersMin workersMax } }\"}" \
    > /dev/null

echo "==> Triggering warmup..."
curl -s -X POST "${ENDPOINT}/warmup" \
    -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
    -H "Content-Type: application/json" \
    -d '{}' > /dev/null

echo "==> Waiting for model to load (polling every 10s, keeping worker alive)..."

ready=false

while true; do
    status=$(curl -s -w "\n%{http_code}" "${ENDPOINT}/health" \
        -H "Authorization: Bearer ${RUNPOD_API_KEY}" \
        | python3 -c "
import sys
lines = sys.stdin.read().rsplit('\n', 1)
body, code = lines[0], lines[1] if len(lines) > 1 else '0'
if code in ('502', '503', '504', '000', '0'):
    print('starting')
else:
    try:
        import json; print(json.loads(body).get('status', 'unknown'))
    except Exception:
        print('unknown')
" 2>/dev/null || echo "unreachable")

    if [[ "${ready}" == "false" ]]; then
        echo "    $(date +%H:%M:%S) — ${status}"
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
            -d '{}' > /dev/null
    fi

    sleep 10
done
