from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse

from app.core.logging_utils import configure_logging
from app.core.settings import Settings, get_settings
from app.core.store import FINAL_STATUSES, create_job, ensure_runtime_dirs, get_job_status
from app.scene.models import HealthResponse, JobCreateResponse, SceneJobCreateRequest
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


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ensure_runtime_dirs(settings)
    return HealthResponse(**service.health_payload())


@app.post("/jobs", response_model=JobCreateResponse)
def submit_job(payload: SceneJobCreateRequest) -> JobCreateResponse:
    ensure_runtime_dirs(settings)
    video_path = Path(payload.video_uri)
    if not video_path.exists():
        raise HTTPException(status_code=400, detail=f"video_uri 不存在: {video_path}")

    job_id, status = create_job(settings, payload.model_dump(mode="json"))
    logger.info("Created scene job %s for %s", job_id, video_path)
    return JobCreateResponse(job_id=job_id, status=status["status"])


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return get_job_status(settings, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}") from exc


@app.get("/jobs/{job_id}/result", response_model=None)
def get_job_result(job_id: str, download: bool = Query(default=False)) -> Response | dict:
    try:
        status = get_job_status(settings, job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"job 不存在: {job_id}") from exc

    if status["status"] not in FINAL_STATUSES:
        return JSONResponse(status_code=202, content=status)
    if status["status"] != "succeeded":
        return JSONResponse(status_code=409, content=status)

    result_files = status.get("result_files") or []
    if not result_files:
        raise HTTPException(status_code=404, detail="任务已完成，但未找到结果文件。")

    target = Path(result_files[0])
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"结果文件不存在: {target}")

    if download:
        return FileResponse(target, media_type="application/json", filename=target.name)
    return status
