#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-${ROOT_DIR}/docker-compose.yml}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:18086}"
DATA_ROOT="${DATA_ROOT:-/data/multimedia-ana}"

docker_compose() {
  docker compose -f "${COMPOSE_FILE}" "$@"
}
