#!/usr/bin/env bash
set -euo pipefail

# Restrict VK_ICD_FILENAMES to physical Mesa GPU drivers (RADV/ANV) so software
# renderers (llvmpipe/lavapipe) do not hide discrete AMD/Intel cards.
if [[ -z "${VK_ICD_FILENAMES:-}" ]]; then
  collected="$(/usr/local/bin/collect-vulkan-icds.sh || true)"
  if [[ -n "$collected" ]]; then
    export VK_ICD_FILENAMES="$collected"
  fi
fi

exec "$@"
