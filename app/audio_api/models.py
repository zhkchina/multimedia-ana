from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class JobCreateRequest(BaseModel):
    audio_uri: str = Field(min_length=1, description="宿主机或共享卷内的本地音频或视频文件路径")
    language: str = Field(default="auto")
    profile: str = Field(default="movie_zh")
    metadata: dict[str, Any] | None = None

    @field_validator("profile")
    @classmethod
    def validate_profile(cls, value: str) -> str:
        if value != "movie_zh":
            raise ValueError("profile 第一版仅支持 movie_zh。")
        return value


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class HealthResponse(BaseModel):
    status: str
    service: str
    worker_online: bool
    queued_jobs: int
    worker: dict | None = None
