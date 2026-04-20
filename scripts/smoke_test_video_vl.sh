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

echo "==> Health check: ${API_BASE_URL}/health"
curl --fail --silent --show-error "${API_BASE_URL}/health"
echo

echo "==> Submit job for ${TARGET_VIDEO_PATH}"
JOB_RESPONSE="$(curl --fail --silent --show-error \
  -X POST "${API_BASE_URL}/jobs" \
  -H 'Content-Type: application/json' \
  -d "{
    \"video_uri\": \"${TARGET_VIDEO_PATH}\",
    \"profile\": \"standard\",
    \"sample_fps\": 1.0,
    \"max_frames\": 128
  }")"

echo "${JOB_RESPONSE}"
echo

JOB_ID="$(printf '%s' "${JOB_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "==> Job ID: ${JOB_ID}"

STATUS=""
for ((i=1; i<=MAX_POLLS; i++)); do
  STATUS_RESPONSE="$(curl --fail --silent --show-error "${API_BASE_URL}/jobs/${JOB_ID}")"
  STATUS="$(printf '%s' "${STATUS_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "[${i}/${MAX_POLLS}] status=${STATUS}"

  if [[ "${STATUS}" == "succeeded" ]]; then
    echo "==> Fetch result"
    curl --fail --silent --show-error "${API_BASE_URL}/jobs/${JOB_ID}/result"
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

echo "==> Timeout waiting for job completion: ${JOB_ID}" >&2
exit 3
