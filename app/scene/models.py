from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class SceneJobCreateRequest(BaseModel):
    video_uri: str = Field(min_length=1, description="宿主机或共享卷内的视频路径")
    profile: str = Field(default="standard")
    min_scene_len: str = Field(default="0.6s")
    threshold: float = Field(default=27.0, ge=0.0, le=255.0)
    save_image_count: int = Field(default=3, ge=0, le=10)
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
