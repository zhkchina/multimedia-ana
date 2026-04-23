from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value is not None else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return float(value) if value is not None else default


@dataclass(frozen=True)
class Settings:
    app_title: str = os.getenv("APP_TITLE", "Multimedia Analysis API")
    api_port: int = _env_int("API_PORT", 7860)
    api_log_level: str = os.getenv("API_LOG_LEVEL", "INFO")
    worker_log_level: str = os.getenv("WORKER_LOG_LEVEL", "INFO")
    host_uid: int = _env_int("HOST_UID", 1000)
    host_gid: int = _env_int("HOST_GID", 1000)
    docker_gid: int = _env_int("DOCKER_GID", 999)
    host_project_dir: Path = Path(os.getenv("HOST_PROJECT_DIR", "/home/kun/tools/multimedia-ana"))
    data_root: Path = Path(os.getenv("DATA_ROOT", "/data/multimedia-ana"))
    service_name: str = os.getenv("SERVICE_NAME", "video-vl")
    worker_image: str = os.getenv("WORKER_IMAGE", "multimedia-ana-video-vl-worker:local")
    worker_container_name: str = os.getenv("WORKER_CONTAINER_NAME", "multimedia-ana-video-vl-worker")
    worker_network_name: str = os.getenv("WORKER_NETWORK_NAME", "multimedia-ana_default")
    worker_idle_timeout_seconds: int = _env_int("WORKER_IDLE_TIMEOUT_SECONDS", 1800)
    worker_poll_interval_seconds: int = _env_int("WORKER_POLL_INTERVAL_SECONDS", 3)
    worker_shm_size: str = os.getenv("WORKER_SHM_SIZE", "16g")
    video_vl_model_id: str = os.getenv("VIDEO_VL_MODEL_ID", "Qwen/Qwen3-VL-8B-Instruct")
    audio_model_id: str = os.getenv("AUDIO_MODEL_ID", "iic/SenseVoiceSmall")
    audio_vad_model_id: str = os.getenv("AUDIO_VAD_MODEL_ID", "fsmn-vad")
    audio_device: str = os.getenv("AUDIO_DEVICE", "cuda:0")
    task_result_ttl_hours: int = _env_int("TASK_RESULT_TTL_HOURS", 24)
    task_wait_poll_interval_seconds: float = _env_float("TASK_WAIT_POLL_INTERVAL_SECONDS", 0.5)
    video_vl_default_max_output_tokens: int = _env_int("VIDEO_VL_DEFAULT_MAX_OUTPUT_TOKENS", 1024)
    video_vl_default_temperature: float = _env_float("VIDEO_VL_DEFAULT_TEMPERATURE", 0.7)
    video_vl_default_top_p: float = _env_float("VIDEO_VL_DEFAULT_TOP_P", 0.8)
    video_vl_transformers_max_frames: int = 64
    video_vl_transformers_min_pixels: int = 4 * 32 * 32
    video_vl_transformers_max_pixels: int = 256 * 32 * 32
    video_vl_transformers_total_pixels: int = 20480 * 32 * 32
    video_vl_use_flash_attention_2: bool = True

    @property
    def service_root(self) -> Path:
        return self.data_root / self.service_name

    @property
    def jobs_dir(self) -> Path:
        return self.service_root / "jobs"

    @property
    def output_dir(self) -> Path:
        return self.service_root / "output"

    @property
    def logs_dir(self) -> Path:
        return self.service_root / "logs"

    @property
    def runtime_dir(self) -> Path:
        return self.service_root / "runtime"

    @property
    def tasks_db_path(self) -> Path:
        return self.runtime_dir / "tasks.db"

    @property
    def cache_dir(self) -> Path:
        return self.service_root / "cache"

    @property
    def worker_state_file(self) -> Path:
        return self.runtime_dir / "worker_state.json"

    @property
    def job_lock_dir(self) -> Path:
        return self.runtime_dir / "locks"

    @property
    def api_log_file(self) -> Path:
        return self.logs_dir / "api.log"

    @property
    def scheduler_log_file(self) -> Path:
        return self.logs_dir / "scheduler.log"

    @property
    def worker_log_file(self) -> Path:
        return self.logs_dir / "worker.log"


def get_settings() -> Settings:
    return Settings()
