#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -f "${ROOT_DIR}/.env" ]]; then
  # shellcheck disable=SC1091
  set -a
  source "${ROOT_DIR}/.env"
  set +a
fi

HOST_UID="${HOST_UID:-1001}"
HOST_GID="${HOST_GID:-1003}"
VIDEO_DIR="${VIDEO_DIR:-/data/multimedia-ana/example-video}"
TESTLAB_DIR="${TESTLAB_DIR:-/data/multimedia-ana/testlab/video-scene}"
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
RUN_DIR="${TESTLAB_DIR}/runs/${RUN_ID}"
QA_NETWORK="${QA_NETWORK:-multimedia-ana_default}"
API_BASE_URL="${API_BASE_URL:-http://video-scene:7860}"
PROFILE="${PROFILE:-standard}"
SCENE_THRESHOLD="${SCENE_THRESHOLD:-27.0}"
MIN_SCENE_LEN="${MIN_SCENE_LEN:-0.6s}"
SAVE_IMAGE_COUNT="${SAVE_IMAGE_COUNT:-3}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-2}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"

mkdir -p "${RUN_DIR}"
echo "video-scene QA run_id=${RUN_ID}"
echo "video-scene QA output_dir=${RUN_DIR}"
echo "video-scene QA network=${QA_NETWORK}"
echo "video-scene QA api_base_url=${API_BASE_URL}"

docker run --rm \
  --network "${QA_NETWORK}" \
  --user "${HOST_UID}:${HOST_GID}" \
  -v /data/multimedia-ana:/data/multimedia-ana \
  -v "${ROOT_DIR}":/workspace \
  -w /workspace \
  multimedia-ana-video-scene-qa:local \
  python3 qa/run_scene_suite.py \
    --video-dir "${VIDEO_DIR}" \
    --output-dir "${RUN_DIR}" \
    --api-base-url "${API_BASE_URL}" \
    --profile "${PROFILE}" \
    --threshold "${SCENE_THRESHOLD}" \
    --min-scene-len "${MIN_SCENE_LEN}" \
    --save-image-count "${SAVE_IMAGE_COUNT}" \
    --poll-interval-seconds "${POLL_INTERVAL_SECONDS}" \
    --timeout-seconds "${TIMEOUT_SECONDS}"
