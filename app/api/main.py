from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.api.models import HealthResponse, TaskCreateRequest
from app.api.scheduler import WorkerScheduler
from app.core.logging_utils import configure_logging
from app.core.settings import Settings, get_settings
from app.core.task_store import (
    FINAL_STATUSES,
    count_queued_tasks,
    create_task,
    ensure_runtime_dirs,
    get_task,
    read_worker_state,
    wait_for_task,
)

settings: Settings = get_settings()
logger = configure_logging("multimedia_ana.api", settings.api_log_level, settings.api_log_file)
scheduler = WorkerScheduler(settings)
app = FastAPI(title=settings.app_title, version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs(settings)
    logger.info("API server started on port %s", settings.api_port)


def _task_status_payload(task: dict) -> dict:
    return {
        "id": task["task_id"],
        "service": task["service"],
        "status": task["status"],
        "created_at": task["created_at"],
        "started_at": task["started_at"],
        "finished_at": task["finished_at"],
        "updated_at": task["updated_at"],
        "expires_at": task["expires_at"],
        "error": task["error"],
    }


def _task_result_payload(task: dict) -> dict:
    return {
        "id": task["task_id"],
        "service": task["service"],
        "status": task["status"],
        "result": task["result"],
    }


@app.get("/health", response_model=HealthResponse)
@app.get("/healthz", response_model=HealthResponse)
def health() -> HealthResponse:
    ensure_runtime_dirs(settings)
    worker_status = scheduler.worker_status()
    runtime_state = read_worker_state(settings)
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        worker_online=worker_status["running"],
        queued_tasks=count_queued_tasks(settings),
        worker={**worker_status, "runtime": runtime_state},
    )


@app.get("/readyz")
def ready() -> dict:
    return {"status": "ok", "service": settings.service_name, "docker_ok": scheduler.ping()}


@app.post("/v1/tasks")
def create_video_task(payload: TaskCreateRequest) -> JSONResponse:
    ensure_runtime_dirs(settings)
    video_path = Path(payload.input.file_uri)
    if not video_path.exists():
        raise HTTPException(status_code=400, detail=f"file_uri 不存在: {video_path}")

    request_payload = payload.input.model_dump(mode="json")
    request_id = (payload.metadata or {}).get("request_id") if payload.metadata else None
    task = create_task(settings, request_payload=request_payload, request_id=request_id)
    logger.info("Created task %s for %s", task["task_id"], video_path)

    if not scheduler.ping():
        raise HTTPException(status_code=500, detail="Docker daemon 不可用，无法启动 worker。")

    try:
        scheduler.ensure_worker()
    except Exception as exc:
        logger.exception("Failed to ensure worker for task %s", task["task_id"])
        raise HTTPException(status_code=500, detail=f"启动 worker 失败: {exc}") from exc

    wait_seconds = payload.options.wait_seconds
    if wait_seconds > 0:
        current = wait_for_task(settings, task["task_id"], wait_seconds)
        if current["status"] in FINAL_STATUSES:
            if current["status"] == "succeeded":
                return JSONResponse(status_code=200, content=_task_result_payload(current))
            return JSONResponse(status_code=200, content=_task_status_payload(current))

    headers = {"Retry-After": "5"}
    return JSONResponse(status_code=202, content=_task_status_payload(task), headers=headers)


@app.get("/v1/tasks/{task_id}")
def get_video_task(task_id: str) -> dict:
    try:
        task = get_task(settings, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task 不存在: {task_id}") from exc
    return _task_status_payload(task)


@app.get("/v1/tasks/{task_id}/result")
def get_video_task_result(task_id: str) -> JSONResponse:
    try:
        task = get_task(settings, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task 不存在: {task_id}") from exc

    if task["status"] not in FINAL_STATUSES:
        return JSONResponse(status_code=202, content=_task_status_payload(task), headers={"Retry-After": "5"})
    if task["status"] != "succeeded":
        return JSONResponse(status_code=409, content=_task_status_payload(task))
    return JSONResponse(status_code=200, content=_task_result_payload(task))


@app.post("/admin/worker/wakeup")
def wakeup_worker() -> dict:
    if not scheduler.ping():
        raise HTTPException(status_code=500, detail="Docker daemon 不可用。")
    try:
        return scheduler.ensure_worker()
    except Exception as exc:
        logger.exception("Failed to wake up worker")
        raise HTTPException(status_code=500, detail=f"启动 worker 失败: {exc}") from exc


@app.post("/admin/worker/shutdown")
def shutdown_worker() -> dict:
    try:
        return scheduler.shutdown_worker()
    except Exception as exc:
        logger.exception("Failed to stop worker")
        raise HTTPException(status_code=500, detail=f"关闭 worker 失败: {exc}") from exc
