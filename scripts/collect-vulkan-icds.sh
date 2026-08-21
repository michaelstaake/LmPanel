#!/usr/bin/env bash
# Emit a colon-separated VK_ICD_FILENAMES value for physical GPU drivers.
# Excludes Mesa software renderers (llvmpipe/lavapipe) so they do not hide
# discrete AMD/Intel GPUs.
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
