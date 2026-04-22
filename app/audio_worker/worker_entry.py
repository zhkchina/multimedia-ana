from __future__ import annotations

import time
from pathlib import Path

from app.audio_worker.inference import AudioASRRunner
from app.core.logging_utils import configure_logging
from app.core.settings import Settings, get_settings
from app.core.store import (
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    claim_next_queued_job,
    ensure_runtime_dirs,
    release_job_lock,
    update_job_status,
    write_worker_state,
)


class AudioWorkerService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = configure_logging("multimedia_ana.audio.worker", settings.worker_log_level, settings.worker_log_file)
        self.worker_id = settings.worker_container_name
        self.runner = AudioASRRunner(settings, self.logger)
        self.last_active_at = time.monotonic()

    def _job_output_path(self, job_id: str) -> Path:
        return self.settings.output_dir / job_id / "analysis.json"

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

    def _process_job(self, request: dict) -> None:
        job_id = request["job_id"]
        output_path = self._job_output_path(job_id)
        self._write_state(status="running", job_id=job_id)
        self.logger.info("Picked up audio job %s", job_id)
        try:
            generated_path = self.runner.analyze(request, output_path)
            status = update_job_status(
                self.settings,
                job_id,
                status=STATUS_SUCCEEDED,
                worker_id=self.worker_id,
                result_files=[str(generated_path)],
                error=None,
            )
            self.last_active_at = time.monotonic()
            self.logger.info("Audio job %s finished successfully", job_id)
            self._write_state(status="idle", last_job=status["job_id"])
        except Exception as exc:
            update_job_status(
                self.settings,
                job_id,
                status=STATUS_FAILED,
                worker_id=self.worker_id,
                result_files=[],
                error=str(exc),
            )
            self.last_active_at = time.monotonic()
            self.logger.exception("Audio job %s failed", job_id)
            self._write_state(status="idle", last_job=job_id, last_error=str(exc))
        finally:
            release_job_lock(self.settings, job_id)

    def run(self) -> None:
        ensure_runtime_dirs(self.settings)
        self.logger.info("Audio worker starting with idle_timeout=%ss", self.settings.worker_idle_timeout_seconds)
        self._write_state(status="starting")

        while True:
            request = claim_next_queued_job(self.settings, self.worker_id)
            if request is not None:
                self._process_job(request)
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
