#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

TARGET="${1:-all}"

case "${TARGET}" in
  all)
    docker_compose build
    ;;
  api)
    docker_compose build docker-api
    ;;
  worker|video-vl-worker)
    docker_compose build video-vl-worker
    ;;
  audio-api)
    docker_compose build audio-api
    ;;
  audio-worker)
    docker_compose build audio-worker
    ;;
  audio)
    docker_compose build audio-api audio-worker
    ;;
  scene|video-scene)
    docker_compose build video-scene
    ;;
  *)
    echo "Usage: $0 [all|api|worker|audio-api|audio-worker|audio|scene]" >&2
    exit 1
    ;;
esac
