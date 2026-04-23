from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.core.logging_utils import configure_logging
from app.core.settings import Settings, get_settings
from app.core.task_store import FINAL_STATUSES, create_task, ensure_runtime_dirs, get_task, wait_for_task
from app.scene.models import HealthResponse, TaskCreateRequest
from app.scene.service import SceneJobService

settings: Settings = get_settings()
logger = configure_logging("multimedia_ana.scene_api", settings.api_log_level, settings.api_log_file)
service = SceneJobService(settings)
app = FastAPI(title="Video Scene API", version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs(settings)
    service.start()
    logger.info("Video-scene API started on port %s", settings.api_port)


@app.on_event("shutdown")
def shutdown() -> None:
    service.stop()


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
    return HealthResponse(**service.health_payload())


@app.get("/readyz")
def ready() -> dict:
    return {"status": "ok", "service": settings.service_name}


@app.post("/v1/tasks")
def create_scene_task(payload: TaskCreateRequest):
    ensure_runtime_dirs(settings)
    video_path = Path(payload.input.file_uri)
    if not video_path.exists():
        raise HTTPException(status_code=400, detail=f"file_uri 不存在: {video_path}")

    request_payload = payload.input.model_dump(mode="json")
    request_id = (payload.metadata or {}).get("request_id") if payload.metadata else None
    task = create_task(settings, request_payload=request_payload, request_id=request_id)
    logger.info("Created scene task %s for %s", task["task_id"], video_path)

    wait_seconds = payload.options.wait_seconds
    if wait_seconds > 0:
        current = wait_for_task(settings, task["task_id"], wait_seconds)
        if current["status"] in FINAL_STATUSES:
            if current["status"] == "succeeded":
                return _task_result_payload(current)
            return _task_status_payload(current)
    return JSONResponse(status_code=202, content=_task_status_payload(task), headers={"Retry-After": "5"})


@app.get("/v1/tasks/{task_id}")
def get_scene_task(task_id: str) -> dict:
    try:
        task = get_task(settings, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task 不存在: {task_id}") from exc
    return _task_status_payload(task)


@app.get("/v1/tasks/{task_id}/result")
def get_scene_task_result(task_id: str):
    try:
        task = get_task(settings, task_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"task 不存在: {task_id}") from exc

    if task["status"] not in FINAL_STATUSES:
        return JSONResponse(status_code=202, content=_task_status_payload(task), headers={"Retry-After": "5"})
    if task["status"] != "succeeded":
        return JSONResponse(status_code=409, content=_task_status_payload(task))
    return _task_result_payload(task)
