#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

DEFAULT_MODELS=(
  dnr-3s-bark64-l1snr
  dnr-3s-erb64-l1snr
  dnr-3s-mel64-l1snr
  dnr-3s-mus64-l1snr
)

if [[ -n "${BANDIT_GRID_MODELS:-}" ]]; then
  # shellcheck disable=SC2206
  MODELS=(${BANDIT_GRID_MODELS})
else
  MODELS=("${DEFAULT_MODELS[@]}")
fi

if [[ -f "${DATA_ROOT}/audio-sed/vendor/bandit/inference.py" ]]; then
  DEFAULT_SKIP_REPO_DOWNLOAD=1
else
  DEFAULT_SKIP_REPO_DOWNLOAD=0
fi

for model in "${MODELS[@]}"; do
  echo "Preparing BandIt checkpoint: ${model}"
  DOWNLOAD_OPENFLAM=0 \
  DOWNLOAD_BANDIT=1 \
  BANDIT_MODEL="${model}" \
  BANDIT_SKIP_REPO_DOWNLOAD="${BANDIT_SKIP_REPO_DOWNLOAD:-${DEFAULT_SKIP_REPO_DOWNLOAD}}" \
    bash "${SCRIPT_DIR}/download_audio_sed_models.sh"
done
