from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.audio_worker.inference import AudioASRRunner
from app.core.logging_utils import configure_logging
from app.core.settings import Settings, get_settings
from app.core.task_store import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    claim_next_queued_task,
    ensure_runtime_dirs,
    store_task_error,
    store_task_result,
    write_worker_state,
)


class AudioWorkerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = configure_logging("multimedia_ana.audio.worker", settings.worker_log_level, settings.worker_log_file)
        self.worker_id = settings.worker_container_name
        self.runner = AudioASRRunner(settings, self.logger)
        self.last_active_at = time.monotonic()

    def _task_work_dir(self, task_id: str) -> Path:
        return self.settings.runtime_dir / "tasks" / task_id

    def _write_state(self, status: str, **extra) -> None:
        write_worker_state(
            self.settings,
            {
                "worker_id": self.worker_id,
                "status": status,
                "idle_timeout_seconds": self.settings.worker_idle_timeout_seconds,
                **extra,
            },
        )

    def _process_task(self, request: dict) -> None:
        task_id = request["task_id"]
        work_dir = self._task_work_dir(task_id)
        self._write_state(status="running", task_id=task_id)
        self.logger.info("Picked up audio task %s", task_id)
        try:
            result = self.runner.analyze(request, work_dir)
            status = store_task_result(
                self.settings,
                task_id,
                result=result,
                worker_id=self.worker_id,
            )
            self.last_active_at = time.monotonic()
            self.logger.info("Audio task %s finished successfully", task_id)
            self._write_state(status="idle", last_task=status["task_id"])
        except Exception as exc:
            store_task_error(
                self.settings,
                task_id,
                worker_id=self.worker_id,
                error={"message": str(exc)},
                status=STATUS_FAILED,
            )
            self.last_active_at = time.monotonic()
            self.logger.exception("Audio task %s failed", task_id)
            self._write_state(status="idle", last_task=task_id, last_error=str(exc))
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def run(self) -> None:
        ensure_runtime_dirs(self.settings)
        self.logger.info("Audio worker starting with idle_timeout=%ss", self.settings.worker_idle_timeout_seconds)
        self._write_state(status="starting")

        while True:
            request = claim_next_queued_task(self.settings, self.worker_id)
            if request is not None:
                self._process_task(request)
                continue

            idle_for = time.monotonic() - self.last_active_at
            self._write_state(status="idle", idle_for_seconds=int(idle_for))
            if idle_for >= self.settings.worker_idle_timeout_seconds:
                self.logger.info("Audio worker idle for %.1fs, exiting", idle_for)
                self._write_state(status="stopped", reason="idle_timeout", idle_for_seconds=int(idle_for))
                return

            time.sleep(self.settings.worker_poll_interval_seconds)


def main() -> None:
    settings = get_settings()
    worker = AudioWorkerService(settings)
    worker.run()


if __name__ == "__main__":
    main()
