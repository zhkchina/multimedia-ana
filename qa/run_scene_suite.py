from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
FINAL_STATUSES = {"succeeded", "failed"}


@dataclass
class VideoRunResult:
    video_path: str
    video_name: str
    output_dir: str
    job_id: str | None
    submit_status_code: int | None
    final_status: str
    status_poll_count: int
    elapsed_seconds: float
    scene_count: int
    image_count: int
    result_json: str | None
    report_json: str
    error: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_videos(video_dir: Path) -> list[Path]:
    return sorted(path for path in video_dir.rglob("*") if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8")
            return response.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body) if body else {}
        except Exception:
            parsed = {"detail": body}
        return exc.code, parsed


def request_bytes(url: str) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def healthcheck(api_base_url: str) -> dict[str, Any]:
    status_code, payload = request_json(f"{api_base_url.rstrip('/')}/health")
    if status_code != 200:
        raise RuntimeError(f"health check failed: status={status_code} payload={payload}")
    return payload


def submit_job(
    api_base_url: str,
    video_path: Path,
    profile: str,
    threshold: float,
    min_scene_len: str,
    save_image_count: int,
) -> tuple[int, dict[str, Any]]:
    payload = {
        "video_uri": str(video_path),
        "profile": profile,
        "threshold": threshold,
        "min_scene_len": min_scene_len,
        "save_image_count": save_image_count,
    }
    return request_json(f"{api_base_url.rstrip('/')}/jobs", method="POST", payload=payload)


def poll_job(api_base_url: str, job_id: str, poll_interval_seconds: float, timeout_seconds: float) -> tuple[dict[str, Any], int]:
    deadline = time.monotonic() + timeout_seconds
    poll_count = 0
    while True:
        poll_count += 1
        status_code, payload = request_json(f"{api_base_url.rstrip('/')}/jobs/{job_id}")
        if status_code != 200:
            raise RuntimeError(f"job status request failed: status={status_code} payload={payload}")
        if payload.get("status") in FINAL_STATUSES:
            return payload, poll_count
        if time.monotonic() >= deadline:
            raise TimeoutError(f"job {job_id} did not finish within {timeout_seconds} seconds")
        time.sleep(poll_interval_seconds)


def download_result(api_base_url: str, job_id: str, target_path: Path) -> dict[str, Any]:
    url = f"{api_base_url.rstrip('/')}/jobs/{urllib.parse.quote(job_id)}/result?download=true"
    status_code, payload = request_bytes(url)
    if status_code != 200:
        raise RuntimeError(f"result download failed: status={status_code} payload={payload.decode('utf-8', errors='replace')}")
    target_path.write_bytes(payload)
    return json.loads(payload.decode("utf-8"))


