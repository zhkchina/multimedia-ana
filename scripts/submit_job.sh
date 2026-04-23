#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

VIDEO_PATH="${1:-}"
PROFILE="${PROFILE:-standard}"
SAMPLE_FPS="${SAMPLE_FPS:-1.0}"
MAX_FRAMES="${MAX_FRAMES:-128}"
LANGUAGE="${LANGUAGE:-}"

if [[ -z "${VIDEO_PATH}" ]]; then
  echo "Usage: $0 /data/multimedia-ana/your_video.mp4" >&2
  exit 1
fi

if [[ ! -f "${VIDEO_PATH}" ]]; then
  echo "Video file not found: ${VIDEO_PATH}" >&2
  exit 1
fi

if [[ "${VIDEO_PATH}" != "${DATA_ROOT}"/* && "${VIDEO_PATH}" != /data/assets/* ]]; then
  echo "Video must be under ${DATA_ROOT} or /data/assets: ${VIDEO_PATH}" >&2
  exit 1
fi

PAYLOAD="$(cat <<EOF
{
  "input": {
    "file_uri": "${VIDEO_PATH}",
    "messages": [
      {
        "role": "user",
        "content": "请输出结构化视频语义理解结果。"
      }
    ],
    "params": {
      "profile": "${PROFILE}",
      "sample_fps": ${SAMPLE_FPS},
      "max_frames": ${MAX_FRAMES}$(
        if [[ -n "${LANGUAGE}" ]]; then
          printf ',\n      "language": "%s"' "${LANGUAGE}"
        fi
      )
    }
  },
  "options": {
    "wait_seconds": 0
  }
}
EOF
)"

curl --fail --silent --show-error \
  -X POST "${API_BASE_URL}/v1/tasks" \
  -H 'Content-Type: application/json' \
  -d "${PAYLOAD}"
echo
