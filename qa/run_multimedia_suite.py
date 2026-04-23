from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


FINAL_STATUSES = {"succeeded", "failed", "canceled"}
LEGACY_VIDEO_VL_PROMPT = (
    "请对这个视频片段进行电影镜头级语义标注，并严格输出 JSON 对象。"
    "字段包含 scene_summary、shot_type、characters、actions、emotion、location、objects、cinematic_tags、clip_value、reason。"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict[str, Any], dict[str, str]]:
    data = None
    headers: dict[str, str] = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, (json.loads(body) if body else {}), dict(resp.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"detail": body}
        return exc.code, parsed, dict(exc.headers.items())


def first_file(directory: Path) -> Path:
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files:
        raise FileNotFoundError(f"No files found under {directory}")
    return files[0]


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def validate_video_vl_result(result: dict[str, Any]) -> dict[str, Any]:
    output_text = result.get("output_text")
    if not isinstance(output_text, str):
        output_text = result.get("raw_text")
    output_json = result.get("output_json")
    if output_json is None:
        output_json = result.get("analysis")
    return {
        "has_backend": isinstance(result.get("backend"), str),
        "has_model_id": isinstance(result.get("model_id"), str),
        "output_text_length": len(output_text or ""),
        "output_json_is_object": isinstance(output_json, dict) or output_json is None,
    }


def validate_scene_result(result: dict[str, Any]) -> dict[str, Any]:
    scenes = result.get("scenes") or []
    return {
        "scene_count": result.get("scene_count"),
        "scenes_len": len(scenes) if isinstance(scenes, list) else None,
        "image_count": result.get("image_count"),
        "has_scenes": isinstance(scenes, list),
    }


def validate_audio_result(result: dict[str, Any]) -> dict[str, Any]:
    segments = result.get("segments") or []
    aed = result.get("aed") or {}
    return {
        "text_length": len(result.get("text") or ""),
        "segment_count": len(segments) if isinstance(segments, list) else None,
        "aed_present": isinstance(aed, dict),
        "has_metadata": isinstance(result.get("metadata"), dict),
    }


@dataclass(frozen=True)
class ServiceSpec:
    service_name: str
    api_base_url: str
    input_path: str
    validation_fn: Callable[[dict[str, Any]], dict[str, Any]]


SERVICE_SPECS = {
    "video-vl": ServiceSpec(
        service_name="video-vl",
        api_base_url="http://docker-api:7860",
        input_path="/data/multimedia-ana/example-video/BV1CidqBUE2R.mp4",
        validation_fn=validate_video_vl_result,
    ),
    "scene": ServiceSpec(
        service_name="scene",
        api_base_url="http://video-scene:7860",
        input_path="/data/multimedia-ana/example-video/BV1CidqBUE2R.mp4",
        validation_fn=validate_scene_result,
    ),
    "audio": ServiceSpec(
        service_name="audio",
        api_base_url="http://audio-api:7860",
        input_path="/data/multimedia-ana/example-audio/audio_mandarin.mp3",
        validation_fn=validate_audio_result,
    ),
}


