#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

TARGET="${1:-api}"

case "${TARGET}" in
  api)
    docker logs -f multimedia-ana-api
    ;;
  worker|video-vl-worker)
    docker logs -f multimedia-ana-video-vl-worker
    ;;
  audio-api)
    docker logs -f multimedia-ana-audio-api
    ;;
  audio-worker)
    docker logs -f multimedia-ana-audio-worker
    ;;
  compose)
    docker_compose logs -f
    ;;
  *)
    echo "Usage: $0 [api|worker|audio-api|audio-worker|compose]" >&2
    exit 1
    ;;
esac
