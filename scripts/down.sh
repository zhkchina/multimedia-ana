#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

docker_compose down
docker rm -f multimedia-ana-video-vl-worker >/dev/null 2>&1 || true
docker rm -f multimedia-ana-audio-worker >/dev/null 2>&1 || true
