#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

DEFAULT_MODELS=(
  dnr-3s-bark64-l1snr
  dnr-3s-erb64-l1snr
  dnr-3s-mel64-l1snr
  dnr-3s-mus64-l1snr
)

if [[ -n "${BANDIT_GRID_MODELS:-}" ]]; then
  # shellcheck disable=SC2206
  MODELS=(${BANDIT_GRID_MODELS})
else
  MODELS=("${DEFAULT_MODELS[@]}")
fi

LABELS=(
  fight
  dialogue
)
INPUTS=(
  /data/multimedia-ana/example-video/proxy_v1.local.00h19m34s-00h19m46s.clip.mp4
  /data/multimedia-ana/example-video/proxy_v1.local.00h19m46s-00h20m00s.clip.mp4
)

GRID_ID="${GRID_ID:-$(date +%Y%m%d_%H%M%S)}"
GRID_WORK_DIR="${GRID_WORK_DIR:-${DATA_ROOT}/audio-sed/runtime/grid/bandit_${GRID_ID}}"
SUMMARY_TSV="${GRID_WORK_DIR}/summary.tsv"
mkdir -p "${GRID_WORK_DIR}"
printf "model\tlabel\tstream_index\tis_default\tevent_count\tmax_score\tavg_score\tmax_local_rms_dbfs\teffects_path\tresult_json\n" > "${SUMMARY_TSV}"

for model in "${MODELS[@]}"; do
  ckpt_path="${DATA_ROOT}/audio-sed/models/bandit/${model}-bs8/checkpoints/${model}.ckpt"
  if [[ ! -e "${ckpt_path}" ]]; then
    echo "Missing checkpoint for ${model}: ${ckpt_path}" >&2
    echo "Run scripts/download_audio_sed_bandit_grid.sh first." >&2
    exit 1
  fi

  for index in "${!INPUTS[@]}"; do
    label="${LABELS[${index}]}"
    input="${INPUTS[${index}]}"
    work_dir="${GRID_WORK_DIR}/${model}/${label}"
    echo "Running model=${model} label=${label}"
    WORK_DIR="${work_dir}" \
      bash "${SCRIPT_DIR}/run_audio_sed_debug.sh" \
        "${input}" \
        --bandit-model-name "${model}" \
        --bandit-ckpt-path "${ckpt_path}"

    python3 - "${work_dir}/result.json" "${model}" "${label}" "${SUMMARY_TSV}" <<'PY'
import json
import sys
from pathlib import Path

result_path = Path(sys.argv[1])
model = sys.argv[2]
label = sys.argv[3]
summary_tsv = Path(sys.argv[4])
payload = json.loads(result_path.read_text(encoding="utf-8"))
lines = []
for stream in payload["audio_streams"]:
    events = stream.get("events") or []
    scores = [float(event["score"]) for event in events]
    local_rms = [
        float(event["event_local_rms_dbfs"])
        for event in events
        if event.get("event_local_rms_dbfs") is not None
    ]
    lines.append(
        "\t".join(
            [
                model,
                label,
                str(stream["stream_index"]),
                str(stream["is_default_stream"]).lower(),
                str(len(events)),
                f"{max(scores):.4f}" if scores else "",
                f"{sum(scores) / len(scores):.4f}" if scores else "",
                f"{max(local_rms):.2f}" if local_rms else "",
                stream["effects_path"],
                str(result_path),
            ]
        )
    )
with summary_tsv.open("a", encoding="utf-8") as handle:
    for line in lines:
        handle.write(line + "\n")
PY
  done
done

echo "BandIt grid output: ${GRID_WORK_DIR}"
echo "BandIt grid summary: ${SUMMARY_TSV}"
