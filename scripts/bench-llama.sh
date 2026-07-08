#!/usr/bin/env bash
# Benchmark llama.cpp inside the inference container on dual-GPU Vulkan hosts.
# Usage: ./scripts/bench-llama.sh [model.gguf]
set -euo pipefail

MODEL="${1:-}"
CONTAINER="${INFERENCE_CONTAINER:-lmpanel-inference}"
BENCH="/opt/llama.cpp/build/bin/llama-bench"
CONTEXT="${BENCH_CONTEXT:-4096}"
GPU_LAYERS="${BENCH_GPU_LAYERS:-99}"

if [[ -z "$MODEL" ]]; then
  echo "Usage: $0 /app/models/<dir>/<model>.gguf" >&2
  exit 1
fi

run_bench() {
  local label="$1"
  shift
  echo "## $label"
  docker exec "$CONTAINER" env "$@" "$BENCH" \
    -m "$MODEL" \
    -c "$CONTEXT" \
    -ngl "$GPU_LAYERS" \
    -fa "${BENCH_FA:-on}" \
    2>/dev/null | tail -n 5
  echo
}

OUTPUT_FILE="${BENCH_OUTPUT:-./logs/bench-$(date +%Y%m%d-%H%M%S).md}"
mkdir -p "$(dirname "$OUTPUT_FILE")"

{
  echo "# llama-bench results"
  echo
  echo "- Model: \`$MODEL\`"
  echo "- Context: $CONTEXT"
  echo "- Container: $CONTAINER"
  echo "- Date: $(date -Iseconds)"
  echo
  echo "| Mode | Command |"
  echo "|------|---------|"

  echo "### Single GPU (device 0)"
  run_bench "single-gpu" GGML_VK_VISIBLE_DEVICES=0

  echo "### Layer split (devices 0,1)"
  run_bench "layer-split" GGML_VK_VISIBLE_DEVICES=0,1

  echo "### Tensor split (devices 0,1)"
  BENCH_SPLIT_MODE=tensor run_bench "tensor-split" GGML_VK_VISIBLE_DEVICES=0,1

  echo "### Flash attention off (single GPU)"
  BENCH_FA=off run_bench "fa-off" GGML_VK_VISIBLE_DEVICES=0

  echo "### KV cache q8_0 (single GPU)"
  docker exec "$CONTAINER" "$BENCH" \
    -m "$MODEL" -c "$CONTEXT" -ngl "$GPU_LAYERS" \
    -ctk q8_0 -ctv q8_0 \
    2>/dev/null | tail -n 5 || true
} | tee "$OUTPUT_FILE"

echo "Wrote $OUTPUT_FILE"
