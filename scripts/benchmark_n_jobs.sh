#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

VIDEO_DIR="${VIDEO_DIR:-/data/multimedia-ana/example-video}"
JOB_COUNT="${1:-}"
PROFILE="${PROFILE:-standard}"
SAMPLE_FPS="${SAMPLE_FPS:-1.0}"
MAX_FRAMES="${MAX_FRAMES:-64}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-5}"
MAX_POLLS="${MAX_POLLS:-1440}"
GPU_SAMPLE_INTERVAL_SECONDS="${GPU_SAMPLE_INTERVAL_SECONDS:-2}"

if [[ ! -d "${VIDEO_DIR}" ]]; then
  echo "Video directory not found: ${VIDEO_DIR}" >&2
  exit 1
fi

mkdir -p "${DATA_ROOT}/benchmark"
RUN_ID="bench_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${DATA_ROOT}/benchmark/${RUN_ID}"
GPU_CSV="${RUN_DIR}/gpu_metrics.csv"
SUMMARY_JSON="${RUN_DIR}/summary.json"
WORKER_LOG="${DATA_ROOT}/video-vl/logs/worker.log"
mkdir -p "${RUN_DIR}"

mapfile -t VIDEO_FILES < <(find "${VIDEO_DIR}" -maxdepth 1 -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.webm' -o -iname '*.avi' \) | sort)

if [[ "${#VIDEO_FILES[@]}" -eq 0 ]]; then
  echo "No video files found under ${VIDEO_DIR}" >&2
  exit 1
fi

if [[ -z "${JOB_COUNT}" ]]; then
  JOB_COUNT="${#VIDEO_FILES[@]}"
fi

if ! [[ "${JOB_COUNT}" =~ ^[0-9]+$ ]] || [[ "${JOB_COUNT}" -le 0 ]]; then
  echo "job_count must be a positive integer: ${JOB_COUNT}" >&2
  exit 1
fi

declare -a JOB_IDS=()
declare -A SUBMIT_TS=()
declare -A STATUS=()
declare -A JOB_VIDEO=()

submit_job() {
  local video_path="$1"
  curl --fail --silent --show-error \
    -X POST "${API_BASE_URL}/v1/tasks" \
    -H 'Content-Type: application/json' \
    -d "{
      \"input\": {
        \"file_uri\": \"${video_path}\",
        \"messages\": [
          {\"role\": \"system\", \"content\": \"你是一个电影视频分析助手。\"},
          {\"role\": \"user\", \"content\": \"请输出结构化视频语义理解结果。\"}
        ],
        \"params\": {
          \"profile\": \"${PROFILE}\",
          \"sample_fps\": ${SAMPLE_FPS},
          \"max_frames\": ${MAX_FRAMES}
        }
      },
      \"options\": {
        \"wait_seconds\": 0
      }
    }"
}

poll_status() {
  local task_id="$1"
  curl --fail --silent --show-error "${API_BASE_URL}/v1/tasks/${task_id}"
}

start_gpu_monitor() {
  {
    echo "timestamp,index,name,util_gpu,util_mem,memory_used_mb,memory_total_mb"
    while :; do
      nvidia-smi \
        --query-gpu=timestamp,index,name,utilization.gpu,utilization.memory,memory.used,memory.total \
        --format=csv,noheader,nounits || true
      sleep "${GPU_SAMPLE_INTERVAL_SECONDS}"
    done
  } >> "${GPU_CSV}" &
  GPU_MONITOR_PID=$!
}

stop_gpu_monitor() {
  if [[ -n "${GPU_MONITOR_PID:-}" ]]; then
    kill "${GPU_MONITOR_PID}" >/dev/null 2>&1 || true
    wait "${GPU_MONITOR_PID}" 2>/dev/null || true
  fi
}

trap stop_gpu_monitor EXIT

echo "==> Health check"
curl --fail --silent --show-error "${API_BASE_URL}/healthz"
echo

echo "==> Start GPU monitor: ${GPU_CSV}"
start_gpu_monitor

echo "==> Submit ${JOB_COUNT} jobs from ${VIDEO_DIR}"
for ((i=1; i<=JOB_COUNT; i++)); do
  video_index="$(( (i - 1) % ${#VIDEO_FILES[@]} ))"
  video_path="${VIDEO_FILES[${video_index}]}"
  response="$(submit_job "${video_path}")"
  job_id="$(printf '%s' "${response}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')"
  JOB_IDS+=("${job_id}")
  SUBMIT_TS["${job_id}"]="$(date +%s)"
  STATUS["${job_id}"]="queued"
  JOB_VIDEO["${job_id}"]="${video_path}"
  echo "job${i}=${job_id} video=${video_path}"