class TasksV1Client:
    def __init__(self, spec: ServiceSpec, *, profile: str, sample_fps: float, max_frames: int, wait_seconds: int) -> None:
        self.spec = spec
        self.profile = profile
        self.sample_fps = sample_fps
        self.max_frames = max_frames
        self.wait_seconds = wait_seconds

    def health(self) -> tuple[int, dict[str, Any]]:
        code, payload, _ = request_json(f"{self.spec.api_base_url}/healthz")
        return code, payload

    def submit(self) -> tuple[int, dict[str, Any]]:
        if self.spec.service_name == "video-vl":
            payload = {
                "input": {
                    "file_uri": self.spec.input_path,
                    "messages": [
                        {"role": "user", "content": LEGACY_VIDEO_VL_PROMPT}
                    ],
                    "params": {
                        "profile": self.profile,
                        "sample_fps": self.sample_fps,
                        "max_frames": self.max_frames,
                    },
                },
                "options": {"wait_seconds": self.wait_seconds},
                "metadata": {"request_id": f"qa-{self.spec.service_name}"},
            }
        elif self.spec.service_name == "scene":
            payload = {
                "input": {
                    "file_uri": self.spec.input_path,
                    "params": {
                        "profile": self.profile,
                        "threshold": 27.0,
                        "min_scene_len": "0.6s",
                        "save_image_count": 0,
                        "include_artifacts": False,
                    },
                },
                "options": {"wait_seconds": self.wait_seconds},
                "metadata": {"request_id": f"qa-{self.spec.service_name}"},
            }
        elif self.spec.service_name == "audio":
            payload = {
                "input": {
                    "file_uri": self.spec.input_path,
                    "params": {
                        "profile": "movie_zh",
                        "language": "auto",
                    },
                },
                "options": {"wait_seconds": self.wait_seconds},
                "metadata": {"request_id": f"qa-{self.spec.service_name}"},
            }
        else:
            raise ValueError(f"Unsupported service: {self.spec.service_name}")
        code, body, _ = request_json(f"{self.spec.api_base_url}/v1/tasks", method="POST", payload=payload, timeout=120.0)
        return code, body

    def status(self, task_id: str) -> tuple[int, dict[str, Any], dict[str, str]]:
        return request_json(f"{self.spec.api_base_url}/v1/tasks/{urllib.parse.quote(task_id)}")

    def result(self, task_id: str) -> tuple[int, dict[str, Any]]:
        code, body, _ = request_json(f"{self.spec.api_base_url}/v1/tasks/{urllib.parse.quote(task_id)}/result", timeout=120.0)
        return code, body


def build_client(
    spec: ServiceSpec,
    *,
    profile: str,
    sample_fps: float,
    max_frames: int,
    wait_seconds: int,
):
    return TasksV1Client(
        spec,
        profile=profile,
        sample_fps=sample_fps,
        max_frames=max_frames,
        wait_seconds=wait_seconds,
    )


