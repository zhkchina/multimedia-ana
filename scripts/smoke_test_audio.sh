#!/usr/bin/env bash
set -euo pipefail

API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18088}"
AUDIO_FILE="${AUDIO_FILE:-$(find /data/multimedia-ana/example-audio -maxdepth 1 -type f | sort | head -n 1)}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"

if [[ -z "${AUDIO_FILE}" ]]; then
  echo "No audio file found under /data/multimedia-ana/example-audio" >&2
  exit 1
fi

echo "Submitting audio job for ${AUDIO_FILE}"
JOB_RESPONSE="$(curl --fail --silent --show-error \
  -X POST "${API_BASE_URL}/v1/tasks" \
  -H 'Content-Type: application/json' \
  -d "{\"input\":{\"file_uri\":\"${AUDIO_FILE}\",\"params\":{\"profile\":\"movie_zh\",\"language\":\"auto\"}},\"options\":{\"wait_seconds\":0}}")"
JOB_ID="$(printf '%s' "${JOB_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
echo "job_id=${JOB_ID}"

START_TS="$(date +%s)"
while true; do
  STATUS_RESPONSE="$(curl --fail --silent --show-error "${API_BASE_URL}/v1/tasks/${JOB_ID}")"
  STATUS="$(printf '%s' "${STATUS_RESPONSE}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
  echo "status=${STATUS}"

  if [[ "${STATUS}" == "succeeded" ]]; then
    break
  fi

  if [[ "${STATUS}" == "failed" ]]; then
    echo "Job failed: ${STATUS_RESPONSE}" >&2
    exit 1
  fi

  NOW_TS="$(date +%s)"
  if (( NOW_TS - START_TS > TIMEOUT_SECONDS )); then
    echo "Timeout waiting for ${JOB_ID}" >&2
    exit 1
  fi

  sleep "${POLL_INTERVAL_SECONDS}"
done

echo "Fetching result"
curl --fail --silent --show-error "${API_BASE_URL}/v1/tasks/${JOB_ID}/result"
