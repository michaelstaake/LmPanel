#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONTAINER="${LMPANEL_INFERENCE_CONTAINER:-lmpanel-inference}"
FAIL=0
HOST_HAS_NVIDIA=0
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

host_has_nvidia() {
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L 2>/dev/null | grep -q 'GPU '; then
    return 0
  fi
  return 1
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
if host_has_nvidia; then
  HOST_HAS_NVIDIA=1
  nvidia-smi -L || warn "nvidia-smi failed on host"
else
  ok "No NVIDIA GPU reported by nvidia-smi on host"
fi

amd_count="$(host_drm_driver_count amdgpu)"
if [[ "$amd_count" -gt 0 ]]; then
  HOST_HAS_AMD=1
  ok "Host has $amd_count amdgpu DRM device(s)"
else
  ok "No amdgpu DRM devices on host"
fi

intel_count="$(host_drm_driver_count i915)"
if [[ "$intel_count" -gt 0 ]]; then
  HOST_HAS_INTEL=1
  ok "Host has $intel_count i915 DRM device(s)"
else
  ok "No i915 DRM devices on host"
fi

if [[ "$HOST_HAS_NVIDIA" -eq 1 ]]; then
  section "Host NVIDIA Vulkan ICD"
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
fi

section "Compose override"
if [[ "$HOST_HAS_NVIDIA" -eq 1 ]]; then
  if [[ -f docker-compose.override.yml ]]; then
    if grep -q 'NVIDIA_DRIVER_CAPABILITIES' docker-compose.override.yml \
      && grep -E 'graphics|all' docker-compose.override.yml >/dev/null; then
      ok "docker-compose.override.yml sets NVIDIA_DRIVER_CAPABILITIES with graphics"
    else
      fail "docker-compose.override.yml missing graphics in NVIDIA_DRIVER_CAPABILITIES"
      echo "  Run: ./lmpanel up"
    fi
    if grep -q 'capabilities:.*graphics' docker-compose.override.yml || grep -q '\[gpu, graphics\]' docker-compose.override.yml; then
      ok "docker-compose.override.yml requests gpu+graphics capabilities"
    else
      fail "docker-compose.override.yml missing graphics in gpus capabilities"
      echo "  Re-run: ./lmpanel up"
    fi
    if grep -q '/dev/dri:/dev/dri' docker-compose.override.yml docker-compose.yml 2>/dev/null; then
      ok "Compose stack passes /dev/dri for AMD/Intel GPUs"
    else
      warn "Compose stack missing /dev/dri (mixed-vendor hosts need it)"
    fi
    if grep -qE 'libEGL_nvidia|libGLX_nvidia' docker-compose.override.yml; then
      fail "docker-compose.override.yml bind-mounts NVIDIA GL libraries (conflicts with NVIDIA Container Toolkit)"
      echo "  Re-run: ./lmpanel up to regenerate a clean override"
    fi
  else
    fail "NVIDIA GPU on host but docker-compose.override.yml is missing"
    echo "  Run: ./lmpanel up"
  fi
else
  if [[ -f docker-compose.override.yml ]]; then
    warn "docker-compose.override.yml present but host has no NVIDIA GPU"
  else
    ok "No NVIDIA override file (expected on non-NVIDIA hosts)"
  fi
fi

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  warn "Container $CONTAINER is not running — start with: ./lmpanel up"
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

if [[ "$HOST_HAS_NVIDIA" -eq 1 ]]; then
  section "Container NVIDIA env"
  caps="$(docker exec "$CONTAINER" printenv NVIDIA_DRIVER_CAPABILITIES 2>/dev/null || true)"
  if [[ -z "$caps" ]]; then
    fail "NVIDIA_DRIVER_CAPABILITIES is not set in $CONTAINER"
    echo "  Recreate: ./lmpanel up --force-recreate inference"
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

  section "Container NVIDIA Vulkan ICD"
  icd="$(docker exec "$CONTAINER" bash -c 'for f in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do [[ -f "$f" ]] && echo "$f" && exit 0; done; exit 1' 2>/dev/null || true)"
  if [[ -n "$icd" ]]; then
    ok "Found $icd"
  else
    fail "nvidia_icd.json not found in container (graphics driver files not mounted)"
  fi
fi

section "Container VK_ICD_FILENAMES"
vk_icd="$(docker exec "$CONTAINER" printenv VK_ICD_FILENAMES 2>/dev/null || true)"
if [[ -n "$vk_icd" ]]; then
  ok "VK_ICD_FILENAMES=$vk_icd"
  if [[ "$HOST_HAS_NVIDIA" -eq 1 ]] && [[ "$vk_icd" != *nvidia_icd.json* ]]; then
    warn "VK_ICD_FILENAMES does not include the NVIDIA ICD"
  fi
  if [[ "$HOST_HAS_AMD" -eq 1 ]] && [[ "$vk_icd" != *radeon_icd* && "$vk_icd" != *amd_icd* ]]; then
    warn "VK_ICD_FILENAMES does not include a Mesa AMD ICD (AMD GPUs may be hidden)"
  fi
  if [[ "$HOST_HAS_INTEL" -eq 1 ]] && [[ "$vk_icd" != *intel_icd* && "$vk_icd" != *intel_hasvk* ]]; then
    warn "VK_ICD_FILENAMES does not include a Mesa Intel ICD (Intel GPUs may be hidden)"
  fi
else
  if [[ "$HOST_HAS_NVIDIA" -eq 1 ]]; then
    warn "VK_ICD_FILENAMES is unset in $CONTAINER"
  else
    ok "VK_ICD_FILENAMES unset (expected on non-NVIDIA hosts)"
  fi
fi

section "Container vulkaninfo"
vulkan_out="$(docker exec "$CONTAINER" vulkaninfo --summary 2>&1 || true)"
echo "$vulkan_out"
if echo "$vulkan_out" | grep -qiE 'llvmpipe|lavapipe'; then
  if ! echo "$vulkan_out" | grep -qiE 'nvidia|geforce|rtx|quadro|radeon|amd|intel|arc'; then
    fail "vulkaninfo only shows software renderer — no physical GPU Vulkan ICD is active"
    echo "  Rebuild and recreate: ./lmpanel up --build --force-recreate inference"
  fi
fi
if [[ "$HOST_HAS_NVIDIA" -eq 1 ]] && echo "$vulkan_out" | grep -qiE 'nvidia|geforce|rtx|quadro'; then
  ok "vulkaninfo lists NVIDIA GPU(s)"
elif [[ "$HOST_HAS_NVIDIA" -eq 1 ]]; then
  fail "vulkaninfo does not list any NVIDIA GPU"
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
  echo "  ./lmpanel up --build --force-recreate inference"
  echo "  ./lmpanel restart backend"
fi

exit "$FAIL"
