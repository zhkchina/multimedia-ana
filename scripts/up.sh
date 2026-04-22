#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

TARGET="${1:-api}"

case "${TARGET}" in
  api)
    docker_compose up -d docker-api
    echo "API is expected at ${API_BASE_URL}"
    ;;
  audio-api|audio)
    docker_compose up -d audio-api
    echo "Audio API is expected at http://127.0.0.1:18088"
    ;;
  *)
    echo "Usage: $0 [api|audio-api|audio]" >&2
    exit 1
    ;;
esac
