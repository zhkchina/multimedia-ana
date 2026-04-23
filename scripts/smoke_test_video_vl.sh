#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18086}"
VIDEO_SRC="${1:-}"
DATA_ROOT="${DATA_ROOT:-/data/multimedia-ana}"
VIDEO_NAME="${VIDEO_NAME:-smoke_test_input.mp4}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-10}"
MAX_POLLS="${MAX_POLLS:-360}"

if [[ -z "${VIDEO_SRC}" ]]; then
  echo "Usage: $0 /path/to/video.mp4" >&2
  exit 1
fi

if [[ ! -f "${VIDEO_SRC}" ]]; then
  echo "Video file not found: ${VIDEO_SRC}" >&2
  exit 1
fi

mkdir -p "${DATA_ROOT}"
TARGET_VIDEO_PATH="${DATA_ROOT}/${VIDEO_NAME}"
if [[ "$(realpath "${VIDEO_SRC}")" != "$(realpath "${TARGET_VIDEO_PATH}")" ]]; then
  cp -f "${VIDEO_SRC}" "${TARGET_VIDEO_PATH}"
fi

echo "==> Health check: ${API_BASE_URL}/healthz"
curl --fail --silent --show-error "${API_BASE_URL}/healthz"
echo

echo "==> Submit task for ${TARGET_VIDEO_PATH}"
TASK_RESPONSE="$(curl --fail --silent --show-error \
  -X POST "${API_BASE_URL}/v1/tasks" \
  -H 'Content-Type: application/json' \
  -d "{
    \"input\": {
      \"file_uri\": \"${TARGET_VIDEO_PATH}\",
      \"messages\": [
        {\"role\": \"system\", \"content\": \"你是一个电影视频分析助手。\"},
        {\"role\": \"user\", \"content\": \"请输出结构化视频语义理解结果。\"}
      ],
      \"params\": {
        \"profile\": \"standard\",
        \"sample_fps\": 1.0,
        \"max_frames\": 128
      }
    },
    \"options\": {
      \"wait_seconds\": 0
    }
  }")"

echo "${TASK_RESPONSE}"
echo

TASK_ID="$(printf '%s' "${TASK_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "==> Task ID: ${TASK_ID}"

STATUS=""
for ((i=1; i<=MAX_POLLS; i++)); do
  STATUS_RESPONSE="$(curl --fail --silent --show-error "${API_BASE_URL}/v1/tasks/${TASK_ID}")"
  STATUS="$(printf '%s' "${STATUS_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "[${i}/${MAX_POLLS}] status=${STATUS}"

  if [[ "${STATUS}" == "succeeded" ]]; then
    echo "==> Fetch result"
    curl --fail --silent --show-error "${API_BASE_URL}/v1/tasks/${TASK_ID}/result"
    echo
    exit 0
  fi

  if [[ "${STATUS}" == "failed" ]]; then
    echo "==> Job failed"
    echo "${STATUS_RESPONSE}"
    exit 2
  fi

  sleep "${POLL_INTERVAL_SECONDS}"
done

echo "==> Timeout waiting for task completion: ${TASK_ID}" >&2
exit 3
