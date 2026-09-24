from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

STAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
MEDIA_PATH_PATTERN = re.compile(r"^live/stage-([a-zA-Z0-9_-]{1,64})$")
LANG_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")


def utc_now() -> datetime:
    return datetime.now(UTC)


def stage_id_from_path(path: str) -> str | None:
    match = MEDIA_PATH_PATTERN.fullmatch(path)
    return match.group(1) if match else None


class CaptionMetrics(BaseModel):
    network_ms: float | None = Field(default=None, ge=0)
    inference_ms: float | None = Field(default=None, ge=0)


class StreamEvent(BaseModel):
    type: Literal[
        "draft",
        "commit",
        "vad_start",
        "vad_end",
        "stream_started",
        "stream_stopped",
        "worker_error",
    ]
    text: str | None = None
    seq: int | None = None
    is_clause_end: bool = False
    emitted_at: datetime = Field(default_factory=utc_now)
    metrics: CaptionMetrics | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class CaptureRegistration(BaseModel):
    node_id: str = Field(min_length=1, max_length=128)
    stage_id: str
    hostname: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=512)
    version: str = "dev"

    @field_validator("stage_id")
    @classmethod
    def valid_stage_id(cls, value: str) -> str:
        if not STAGE_ID_PATTERN.fullmatch(value):
            raise ValueError("invalid stage id")
        return value


class CaptureHeartbeat(BaseModel):
    stage_id: str
    rtt_ms: float | None = Field(default=None, ge=0)
    ffmpeg_alive: bool = True
    bytes_sent: int | None = Field(default=None, ge=0)


class WorkerHeartbeat(BaseModel):
    pid: int
    state: Literal["starting", "listening", "speech", "degraded", "failed"]
    audio_seen_at: datetime | None = None
    ffmpeg_alive: bool = True
    error: str | None = None
    inference_ms: float | None = Field(default=None, ge=0)
    vad_backlog_ms: float = Field(default=0, ge=0)
    redis_publish_ms: float | None = Field(default=None, ge=0)
    segments_published: int = Field(default=0, ge=0)
    ffmpeg_restarts: int = Field(default=0, ge=0)
    audio_samples: int = Field(default=0, ge=0)


class StageContext(BaseModel):
    id: str
    name: str
    session: str = ""
    languages: list[str] = Field(default_factory=lambda: ["es"])
    glossary: list[str] = Field(default_factory=list)
    speakers: list[dict[str, Any]] = Field(default_factory=list)
