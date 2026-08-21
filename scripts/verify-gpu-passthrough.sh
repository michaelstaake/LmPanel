#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="${LMPANEL_INFERENCE_CONTAINER:-lmpanel-inference}"
FAIL=0
HOST_HAS_AMD=0
HOST_HAS_INTEL=0

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

host_drm_driver_count() {
  local driver="$1"
  local count=0
  local card
  for card in /sys/class/drm/card[0-9]; do
    [[ -d "$card" ]] || continue
    [[ "$(basename "$card")" == *-* ]] && continue
    if [[ "$(readlink -f "$card/device/driver" 2>/dev/null | xargs basename 2>/dev/null || true)" == "$driver" ]]; then
      count=$((count + 1))
    fi
  done
  echo "$count"
}

section "Host GPUs"
amd_count="$(host_drm_driver_count amdgpu)"
if [[ "$amd_count" -gt 0 ]]; then
  HOST_HAS_AMD=1
  ok "Host has $amd_count amdgpu DRM device(s)"
else
  ok "No amdgpu DRM devices on host"
fi

intel_count="$(host_drm_driver_count i915)"
xe_count="$(host_drm_driver_count xe)"
intel_total=$((intel_count + xe_count))
if [[ "$intel_total" -gt 0 ]]; then
  HOST_HAS_INTEL=1
  ok "Host has $intel_total Intel DRM device(s) (i915=$intel_count, xe=$xe_count)"
else
  ok "No Intel DRM devices on host"
fi

section "Compose /dev/dri"
if grep -q '/dev/dri:/dev/dri' docker-compose.yml 2>/dev/null; then
  ok "Compose stack passes /dev/dri for AMD/Intel GPUs"
else
  fail "Compose stack missing /dev/dri"
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  warn "Container $CONTAINER is not running — start with: docker compose up -d"
  exit "$FAIL"
fi

section "Container /dev/dri"
dri_listing="$(docker exec "$CONTAINER" ls -la /dev/dri 2>/dev/null || true)"
if [[ -n "$dri_listing" ]]; then
  echo "$dri_listing"
  ok "/dev/dri is mounted in $CONTAINER"
else
  fail "/dev/dri is not available in $CONTAINER"
fi

section "Container VK_ICD_FILENAMES"
vk_icd="$(docker exec "$CONTAINER" printenv VK_ICD_FILENAMES 2>/dev/null || true)"
if [[ -n "$vk_icd" ]]; then
  ok "VK_ICD_FILENAMES=$vk_icd"
  if [[ "$HOST_HAS_AMD" -eq 1 ]] && [[ "$vk_icd" != *radeon_icd* && "$vk_icd" != *amd_icd* ]]; then
    warn "VK_ICD_FILENAMES does not include a Mesa AMD ICD (AMD GPUs may be hidden)"
  fi
  if [[ "$HOST_HAS_INTEL" -eq 1 ]] && [[ "$vk_icd" != *intel_icd* && "$vk_icd" != *intel_hasvk* ]]; then
    warn "VK_ICD_FILENAMES does not include a Mesa Intel ICD (Intel GPUs may be hidden)"
  fi
else
  ok "VK_ICD_FILENAMES unset (Mesa default ICD discovery)"
fi

section "Container vulkaninfo"
vulkan_out="$(docker exec "$CONTAINER" vulkaninfo --summary 2>&1 || true)"
echo "$vulkan_out"
if echo "$vulkan_out" | grep -qiE 'llvmpipe|lavapipe'; then
  if ! echo "$vulkan_out" | grep -qiE 'radeon|amd|intel|arc'; then
    fail "vulkaninfo only shows software renderer — no physical GPU Vulkan ICD is active"
    echo "  Rebuild and recreate: docker compose up -d --build --force-recreate inference"
  fi
fi
if [[ "$HOST_HAS_AMD" -eq 1 ]] && echo "$vulkan_out" | grep -qiE 'radeon|amd'; then
  ok "vulkaninfo lists AMD GPU(s)"
elif [[ "$HOST_HAS_AMD" -eq 1 ]]; then
  fail "vulkaninfo does not list any AMD GPU"
fi
if [[ "$HOST_HAS_INTEL" -eq 1 ]] && echo "$vulkan_out" | grep -qiE 'intel|arc'; then
  ok "vulkaninfo lists Intel GPU(s)"
elif [[ "$HOST_HAS_INTEL" -eq 1 ]]; then
  fail "vulkaninfo does not list any Intel GPU"
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
