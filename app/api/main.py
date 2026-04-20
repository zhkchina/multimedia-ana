from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse

from app.api.models import HealthResponse, JobCreateRequest, JobCreateResponse
from app.api.scheduler import WorkerScheduler
from app.core.logging_utils import configure_logging
from app.core.settings import Settings, get_settings
from app.core.store import FINAL_STATUSES, create_job, ensure_runtime_dirs, get_job_status, list_queued_jobs, read_worker_state

settings: Settings = get_settings()
logger = configure_logging("multimedia_ana.api", settings.api_log_level, settings.api_log_file)
scheduler = WorkerScheduler(settings)
app = FastAPI(title=settings.app_title, version="0.1.0")


@app.on_event("startup")
def startup() -> None:
    ensure_runtime_dirs(settings)
    logger.info("API server started on port %s", settings.api_port)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    ensure_runtime_dirs(settings)
    worker_status = scheduler.worker_status()
    runtime_state = read_worker_state(settings)
    return HealthResponse(
        ok=True,
        worker_online=worker_status["running"],
        queued_jobs=len(list_queued_jobs(settings)),
        worker={**worker_status, "runtime": runtime_state},
    )


@app.post("/jobs", response_model=JobCreateResponse)
def submit_job(payload: JobCreateRequest) -> JobCreateResponse:
    ensure_runtime_dirs(settings)
    video_path = Path(payload.video_uri)
    if not video_path.exists():
        raise HTTPException(status_code=400, detail=f"video_uri 不存在: {video_path}")

    request_payload = payload.model_dump(mode="json")

    job_id, status = create_job(settings, request_payload)
    logger.info("Created job %s for %s", job_id, video_path)

    if not scheduler.ping():
        raise HTTPException(status_code=500, detail="Docker daemon 不可用，无法启动 worker。")

    try:
        scheduler.ensure_worker()
    except Exception as exc:
        logger.exception("Failed to ensure worker for job %s", job_id)
        raise HTTPException(status_code=500, detail=f"启动 worker 失败: {exc}") from exc

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
