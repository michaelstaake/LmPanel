#!/usr/bin/env bash
set -euo pipefail

# When NVIDIA Container Toolkit mounts the proprietary Vulkan ICD, prefer it over
# Mesa llvmpipe/lavapipe from mesa-vulkan-drivers in this image.
if [[ -e /dev/nvidia0 ]]; then
  if [[ -z "${VK_ICD_FILENAMES:-}" ]]; then
    for icd in /usr/share/vulkan/icd.d/nvidia_icd.json /etc/vulkan/icd.d/nvidia_icd.json; do
      if [[ -f "$icd" ]]; then
        export VK_ICD_FILENAMES="$icd"
        break
      fi
    done
  fi

  caps="${NVIDIA_DRIVER_CAPABILITIES:-}"
  if [[ "$caps" != *graphics* && "$caps" != "all" ]]; then
    echo "WARNING: NVIDIA GPU detected but NVIDIA_DRIVER_CAPABILITIES=${caps:-unset}." >&2
    echo "  Vulkan requires the graphics capability. Run: ./lmpanel up --build --force-recreate inference" >&2
  fi

  if [[ -z "${VK_ICD_FILENAMES:-}" ]]; then
    echo "WARNING: NVIDIA GPU detected but nvidia_icd.json was not mounted into the container." >&2
    echo "  Run: ./lmpanel up --build --force-recreate inference" >&2
  fi
fi

exec "$@"
