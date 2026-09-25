from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TranscriberSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "nerdearla-transcriber"
    bind_port: int = Field(default=8090, ge=1, le=65535)

    gemini_api_key: str = ""
    # Discrete clips, not a Live session: a standard multimodal model handles
    # audio input and supports structured output. Pin the exact id against the
    # docs before the event; it lives here so changing it never touches code.
    transcription_model: str = "gemini-3.5-flash"
    transcription_thinking_level: Literal["minimal", "low", "medium", "high"] = (
        "minimal"
    )
    request_timeout_seconds: float = Field(default=12.0, gt=0, le=60)
    max_attempts: int = Field(default=2, ge=1, le=5)
    model_probe_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    model_probe_retry_seconds: float = Field(default=30.0, ge=5, le=600)
    model_probe_success_seconds: float = Field(default=300.0, ge=30, le=3600)

    # Carril 3 caps segments at MAX_SEGMENT_SECONDS (28 s by default). Anything
    # far above that is a malformed request, not a long sentence.
    max_segment_seconds: int = Field(default=40, ge=5, le=300)

    redis_url: str = "redis://redis:6379/0"
    stage_context_file: str = "config/stages.json"
    bus_enabled: bool = False
    bus_queue_size: int = Field(default=32, ge=1, le=1024)
    max_parallel_stages: int = Field(default=4, ge=1, le=32)

    transcription_engine: Literal["gemini", "stub"] = "gemini"
    allow_stub_engine: bool = False

    @property
    def max_segment_bytes(self) -> int:
        return self.max_segment_seconds * 16_000 * 2


@lru_cache
def get_settings() -> TranscriberSettings:
    return TranscriberSettings()
