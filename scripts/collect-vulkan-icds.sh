#!/usr/bin/env bash
# Emit a colon-separated VK_ICD_FILENAMES value for physical GPU drivers.
# Excludes Mesa software renderers (llvmpipe/lavapipe) so NVIDIA hosts do not
# silently hide AMD/Intel GPUs when mixed cards are present.
set -euo pipefail

declare -A seen=()
icds=()

add_icd() {
  local path="$1"
  [[ -f "$path" ]] || return
  [[ -n "${seen[$path]:-}" ]] && return
  seen[$path]=1
  icds+=("$path")
}

is_software_icd() {
  case "$(basename "$1")" in
    lvp_icd.*|virtio_icd.*|gfxstream_icd.*) return 0 ;;
  esac
  return 1
}

# NVIDIA proprietary ICD (injected by the NVIDIA Container Toolkit).
if [[ -e /dev/nvidia0 ]]; then
  for icd in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
    add_icd "$icd"
  done
fi

# Mesa ICDs for AMD (RADV) and Intel (ANV/HasVK), etc.
for dir in /usr/share/vulkan/icd.d /etc/vulkan/icd.d; do
  [[ -d "$dir" ]] || continue
  for icd in "$dir"/*.json; do
    [[ -f "$icd" ]] || continue
    case "$(basename "$icd")" in
      nvidia_icd.json) continue ;;
    esac
    if is_software_icd "$icd"; then
      continue
    fi
    add_icd "$icd"
  done
done

if [[ ${#icds[@]} -eq 0 ]]; then
  exit 0
fi

(IFS=:; echo "${icds[*]}")
