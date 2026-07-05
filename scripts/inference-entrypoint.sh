#!/usr/bin/env bash
set -euo pipefail

# When an NVIDIA GPU is present, the Container Toolkit mounts the proprietary
# Vulkan ICD. Restrict VK_ICD_FILENAMES to physical GPU drivers only (NVIDIA +
# Mesa RADV/ANV) so mixed AMD/Intel/NVIDIA hosts enumerate every card.
if [[ -z "${VK_ICD_FILENAMES:-}" ]]; then
  collected="$(/usr/local/bin/collect-vulkan-icds.sh || true)"
  if [[ -n "$collected" ]]; then
    export VK_ICD_FILENAMES="$collected"
  fi
fi

if [[ -e /dev/nvidia0 ]]; then
  caps="${NVIDIA_DRIVER_CAPABILITIES:-}"
  if [[ "$caps" != *graphics* && "$caps" != "all" ]]; then
    echo "WARNING: NVIDIA GPU detected but NVIDIA_DRIVER_CAPABILITIES=${caps:-unset}." >&2
    echo "  Vulkan requires the graphics capability. Run: ./lmpanel up --build --force-recreate inference" >&2
  fi

  has_nvidia_icd=0
  for icd in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
    if [[ -f "$icd" ]]; then
      has_nvidia_icd=1
      break
    fi
  done
  if [[ "$has_nvidia_icd" -eq 0 ]]; then
    echo "WARNING: NVIDIA GPU detected but nvidia_icd.json was not mounted into the container." >&2
    echo "  Run: ./lmpanel up --build --force-recreate inference" >&2
  fi
fi

exec "$@"
