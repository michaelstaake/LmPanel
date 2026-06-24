#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="${LMPANEL_INFERENCE_CONTAINER:-lmpanel-inference}"
FAIL=0

section() {
  echo ""
  echo "== $1 =="
}

warn() {
  echo "WARNING: $*" >&2
  FAIL=1
}

fail() {
  echo "FAIL: $*" >&2
  FAIL=1
}

ok() {
  echo "OK: $*"
}

section "Host NVIDIA"
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || warn "nvidia-smi failed on host"
else
  warn "nvidia-smi not found on host"
fi

section "Host Vulkan ICD"
host_icd=""
for path in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
  if [[ -f "$path" ]]; then
    host_icd="$path"
    ok "Host has $path"
    break
  fi
done
if [[ -z "$host_icd" ]]; then
  fail "nvidia_icd.json not found on host — install NVIDIA driver Vulkan support"
fi

section "Compose override"
if [[ -f docker-compose.override.yml ]]; then
  if grep -q 'NVIDIA_DRIVER_CAPABILITIES' docker-compose.override.yml \
    && grep -E 'graphics|all' docker-compose.override.yml >/dev/null; then
    ok "docker-compose.override.yml sets NVIDIA_DRIVER_CAPABILITIES with graphics"
  else
    fail "docker-compose.override.yml missing graphics in NVIDIA_DRIVER_CAPABILITIES"
    echo "  Run: bash scripts/configure-gpu-compose.sh"
  fi
  if grep -q 'nvidia_icd.json' docker-compose.override.yml; then
    ok "docker-compose.override.yml bind-mounts host nvidia_icd.json"
  elif [[ -n "$host_icd" ]]; then
    fail "docker-compose.override.yml missing nvidia_icd.json bind mount"
    echo "  Re-run: bash scripts/configure-gpu-compose.sh"
  fi
  if grep -q 'capabilities:.*graphics' docker-compose.override.yml || grep -q '\[gpu, graphics\]' docker-compose.override.yml; then
    ok "docker-compose.override.yml requests gpu+graphics capabilities"
  else
    fail "docker-compose.override.yml missing graphics in gpus capabilities"
    echo "  Re-run: bash scripts/configure-gpu-compose.sh"
  fi
else
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -q 'GPU '; then
    fail "NVIDIA GPU on host but docker-compose.override.yml is missing"
    echo "  Run: bash scripts/configure-gpu-compose.sh"
  else
    ok "No override file (expected on non-NVIDIA hosts)"
  fi
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  warn "Container $CONTAINER is not running — start with: docker compose up -d"
  exit "$FAIL"
fi

section "Container NVIDIA env"
caps="$(docker exec "$CONTAINER" printenv NVIDIA_DRIVER_CAPABILITIES 2>/dev/null || true)"
if [[ -z "$caps" ]]; then
  fail "NVIDIA_DRIVER_CAPABILITIES is not set in $CONTAINER"
  echo "  Recreate: docker compose up -d --force-recreate inference"
elif [[ "$caps" != *graphics* && "$caps" != "all" ]]; then
  fail "NVIDIA_DRIVER_CAPABILITIES=$caps (must include graphics or all)"
else
  ok "NVIDIA_DRIVER_CAPABILITIES=$caps"
fi

section "Container nvidia-smi"
if docker exec "$CONTAINER" nvidia-smi -L >/dev/null 2>&1; then
  docker exec "$CONTAINER" nvidia-smi -L
else
  fail "nvidia-smi failed inside $CONTAINER"
fi

section "Container Vulkan ICD"
icd="$(docker exec "$CONTAINER" bash -c 'for f in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do [[ -f "$f" ]] && echo "$f" && exit 0; done; exit 1' 2>/dev/null || true)"
if [[ -n "$icd" ]]; then
  ok "Found $icd"
else
  fail "nvidia_icd.json not found in container (graphics driver files not mounted)"
fi

section "Container vulkaninfo"
vulkan_out="$(docker exec "$CONTAINER" vulkaninfo --summary 2>&1 || true)"
echo "$vulkan_out"
if echo "$vulkan_out" | grep -qiE 'llvmpipe|lavapipe'; then
  if ! echo "$vulkan_out" | grep -qiE 'nvidia|geforce|rtx|quadro'; then
    fail "vulkaninfo only shows software renderer — NVIDIA Vulkan ICD is not active"
    echo "  Rebuild and recreate: docker compose up -d --build --force-recreate inference"
  fi
fi
if echo "$vulkan_out" | grep -qiE 'nvidia|geforce|rtx|quadro'; then
  ok "vulkaninfo lists NVIDIA GPU(s)"
fi

section "Inference runtime devices"
devices_json="$(docker exec "$CONTAINER" curl -sf http://localhost:8100/runtime/devices 2>/dev/null || true)"
if [[ -n "$devices_json" ]]; then
  echo "$devices_json"
  if echo "$devices_json" | grep -q '"device_type": "gpu"'; then
    ok "Inference service reports GPU device(s)"
  else
    fail "Inference /runtime/devices has no GPU entries"
  fi
else
  warn "Could not query http://localhost:8100/runtime/devices inside $CONTAINER"
fi

section "Result"
if [[ "$FAIL" -eq 0 ]]; then
  echo "All checks passed."
else
  echo "Some checks failed. Fix the issues above, then run:"
  echo "  docker compose up -d --build --force-recreate inference"
  echo "  docker compose restart backend"
fi

exit "$FAIL"
