#!/usr/bin/env bash
# install_llama_server.sh
#
# Builds llama-server from llama.cpp tag b8255 with CUDA support.
# This tag includes:
#   - PR #18058: nemotron_h_moe architecture support (merged 2025-12-16)
#   - PR #20270: mamba2 assert crash fix (merged 2026-03-09)
#
# System cmake 3.22 (Ubuntu 22.04) is too old — we install cmake>=3.28 via pip first.
# Idempotent: skips build if /app/llama-server already exists and works.

set -euo pipefail

BUILD_DIR="/tmp/llama-cpp-build"
INSTALL_DIR="/app"
BINARY="${INSTALL_DIR}/llama-server"
VOLUME_CACHE="/runpod-volume/cache/llama-server"
MODEL_DIR="/runpod-volume/models/UD-Q4_K_XL"
MODEL_PATH="${MODEL_DIR}/NVIDIA-Nemotron-3-Super-120B-A12B-UD-Q4_K_XL-00001-of-00003.gguf"

preload_model() {
    # Read all GGUF shards into Linux page cache in parallel before starting llama-server.
    #
    # Why: llama-server uses mmap() — tensors are loaded lazily on first access. CUDA
    # triggers page faults for each tensor block, reading from the network volume at
    # ~200 MB/s. By pre-reading all shards into RAM first, CUDA DMA hits page cache at
    # ~50 GB/s instead of the network volume, cutting VRAM load time significantly.
    #
    # Strategy: each shard is split into STREAMS_PER_SHARD concurrent dd readers at
    # different offsets. More parallel readers = more concurrent I/O against the volume,
    # saturating its IOPS/throughput headroom that a single sequential reader leaves idle.
    # bs=128M reduces syscall overhead vs cat's default 128K blocks.
    # Each dd process uses O(1) memory — page cache is shared across all readers.
    local STREAMS_PER_SHARD=4
    local BLOCK_SIZE_MB=128
    local BLOCK_SIZE=$((BLOCK_SIZE_MB * 1024 * 1024))

    echo "==> Pre-loading model shards into page cache (${STREAMS_PER_SHARD} streams/shard, bs=${BLOCK_SIZE_MB}M)..."

    local pids=()
    for shard in "${MODEL_DIR}"/*.gguf; do
        [[ -f "${shard}" ]] || continue
        local shard_bytes
        shard_bytes=$(stat -c%s "${shard}")
        local total_blocks=$(( (shard_bytes + BLOCK_SIZE - 1) / BLOCK_SIZE ))
        local blocks_per_stream=$(( (total_blocks + STREAMS_PER_SHARD - 1) / STREAMS_PER_SHARD ))
        local name
        name=$(basename "${shard}")
        echo "    ${name}: ${total_blocks} blocks × ${BLOCK_SIZE_MB}M, ${STREAMS_PER_SHARD} streams"

        for (( s=0; s<STREAMS_PER_SHARD; s++ )); do
            local skip=$(( s * blocks_per_stream ))
            local count=${blocks_per_stream}
            # Last stream may have a partial block — dd handles this gracefully (reads until EOF)
            dd if="${shard}" of=/dev/null bs="${BLOCK_SIZE}" skip="${skip}" count="${count}" 2>/dev/null &
            pids+=($!)
        done
    done

    if [[ ${#pids[@]} -eq 0 ]]; then
        echo "    WARNING: no .gguf shards found in ${MODEL_DIR}, skipping preload"
        return
    fi
    for pid in "${pids[@]}"; do
        wait "${pid}"
    done
    echo "==> Page cache warm — all shards loaded into RAM"
}

auto_warmup() {
    local binary="$1"
    if pgrep -x llama-server &>/dev/null; then
        echo "==> llama-server already running, skipping auto-warmup"
        return
    fi
    preload_model
    echo "==> Auto-warming: starting llama-server in background"
    nohup "${binary}" \
        --model "${MODEL_PATH}" \
        --host 127.0.0.1 \
        --port 8081 \
        --n-gpu-layers 99 \
        --parallel 1 \
        --ctx-size 32768 \
        --flash-attn on \
        >> /var/log/llama-server.log 2>&1 &
    echo "==> llama-server started (pid $!), loading model in background"
}

if [[ -x "${BINARY}" ]] && "${BINARY}" --version &>/dev/null; then
    echo "==> llama-server already installed at ${BINARY}, skipping build"
    "${BINARY}" --version
    auto_warmup "${BINARY}"
    exit 0
fi

if [[ -x "${VOLUME_CACHE}" ]] && "${VOLUME_CACHE}" --version &>/dev/null; then
    echo "==> Restoring llama-server from volume cache"
    cp "${VOLUME_CACHE}" "${BINARY}"
    chmod +x "${BINARY}"
    "${BINARY}" --version
    auto_warmup "${BINARY}"
    exit 0
fi

echo "==> Installing cmake>=3.28 (system cmake 3.22 is too old)"
pip install "cmake>=3.28"

echo "==> Cloning llama.cpp (latest main)"
rm -rf "${BUILD_DIR}"
git clone --depth 1 https://github.com/ggml-org/llama.cpp.git "${BUILD_DIR}"

echo "==> Configuring with CUDA (static build, multi-arch)"
# sm_90 = H200, sm_100 = B200, sm_120 = RTX Pro 6000 Blackwell
# NOTE: the seed runner must use a GPU from this set (currently RTX Pro 6000 Blackwell).
# If you change the inference GPU, update the seed runner GPU in nemotron.py to match
# so the cached binary was built on the same architecture family.
cmake "${BUILD_DIR}" -B "${BUILD_DIR}/build" \
    -DBUILD_SHARED_LIBS=OFF \
    -DGGML_CUDA=ON \
    -DCMAKE_CUDA_ARCHITECTURES="90;100;120"

echo "==> Building llama-server (this takes a few minutes)"
cmake --build "${BUILD_DIR}/build" --config Release -j"$(nproc)" \
    --target llama-server

echo "==> Installing binary to ${INSTALL_DIR}"
cp "${BUILD_DIR}/build/bin/llama-server" "${BINARY}"
chmod +x "${BINARY}"

echo "==> Verifying"
"${BINARY}" --version

echo "==> Caching binary to volume for future cold starts"
mkdir -p "$(dirname "${VOLUME_CACHE}")"
cp "${BINARY}" "${VOLUME_CACHE}"
chmod +x "${VOLUME_CACHE}"

echo "==> Cleaning up"
rm -rf "${BUILD_DIR}"

auto_warmup "${BINARY}"
