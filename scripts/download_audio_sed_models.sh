#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

IMAGE="${AUDIO_SED_WORKER_IMAGE:-multimedia-ana-audio-sed-worker:local}"
CONTAINER_NAME="${AUDIO_SED_DOWNLOAD_CONTAINER_NAME:-multimedia-ana-audio-sed-download}"
OPENFLAM_MODEL="${OPENFLAM_MODEL:-v1-base}"
OPENFLAM_CACHE_DIR="${OPENFLAM_CACHE_DIR:-${DATA_ROOT}/audio-sed/models/openflam}"
DEVICE="${AUDIO_SED_DEVICE:-cuda}"
DOWNLOAD_OPENFLAM="${DOWNLOAD_OPENFLAM:-1}"
DOWNLOAD_BANDIT="${DOWNLOAD_BANDIT:-1}"
BANDIT_MODEL="${BANDIT_MODEL:-dnr-3s-mus64-l1snr}"
BANDIT_REPO_DIR="${BANDIT_REPO_DIR:-${DATA_ROOT}/audio-sed/vendor/bandit}"
BANDIT_MODEL_DIR="${BANDIT_MODEL_DIR:-${DATA_ROOT}/audio-sed/models/bandit}"
MODEL_ARGS=()
if [[ "${DOWNLOAD_OPENFLAM}" = "1" ]]; then
  MODEL_ARGS+=(
    --openflam
    --openflam-model "${OPENFLAM_MODEL}"
    --openflam-cache-dir "${OPENFLAM_CACHE_DIR}"
    --device "${DEVICE}"
  )
fi
if [[ "${DOWNLOAD_BANDIT}" = "1" ]]; then
  MODEL_ARGS+=(
    --bandit
    --bandit-model "${BANDIT_MODEL}"
    --bandit-repo-dir "${BANDIT_REPO_DIR}"
    --bandit-model-dir "${BANDIT_MODEL_DIR}"
  )
fi
BANDIT_EXTRA_ARGS=()
if [[ -n "${BANDIT_CKPT_URL:-}" ]]; then
  BANDIT_EXTRA_ARGS+=(--bandit-ckpt-url "${BANDIT_CKPT_URL}")
fi
if [[ -n "${BANDIT_HPARAMS_URL:-}" ]]; then
  BANDIT_EXTRA_ARGS+=(--bandit-hparams-url "${BANDIT_HPARAMS_URL}")
fi
if [[ -n "${BANDIT_TARBALL_URL:-}" ]]; then
  BANDIT_EXTRA_ARGS+=(--bandit-tarball-url "${BANDIT_TARBALL_URL}")
fi
if [[ -n "${BANDIT_LOCAL_ARCHIVE:-}" ]]; then
  BANDIT_EXTRA_ARGS+=(--bandit-local-archive "${BANDIT_LOCAL_ARCHIVE}")
fi
if [[ "${BANDIT_SKIP_REPO_DOWNLOAD:-0}" = "1" ]]; then
  BANDIT_EXTRA_ARGS+=(--bandit-skip-repo-download)
fi

docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true

docker run --name "${CONTAINER_NAME}" --rm \
  --gpus all \
  --user "${HOST_UID:-1001}:${HOST_GID:-1003}" \
  -e DATA_ROOT="${DATA_ROOT}" \
  -e HOME="${DATA_ROOT}/audio-sed/cache/home" \
  -e HF_HOME="${DATA_ROOT}/audio-sed/cache/huggingface" \
  -e TORCH_HOME="${DATA_ROOT}/audio-sed/cache/torch" \
  -v "${ROOT_DIR}:/workspace:ro" \
  -v "${DATA_ROOT}:${DATA_ROOT}" \
  -w /workspace \
  "${IMAGE}" \
  python3 -m app.audio_sed_worker.download_models \
    "${MODEL_ARGS[@]}" \
    "${BANDIT_EXTRA_ARGS[@]}"
