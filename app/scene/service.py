from __future__ import annotations

import threading
import time
from pathlib import Path

from app.core.logging_utils import configure_logging
from app.core.settings import Settings
from app.core.store import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    claim_next_queued_job,
    ensure_runtime_dirs,
    list_queued_jobs,
    read_worker_state,
    release_job_lock,
    update_job_status,
    write_worker_state,
)
from app.scene.runner import VideoSceneRunner


class SceneJobService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = configure_logging("multimedia_ana.scene", settings.api_log_level, settings.api_log_file)
        self.worker_id = f"{settings.service_name}-api"
        self.runner = VideoSceneRunner(settings, self.logger)
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def _job_output_path(self, job_id: str) -> Path:
        return self.settings.output_dir / job_id / "analysis.json"

    def _write_state(self, status: str, **extra) -> None:
        write_worker_state(
            self.settings,
            {
                "worker_id": self.worker_id,
                "status": status,
                **extra,
            },
        )

    def _process_job(self, request: dict) -> None:
        job_id = request["job_id"]
        output_path = self._job_output_path(job_id)
        self._write_state(status="running", job_id=job_id)
        try:
            generated_path = self.runner.analyze(request, output_path)
            update_job_status(
                self.settings,
                job_id,
                status=STATUS_SUCCEEDED,
                worker_id=self.worker_id,
                result_files=[str(generated_path)],
                error=None,
            )
            self._write_state(status="idle", last_job=job_id)
        except Exception as exc:
            update_job_status(
                self.settings,
                job_id,
                status=STATUS_FAILED,
                worker_id=self.worker_id,
                result_files=[],
                error=str(exc),
            )
            self.logger.exception("Scene job %s failed", job_id)
            self._write_state(status="idle", last_job=job_id, last_error=str(exc))
        finally:
            release_job_lock(self.settings, job_id)

    def _run_loop(self) -> None:
        ensure_runtime_dirs(self.settings)
        self._write_state(status="starting")
        while not self._stop_event.is_set():
            request = claim_next_queued_job(self.settings, self.worker_id)
            if request is None:
                self._write_state(status="idle", queued_jobs=len(list_queued_jobs(self.settings)))
                time.sleep(1)
                continue
            self._process_job(request)
        self._write_state(status="stopped", reason="shutdown")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="video-scene-job-loop", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def health_payload(self) -> dict:
        runtime_state = read_worker_state(self.settings)
        return {
            "ok": True,
            "worker_online": self._thread is not None and self._thread.is_alive(),
            "queued_jobs": len(list_queued_jobs(self.settings)),
            "worker": {
                "exists": True,
                "running": self._thread is not None and self._thread.is_alive(),
                "status": "running" if self._thread is not None and self._thread.is_alive() else "stopped",
                "container_name": self.settings.service_name,
                "image": "multimedia-ana-video-scene:local",
                "runtime": runtime_state,
            },
        }
