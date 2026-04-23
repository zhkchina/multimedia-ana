from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class Message(BaseModel):
    role: Literal["system", "user", "assistant"] = "user"
    content: Any


class TaskOptions(BaseModel):
    wait_seconds: int = Field(default=0, ge=0, le=3600)


class FileTaskInput(BaseModel):
    file_uri: str = Field(min_length=1, description="宿主机或共享卷内的单文件路径")
    messages: list[Message] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("params 必须是 JSON 对象。")
        return value


class TaskCreateRequest(BaseModel):
    input: FileTaskInput
    options: TaskOptions = Field(default_factory=TaskOptions)
    metadata: dict[str, Any] | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    worker_online: bool
    queued_tasks: int
    worker: dict | None = None
