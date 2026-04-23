from __future__ import annotations

import threading
from typing import Any

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.types import DeviceRequest

from app.core.logging_utils import configure_logging
from app.core.settings import Settings


class WorkerScheduler:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.logger = configure_logging("multimedia_ana.scheduler", settings.api_log_level, settings.scheduler_log_file)
        self._lock = threading.Lock()
        self._client = docker.from_env()

    def _container(self):
        try:
            return self._client.containers.get(self.settings.worker_container_name)
        except NotFound:
            return None

    def worker_status(self) -> dict[str, Any]:
        container = self._container()
        if container is None:
            return {
                "exists": False,
                "running": False,
                "status": "missing",
                "container_name": self.settings.worker_container_name,
                "image": self.settings.worker_image,
            }
        container.reload()
        return {
            "exists": True,
            "running": container.status == "running",
            "status": container.status,
            "container_name": container.name,
            "image": self.settings.worker_image,
            "started_at": container.attrs["State"].get("StartedAt"),
            "finished_at": container.attrs["State"].get("FinishedAt"),
        }

    def ensure_worker(self) -> dict[str, Any]:
        with self._lock:
            container = self._container()
            if container is not None:
                container.reload()
                if container.status == "running":
                    return self.worker_status()
                self.logger.info("Removing stale worker container with status=%s", container.status)
                container.remove(force=True)

            self.logger.info("Starting worker container from image %s", self.settings.worker_image)
            # 注意：这里是通过 Docker SDK 动态拉起 worker，不会自动继承 docker-compose.yml
            # 里 video-vl-worker service 的 volumes/environment/shm_size/user/network 等配置。
            # 如果 docker-compose.yml 中的 worker 配置有调整，必须同步修改这里的 kwargs。
            # 另外，修改动态 worker 的代码、镜像或运行参数后，要先删除旧的
            # multimedia-ana-video-vl-worker 容器；否则后续请求可能继续复用旧 worker。
            kwargs: dict[str, Any] = {
                "image": self.settings.worker_image,
                "name": self.settings.worker_container_name,
                "network": self.settings.worker_network_name,
                "command": ["python3", "-m", "app.worker.worker_entry"],
                "detach": True,
                "shm_size": self.settings.worker_shm_size,
                "user": f"{self.settings.host_uid}:{self.settings.host_gid}",
                "environment": {
                    "DATA_ROOT": str(self.settings.data_root),
                    "HOME": str(self.settings.cache_dir / "home"),
                    "USER": "kun",
                    "LOGNAME": "kun",
                    "SERVICE_NAME": self.settings.service_name,
                    "WORKER_CONTAINER_NAME": self.settings.worker_container_name,
                    "WORKER_NETWORK_NAME": self.settings.worker_network_name,
                    "HOST_UID": str(self.settings.host_uid),
                    "HOST_GID": str(self.settings.host_gid),
                    "WORKER_IDLE_TIMEOUT_SECONDS": str(self.settings.worker_idle_timeout_seconds),
                    "WORKER_POLL_INTERVAL_SECONDS": str(self.settings.worker_poll_interval_seconds),
                    "VIDEO_VL_MODEL_ID": self.settings.video_vl_model_id,
                    "HF_HOME": str(self.settings.cache_dir / "huggingface"),
                    "WORKER_LOG_LEVEL": self.settings.worker_log_level,
                },
                "volumes": {
                    str(self.settings.host_project_dir): {"bind": "/workspace", "mode": "ro"},
                    str(self.settings.data_root): {"bind": str(self.settings.data_root), "mode": "rw"},
                    "/data/assets": {"bind": "/data/assets", "mode": "ro"},
                },
                "restart_policy": {"Name": "no"},
            }
            kwargs["device_requests"] = [DeviceRequest(count=-1, capabilities=[["gpu"]])]

            try:
                self._client.containers.run(**kwargs)
            except ImageNotFound as exc:
                raise RuntimeError(
                    f"worker image 不存在: {self.settings.worker_image}。"
                    "请先执行 `docker compose build video-vl-worker` 或 `docker compose build`。"
                ) from exc
            return self.worker_status()

    def shutdown_worker(self) -> dict[str, Any]:
        with self._lock:
            container = self._container()
            if container is None:
                return self.worker_status()
            self.logger.info("Stopping worker container %s", container.name)
            container.remove(force=True)
            return self.worker_status()

    def ping(self) -> bool:
        try:
            self._client.ping()
            return True
        except DockerException:
            self.logger.exception("Failed to talk to Docker daemon")
            return False
