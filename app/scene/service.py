from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from app.core.logging_utils import configure_logging
from app.core.settings import Settings
from app.core.task_store import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    claim_next_queued_task,
    count_queued_tasks,
    ensure_runtime_dirs,
    read_worker_state,
    store_task_error,
    store_task_result,
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

    def _task_work_dir(self, task_id: str) -> Path:
        return self.settings.runtime_dir / "tasks" / task_id

    def _write_state(self, status: str, **extra) -> None:
        write_worker_state(
            self.settings,
            {
                "worker_id": self.worker_id,
                "status": status,
                **extra,
            },
        )

    def _process_task(self, request: dict) -> None:
        task_id = request["task_id"]
        work_dir = self._task_work_dir(task_id)
        self._write_state(status="running", task_id=task_id)
        try:
            result = self.runner.analyze(request, work_dir)
            store_task_result(
                self.settings,
                task_id,
                result=result,
                worker_id=self.worker_id,
            )
            self._write_state(status="idle", last_task=task_id)
        except Exception as exc:
            store_task_error(
                self.settings,
                task_id,
                worker_id=self.worker_id,
                error={"message": str(exc)},
                status=STATUS_FAILED,
            )
            self.logger.exception("Scene task %s failed", task_id)
            self._write_state(status="idle", last_task=task_id, last_error=str(exc))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _run_loop(self) -> None:
        ensure_runtime_dirs(self.settings)
        self._write_state(status="starting")
        while not self._stop_event.is_set():
            request = claim_next_queued_task(self.settings, self.worker_id)
            if request is None:
                self._write_state(status="idle", queued_tasks=count_queued_tasks(self.settings))
                time.sleep(1)
                continue
            self._process_task(request)
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
            "status": "ok",
            "service": self.settings.service_name,
            "worker_online": self._thread is not None and self._thread.is_alive(),
            "queued_tasks": count_queued_tasks(self.settings),
            "worker": {
                "exists": True,
                "running": self._thread is not None and self._thread.is_alive(),
                "status": "running" if self._thread is not None and self._thread.is_alive() else "stopped",
                "container_name": self.settings.service_name,
                "image": "multimedia-ana-video-scene:local",
                "runtime": runtime_state,
            },
        }
