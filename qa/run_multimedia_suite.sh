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
RUN_ID="${RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
TESTLAB_DIR="${TESTLAB_DIR:-/data/multimedia-ana/testlab/multimedia}"
RUN_DIR="${TESTLAB_DIR}/runs/${RUN_ID}"
QA_NETWORK="${QA_NETWORK:-multimedia-ana_default}"
SERVICES="${SERVICES:-video-vl scene audio}"
RUNS="${RUNS:-2}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
WAIT_SECONDS="${WAIT_SECONDS:-30}"
PROFILE="${PROFILE:-standard}"
SAMPLE_FPS="${SAMPLE_FPS:-1.0}"
MAX_FRAMES="${MAX_FRAMES:-64}"
VIDEO_VL_BASE_URL="${VIDEO_VL_BASE_URL:-http://docker-api:7860}"
SCENE_BASE_URL="${SCENE_BASE_URL:-http://video-scene:7860}"
AUDIO_BASE_URL="${AUDIO_BASE_URL:-http://audio-api:7860}"
VIDEO_INPUT="${VIDEO_INPUT:-/data/multimedia-ana/example-video/BV1CidqBUE2R.mp4}"
SCENE_INPUT="${SCENE_INPUT:-/data/multimedia-ana/example-video/BV1CidqBUE2R.mp4}"
AUDIO_INPUT="${AUDIO_INPUT:-/data/multimedia-ana/example-audio/audio_mandarin.mp3}"

mkdir -p "${RUN_DIR}"
echo "multimedia QA run_id=${RUN_ID}"
echo "multimedia QA output_dir=${RUN_DIR}"
echo "multimedia QA services=${SERVICES}"

docker run --rm \
  --network "${QA_NETWORK}" \
  --user "${HOST_UID}:${HOST_GID}" \
  -v /data/multimedia-ana:/data/multimedia-ana \
  -v "${ROOT_DIR}":/workspace \
  -w /workspace \
  multimedia-ana-video-scene-qa:local \
  python3 qa/run_multimedia_suite.py \
    --output-dir "${RUN_DIR}" \
    --services ${SERVICES} \
    --runs "${RUNS}" \
    --poll-interval-seconds "${POLL_INTERVAL_SECONDS}" \
    --timeout-seconds "${TIMEOUT_SECONDS}" \
    --wait-seconds "${WAIT_SECONDS}" \
    --profile "${PROFILE}" \
    --sample-fps "${SAMPLE_FPS}" \
    --max-frames "${MAX_FRAMES}" \
    --video-vl-base-url "${VIDEO_VL_BASE_URL}" \
    --scene-base-url "${SCENE_BASE_URL}" \
    --audio-base-url "${AUDIO_BASE_URL}" \
    --video-input "${VIDEO_INPUT}" \
    --scene-input "${SCENE_INPUT}" \
    --audio-input "${AUDIO_INPUT}"