def run_single_video(
    api_base_url: str,
    video_path: Path,
    output_dir: Path,
    profile: str,
    threshold: float,
    min_scene_len: str,
    save_image_count: int,
    poll_interval_seconds: float,
    timeout_seconds: float,
) -> VideoRunResult:
    video_output_dir = output_dir / video_path.stem
    video_output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.monotonic()

    submit_status_code, submit_payload = submit_job(
        api_base_url=api_base_url,
        video_path=video_path,
        profile=profile,
        threshold=threshold,
        min_scene_len=min_scene_len,
        save_image_count=save_image_count,
    )
    job_id = submit_payload.get("job_id")
    if submit_status_code != 200 or not job_id:
        error = f"submit failed: status={submit_status_code} payload={submit_payload}"
        report_json = video_output_dir / "scene_report.json"
        write_json(
            report_json,
            {
                "video_path": str(video_path),
                "video_name": video_path.name,
                "output_dir": str(video_output_dir),
                "job_id": job_id,
                "submit_status_code": submit_status_code,
                "submit_payload": submit_payload,
                "final_status": "failed",
                "error": error,
                "finished_at": now_iso(),
            },
        )
        return VideoRunResult(
            video_path=str(video_path),
            video_name=video_path.name,
            output_dir=str(video_output_dir),
            job_id=job_id,
            submit_status_code=submit_status_code,
            final_status="failed",
            status_poll_count=0,
            elapsed_seconds=time.monotonic() - started_at,
            scene_count=0,
            image_count=0,
            result_json=None,
            report_json=str(report_json),
            error=error,
        )

    status_payload, poll_count = poll_job(
        api_base_url=api_base_url,
        job_id=job_id,
        poll_interval_seconds=poll_interval_seconds,
        timeout_seconds=timeout_seconds,
    )

    result_json_path: Path | None = None
    result_payload: dict[str, Any] | None = None
    error: str | None = None
    if status_payload.get("status") == "succeeded":
        result_json_path = video_output_dir / "analysis.json"
        result_payload = download_result(api_base_url, job_id, result_json_path)
    else:
        error = status_payload.get("error") or "job failed without error message"

    scene_count = len(result_payload.get("scenes", [])) if result_payload else 0
    image_count = len(result_payload.get("image_files", [])) if result_payload else 0
    elapsed_seconds = time.monotonic() - started_at

    report = {
        "video_path": str(video_path),
        "video_name": video_path.name,
        "output_dir": str(video_output_dir),
        "job_id": job_id,
        "submit_status_code": submit_status_code,
        "submit_payload": submit_payload,
        "final_status": status_payload.get("status", "failed"),
        "status_poll_count": poll_count,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "scene_count": scene_count,
        "image_count": image_count,
        "result_json": str(result_json_path) if result_json_path else None,
        "status_payload": status_payload,
        "error": error,
        "finished_at": now_iso(),
    }
    report_json = video_output_dir / "scene_report.json"
    write_json(report_json, report)

    return VideoRunResult(
        video_path=str(video_path),
        video_name=video_path.name,
        output_dir=str(video_output_dir),
        job_id=job_id,
        submit_status_code=submit_status_code,
        final_status=status_payload.get("status", "failed"),
        status_poll_count=poll_count,
        elapsed_seconds=elapsed_seconds,
        scene_count=scene_count,
        image_count=image_count,
        result_json=str(result_json_path) if result_json_path else None,
        report_json=str(report_json),
        error=error,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run video-scene API QA over a directory of videos.")
    parser.add_argument("--video-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--profile", default="standard")
    parser.add_argument("--threshold", type=float, default=27.0)
    parser.add_argument("--min-scene-len", default="0.6s")
    parser.add_argument("--save-image-count", type=int, default=3)
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=3600.0)
    args = parser.parse_args()

    video_dir = Path(args.video_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "generated_at": now_iso(),
        "video_dir": str(video_dir),
        "api_base_url": args.api_base_url,
        "profile": args.profile,
        "threshold": args.threshold,
        "min_scene_len": args.min_scene_len,
        "save_image_count": args.save_image_count,
        "poll_interval_seconds": args.poll_interval_seconds,
        "timeout_seconds": args.timeout_seconds,
    }
    try:
        health = healthcheck(args.api_base_url)
        manifest["health"] = health
    except Exception as exc:
        manifest["health_error"] = str(exc)
        write_json(output_dir / "manifest.json", manifest)
        write_json(
            output_dir / "summary.json",
            {
                "generated_at": now_iso(),
                "status": "failed",
                "run_dir": str(output_dir),
                "video_dir": str(video_dir),
                "api_base_url": args.api_base_url,
                "reason": f"health check failed: {exc}",
            },
        )
        return 1

    videos = find_videos(video_dir)
    manifest["video_count"] = len(videos)
    manifest["videos"] = [str(path) for path in videos]
    write_json(output_dir / "manifest.json", manifest)

    if not videos:
        write_json(
            output_dir / "summary.json",
            {
                "generated_at": now_iso(),
                "status": "failed",
                "reason": f"no video files found under {video_dir}",
                "health": health,
            },
        )
        return 1

    results: list[VideoRunResult] = []
    for video_path in videos:
        results.append(
            run_single_video(
                api_base_url=args.api_base_url,
                video_path=video_path,
                output_dir=output_dir,
                profile=args.profile,
                threshold=args.threshold,
                min_scene_len=args.min_scene_len,
                save_image_count=args.save_image_count,
                poll_interval_seconds=args.poll_interval_seconds,
                timeout_seconds=args.timeout_seconds,
            )
        )

    succeeded = [result for result in results if result.final_status == "succeeded"]
    failed = [result for result in results if result.final_status != "succeeded"]
    summary = {
        "generated_at": now_iso(),
        "status": "succeeded" if not failed else "partial_failed",
        "video_dir": str(video_dir),
        "run_dir": str(output_dir),
        "api_base_url": args.api_base_url,
        "video_count": len(results),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "total_scene_count": sum(result.scene_count for result in results),
        "total_image_count": sum(result.image_count for result in results),
        "total_elapsed_seconds": round(sum(result.elapsed_seconds for result in results), 3),
        "health": health,
        "results": [result.__dict__ for result in results],
    }
    write_json(output_dir / "summary.json", summary)
    return 0 if not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
