#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker build -f "${ROOT_DIR}/qa/Dockerfile" -t multimedia-ana-video-scene-qa:local "${ROOT_DIR}"