done

echo "==> Poll all jobs"
all_done=0
for ((poll=1; poll<=MAX_POLLS; poll++)); do
  all_done=1
  for job_id in "${JOB_IDS[@]}"; do
    if [[ "${STATUS[${job_id}]}" == "succeeded" || "${STATUS[${job_id}]}" == "failed" ]]; then
      continue
    fi
    status_response="$(poll_status "${job_id}")"
    status="$(printf '%s' "${status_response}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["status"])')"
    STATUS["${job_id}"]="${status}"
    if [[ "${status}" != "succeeded" && "${status}" != "failed" ]]; then
      all_done=0
    fi
  done

  printf '[poll=%s] ' "${poll}"
  for job_id in "${JOB_IDS[@]}"; do
    printf '%s=%s ' "${job_id}" "${STATUS[${job_id}]}"
  done
  echo

  if [[ "${all_done}" -eq 1 ]]; then
    break
  fi
  sleep "${POLL_INTERVAL_SECONDS}"
done

stop_gpu_monitor
trap - EXIT

echo "==> Build summary"
JOB_VIDEO_JSON="$(mktemp)"
{
  printf '{\n'
  for index in "${!JOB_IDS[@]}"; do
    job_id="${JOB_IDS[${index}]}"
    video_path="${JOB_VIDEO[${job_id}]}"
    escaped_video_path="$(printf '%s' "${video_path}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')"
    if [[ "${index}" -gt 0 ]]; then
      printf ',\n'
    fi
    printf '  "%s": %s' "${job_id}" "${escaped_video_path}"
  done
  printf '\n}\n'
} > "${JOB_VIDEO_JSON}"

python3 - "$WORKER_LOG" "$GPU_CSV" "$SUMMARY_JSON" "${VIDEO_DIR}" "$JOB_VIDEO_JSON" "${JOB_IDS[@]}" <<'PY'
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

worker_log = Path(sys.argv[1])
gpu_csv = Path(sys.argv[2])
summary_json = Path(sys.argv[3])
video_dir = sys.argv[4]
job_video_json = Path(sys.argv[5])
job_ids = sys.argv[6:]

log_text = worker_log.read_text(encoding="utf-8", errors="ignore") if worker_log.exists() else ""
lines = log_text.splitlines()
job_video = json.loads(job_video_json.read_text(encoding="utf-8")) if job_video_json.exists() else {}

def first_ts(job_id, marker):
    for line in lines:
        if marker in line and job_id in line:
            return line[:19]
    return None

def to_epoch(ts):
    if ts is None:
        return None
    return int(datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").timestamp())

gpu_rows = []
if gpu_csv.exists():
    with gpu_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                gpu_rows.append({
                    "timestamp": row["timestamp"],
                    "util_gpu": float(row["util_gpu"]),
                    "util_mem": float(row["util_mem"]),
                    "memory_used_mb": float(row["memory_used_mb"]),
                    "memory_total_mb": float(row["memory_total_mb"]),
                })
            except Exception:
                pass

gpu_summary = {
    "samples": len(gpu_rows),
    "avg_util_gpu": round(sum(r["util_gpu"] for r in gpu_rows) / len(gpu_rows), 2) if gpu_rows else None,
    "peak_util_gpu": max((r["util_gpu"] for r in gpu_rows), default=None),
    "avg_memory_used_mb": round(sum(r["memory_used_mb"] for r in gpu_rows) / len(gpu_rows), 2) if gpu_rows else None,
    "peak_memory_used_mb": max((r["memory_used_mb"] for r in gpu_rows), default=None),
}

jobs = []
for job_id in job_ids:
    start_ts = first_ts(job_id, "Picked up task")
    end_ts = first_ts(job_id, "finished successfully")
    start_epoch = to_epoch(start_ts)
    end_epoch = to_epoch(end_ts)
    jobs.append({
        "job_id": job_id,
        "video_path": job_video.get(job_id),
        "worker_started_at": start_ts,
        "worker_finished_at": end_ts,
        "run_seconds": (end_epoch - start_epoch) if start_epoch is not None and end_epoch is not None else None,
    })

summary = {
    "video_dir": video_dir,
    "job_count": len(job_ids),
    "jobs": jobs,
    "gpu_summary": gpu_summary,
    "gpu_csv": str(gpu_csv),
}
summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
PY

rm -f "${JOB_VIDEO_JSON}"

echo "==> Summary saved to ${SUMMARY_JSON}"