def parse_task_id(payload: dict[str, Any]) -> str | None:
    for key in ("task_id", "job_id", "id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def parse_status(payload: dict[str, Any]) -> str | None:
    value = payload.get("status")
    return value if isinstance(value, str) else None


def maybe_inline_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    result = payload.get("result")
    return result if isinstance(result, dict) else None


def unwrap_result_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = payload.get("result")
    if isinstance(result, dict):
        return result
    return payload


def run_service(
    *,
    client,
    spec: ServiceSpec,
    runs: int,
    warmup_runs: int,
    poll_interval_seconds: float,
    timeout_seconds: float,
    output_dir: Path,
) -> dict[str, Any]:
    service_dir = output_dir / spec.service_name
    ensure_dir(service_dir)

    health_code, health_payload = client.health()
    if health_code != 200:
        raise RuntimeError(f"{spec.service_name} health check failed: status={health_code} payload={health_payload}")

    results: list[dict[str, Any]] = []
    total_runs = warmup_runs + runs
    for overall_index in range(1, total_runs + 1):
        run_started = time.monotonic()
        submit_code, submit_payload = client.submit()
        task_id = parse_task_id(submit_payload)
        status = parse_status(submit_payload)
        inline_result = maybe_inline_result(submit_payload)
        status_poll_count = 0
        terminal_payload = submit_payload

        if submit_code not in {200, 201, 202}:
            raise RuntimeError(
                f"{spec.service_name} submit failed: status={submit_code} payload={submit_payload}"
            )
        if not task_id:
            raise RuntimeError(f"{spec.service_name} submit did not return task id: payload={submit_payload}")

        if inline_result is None or status not in FINAL_STATUSES:
            deadline = time.monotonic() + timeout_seconds
            while True:
                status_poll_count += 1
                status_code, status_payload, _ = client.status(task_id)
                if status_code != 200:
                    raise RuntimeError(
                        f"{spec.service_name} status failed: status={status_code} payload={status_payload}"
                    )
                terminal_payload = status_payload
                status = parse_status(status_payload)
                if status in FINAL_STATUSES:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"{spec.service_name} task {task_id} did not finish within timeout")
                time.sleep(poll_interval_seconds)

        if inline_result is None:
            result_code, result_payload = client.result(task_id)
            if result_code != 200:
                raise RuntimeError(
                    f"{spec.service_name} result fetch failed: status={result_code} payload={result_payload}"
                )
        else:
            result_payload = inline_result

        normalized_result_payload = unwrap_result_payload(result_payload)
        elapsed_seconds = round(time.monotonic() - run_started, 3)
        validation = spec.validation_fn(normalized_result_payload)
        run_report = {
            "run_index": overall_index - warmup_runs,
            "overall_index": overall_index,
            "is_warmup": overall_index <= warmup_runs,
            "task_id": task_id,
            "submit_status_code": submit_code,
            "final_status": parse_status(terminal_payload),
            "status_poll_count": status_poll_count,
            "elapsed_seconds": elapsed_seconds,
            "result_size_bytes": len(json.dumps(normalized_result_payload, ensure_ascii=False).encode("utf-8")),
            "validation": validation,
            "result": normalized_result_payload,
            "status_payload": terminal_payload,
        }
        if overall_index <= warmup_runs:
            report_path = service_dir / f"warmup_{overall_index:02d}.json"
        else:
            report_path = service_dir / f"run_{overall_index - warmup_runs:02d}.json"
        report_path.write_text(json.dumps(run_report, ensure_ascii=False, indent=2), encoding="utf-8")
        if overall_index > warmup_runs:
            results.append(run_report)

    elapsed_values = [item["elapsed_seconds"] for item in results]
    return {
        "service": spec.service_name,
        "input_path": spec.input_path,
        "health": health_payload,
        "runs": results,
        "summary": {
            "run_count": len(results),
            "success_count": sum(1 for item in results if item["final_status"] == "succeeded"),
            "avg_elapsed_seconds": round(statistics.mean(elapsed_values), 3) if elapsed_values else None,
            "min_elapsed_seconds": min(elapsed_values) if elapsed_values else None,
            "max_elapsed_seconds": max(elapsed_values) if elapsed_values else None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run unified multimedia QA suite.")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--services", nargs="+", default=["video-vl", "scene", "audio"])
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--warmup-runs", type=int, default=0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    parser.add_argument("--wait-seconds", type=int, default=30)
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--sample-fps", type=float, default=1.0)
    parser.add_argument("--max-frames", type=int, default=64)
    parser.add_argument("--video-vl-base-url", default=SERVICE_SPECS["video-vl"].api_base_url)
    parser.add_argument("--scene-base-url", default=SERVICE_SPECS["scene"].api_base_url)
    parser.add_argument("--audio-base-url", default=SERVICE_SPECS["audio"].api_base_url)
    parser.add_argument("--video-input", default=SERVICE_SPECS["video-vl"].input_path)
    parser.add_argument("--scene-input", default=SERVICE_SPECS["scene"].input_path)
    parser.add_argument("--audio-input", default=SERVICE_SPECS["audio"].input_path)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    ensure_dir(output_dir)

    services = args.services
    if services == ["all"]:
        services = ["video-vl", "scene", "audio"]

    spec_map = {
        "video-vl": ServiceSpec("video-vl", args.video_vl_base_url, args.video_input, validate_video_vl_result),
        "scene": ServiceSpec("scene", args.scene_base_url, args.scene_input, validate_scene_result),
        "audio": ServiceSpec("audio", args.audio_base_url, args.audio_input, validate_audio_result),
    }

    summary: dict[str, Any] = {
        "generated_at": now_iso(),
        "api_mode": "tasks_v1",
        "runs_per_service": args.runs,
        "services": {},
    }

    for service_name in services:
        spec = spec_map[service_name]
        client = build_client(
            spec,
            profile=args.profile,
            sample_fps=args.sample_fps,
            max_frames=args.max_frames,
            wait_seconds=args.wait_seconds,
        )
        summary["services"][service_name] = run_service(
            client=client,
            spec=spec,
            runs=args.runs,
            warmup_runs=args.warmup_runs,
            poll_interval_seconds=args.poll_interval_seconds,
            timeout_seconds=args.timeout_seconds,
            output_dir=output_dir,
        )

    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
