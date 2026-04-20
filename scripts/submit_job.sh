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

if [[ "${VIDEO_PATH}" != "${DATA_ROOT}"/* ]]; then
  echo "Video must be under ${DATA_ROOT}: ${VIDEO_PATH}" >&2
  exit 1
fi

PAYLOAD="$(cat <<EOF
{
  "video_uri": "${VIDEO_PATH}",
  "profile": "${PROFILE}",
  "sample_fps": ${SAMPLE_FPS},
  "max_frames": ${MAX_FRAMES}$(
    if [[ -n "${LANGUAGE}" ]]; then
      printf ',\n  "language": "%s"' "${LANGUAGE}"
    fi
  )
}
EOF
)"

curl --fail --silent --show-error \
  -X POST "${API_BASE_URL}/jobs" \
  -H 'Content-Type: application/json' \
  -d "${PAYLOAD}"
echo
