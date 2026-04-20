from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.settings import Settings


STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
FINAL_STATUSES = {STATUS_SUCCEEDED, STATUS_FAILED}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_runtime_dirs(settings: Settings) -> None:
    for path in (
        settings.data_root,
        settings.service_root,
        settings.jobs_dir,
        settings.output_dir,
        settings.logs_dir,
        settings.runtime_dir,
        settings.cache_dir,
        settings.job_lock_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def create_job(settings: Settings, request_payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    job_id = f"job_{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    created_at = now_iso()
    job_dir = settings.jobs_dir / job_id
    output_dir = settings.output_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=True)

    request = {
        "job_id": job_id,
        "submitted_at": created_at,
        **request_payload,
    }
    status = {
        "job_id": job_id,
        "status": STATUS_QUEUED,
        "created_at": created_at,
        "updated_at": created_at,
        "worker_id": None,
        "result_files": [],
        "error": None,
    }
    _atomic_write_json(job_dir / "request.json", request)
    _atomic_write_json(job_dir / "status.json", status)
    return job_id, status


def get_job_dir(settings: Settings, job_id: str) -> Path:
    return settings.jobs_dir / job_id


def get_job_request(settings: Settings, job_id: str) -> dict[str, Any]:
    return _read_json(get_job_dir(settings, job_id) / "request.json")


def get_job_status(settings: Settings, job_id: str) -> dict[str, Any]:
    return _read_json(get_job_dir(settings, job_id) / "status.json")


def update_job_status(
    settings: Settings,
    job_id: str,
    *,
    status: str,
    worker_id: str | None = None,
    result_files: list[str] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    status_path = get_job_dir(settings, job_id) / "status.json"
    current = _read_json(status_path)
    current["status"] = status
    current["updated_at"] = now_iso()
    if worker_id is not None:
        current["worker_id"] = worker_id
    if result_files is not None:
        current["result_files"] = result_files
    current["error"] = error
    _atomic_write_json(status_path, current)
    return current


def list_jobs(settings: Settings) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not settings.jobs_dir.exists():
        return items
    for job_dir in sorted((path for path in settings.jobs_dir.iterdir() if path.is_dir()), key=lambda item: item.name):
        status_path = job_dir / "status.json"
        if status_path.exists():
            items.append(_read_json(status_path))
    return items


def list_queued_jobs(settings: Settings) -> list[dict[str, Any]]:
    return [item for item in list_jobs(settings) if item["status"] == STATUS_QUEUED]


def _job_lock_path(settings: Settings, job_id: str) -> Path:
    return settings.job_lock_dir / f"{job_id}.lock"


def acquire_job_lock(settings: Settings, job_id: str) -> bool:
    lock_path = _job_lock_path(settings, job_id)
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(now_iso())
    return True


def release_job_lock(settings: Settings, job_id: str) -> None:
    lock_path = _job_lock_path(settings, job_id)
    if lock_path.exists():
        lock_path.unlink()


def claim_next_queued_job(settings: Settings, worker_id: str) -> dict[str, Any] | None:
    for item in list_queued_jobs(settings):
        job_id = item["job_id"]
        if not acquire_job_lock(settings, job_id):
            continue
        try:
            current = get_job_status(settings, job_id)
            if current["status"] != STATUS_QUEUED:
                release_job_lock(settings, job_id)
                continue
            update_job_status(settings, job_id, status=STATUS_RUNNING, worker_id=worker_id)
            request = get_job_request(settings, job_id)
            request["_status"] = get_job_status(settings, job_id)
            return request
        except Exception:
            release_job_lock(settings, job_id)
            raise
    return None


def write_worker_state(settings: Settings, payload: dict[str, Any]) -> None:
    _atomic_write_json(settings.worker_state_file, {"updated_at": now_iso(), **payload})


def read_worker_state(settings: Settings) -> dict[str, Any] | None:
    if not settings.worker_state_file.exists():
        return None
    return _read_json(settings.worker_state_file)
