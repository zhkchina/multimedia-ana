#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

INPUT="${1:-/data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4}"
EXTRA_ARGS=()
if [[ "$#" -gt 1 ]]; then
  EXTRA_ARGS=("${@:2}")
fi
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
WORK_DIR="${WORK_DIR:-${DATA_ROOT}/audio-sed/runtime/debug/${RUN_ID}}"
IMAGE="${AUDIO_SED_WORKER_IMAGE:-multimedia-ana-audio-sed-worker:local}"
BACKEND="${AUDIO_SED_LOCALIZATION_BACKEND:-openflam}"
SEPARATION_BACKEND="${AUDIO_SED_SEPARATION_BACKEND:-bandit}"
DEVICE="${AUDIO_SED_DEVICE:-cpu}"

docker run --rm \
  --gpus all \
  --user "${HOST_UID:-1001}:${HOST_GID:-1003}" \
  -e DATA_ROOT="${DATA_ROOT}" \
  -e HOME="${DATA_ROOT}/audio-sed/cache/home" \
  -e HF_HOME="${DATA_ROOT}/audio-sed/cache/huggingface" \
  -e TORCH_HOME="${DATA_ROOT}/audio-sed/cache/torch" \
  -v "${ROOT_DIR}:/workspace:ro" \
  -v "${DATA_ROOT}:${DATA_ROOT}" \
  -v /data/assets:/data/assets:ro \
  -w /workspace \
  "${IMAGE}" \
  python3 -m app.audio_sed_worker.pipeline \
    --input "${INPUT}" \
    --work-dir "${WORK_DIR}" \
    --device "${DEVICE}" \
    --separation-backend "${SEPARATION_BACKEND}" \
    --localization-backend "${BACKEND}" \
    "${EXTRA_ARGS[@]}"

echo "Audio SED debug output: ${WORK_DIR}"
