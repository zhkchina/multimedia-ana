#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

VIDEO_PATH="${1:-}"
PROFILE="${PROFILE:-standard}"
SAMPLE_FPS="${SAMPLE_FPS:-1.0}"
MAX_FRAMES="${MAX_FRAMES:-64}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
MAX_POLLS="${MAX_POLLS:-720}"

if [[ -z "${VIDEO_PATH}" ]]; then
  echo "Usage: $0 /data/multimedia-ana/your_video.mp4" >&2
  exit 1
fi

if [[ ! -f "${VIDEO_PATH}" ]]; then
  echo "Video file not found: ${VIDEO_PATH}" >&2
  exit 1
fi

submit_job() {
  curl --fail --silent --show-error \
    -X POST "${API_BASE_URL}/jobs" \
    -H 'Content-Type: application/json' \
    -d "{
      \"video_uri\": \"${VIDEO_PATH}\",
      \"profile\": \"${PROFILE}\",
      \"sample_fps\": ${SAMPLE_FPS},
      \"max_frames\": ${MAX_FRAMES}
    }"
}

poll_job() {
  local job_id="$1"
  local start_ts="$2"
  local label="$3"
  local status_response status end_ts elapsed

  for ((i=1; i<=MAX_POLLS; i++)); do
    status_response="$(curl --fail --silent --show-error "${API_BASE_URL}/jobs/${job_id}")"
    status="$(printf '%s' "${status_response}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    echo "[${label}] poll=${i}/${MAX_POLLS} status=${status}"

    if [[ "${status}" == "succeeded" ]]; then
      end_ts="$(date +%s)"
      elapsed="$((end_ts - start_ts))"
      printf '%s' "${status_response}" > "/tmp/${job_id}.status.json"
      echo "[${label}] done in ${elapsed}s"
      return 0
    fi

    if [[ "${status}" == "failed" ]]; then
      echo "[${label}] failed: ${status_response}" >&2
      return 2
    fi

    sleep "${POLL_INTERVAL_SECONDS}"
  done

  echo "[${label}] timeout waiting for ${job_id}" >&2
  return 3
}

echo "==> Health check"
curl --fail --silent --show-error "${API_BASE_URL}/health"
echo

echo "==> Submit two jobs back-to-back"
JOB1_START="$(date +%s)"
JOB1_RESPONSE="$(submit_job)"
JOB1_ID="$(printf '%s' "${JOB1_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "job1=${JOB1_ID}"

JOB2_START="$(date +%s)"
JOB2_RESPONSE="$(submit_job)"
JOB2_ID="$(printf '%s' "${JOB2_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "job2=${JOB2_ID}"

poll_job "${JOB1_ID}" "${JOB1_START}" "job1"
poll_job "${JOB2_ID}" "${JOB2_START}" "job2"

JOB1_STATUS_JSON="$(cat "/tmp/${JOB1_ID}.status.json")"
JOB2_STATUS_JSON="$(cat "/tmp/${JOB2_ID}.status.json")"
JOB1_RESULT="$(printf '%s' "${JOB1_STATUS_JSON}" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("result_files") or [""])[0])')"
JOB2_RESULT="$(printf '%s' "${JOB2_STATUS_JSON}" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("result_files") or [""])[0])')"

echo "==> Summary"
echo "job1 id: ${JOB1_ID}"
echo "job1 result: ${JOB1_RESULT}"
echo "job2 id: ${JOB2_ID}"
echo "job2 result: ${JOB2_RESULT}"
echo "check worker logs to confirm second job reused the loaded model."
