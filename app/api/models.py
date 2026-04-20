from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobCreateRequest(BaseModel):
    video_uri: str = Field(min_length=1, description="宿主机或共享卷内的视频路径")
    language: str | None = None
    profile: str = Field(default="standard")
    max_frames: int = Field(default=128, ge=4, le=512)
    sample_fps: float = Field(default=1.0, gt=0.0, le=30.0)
    metadata: dict[str, Any] | None = None

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        if value not in {"draft", "standard", "deep"}:
            raise ValueError("profile 仅支持 draft / standard / deep。")
        return value


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class HealthResponse(BaseModel):
    ok: bool
    worker_online: bool
    queued_jobs: int
    worker: dict | None = None
