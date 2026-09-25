from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "nerdearla-plumbing"
    mediamtx_api_url: str = "http://mediamtx:9997"
    mediamtx_rtsp_base: str = "rtsp://mediamtx:8554"
    mediamtx_poll_seconds: float = Field(default=1.0, ge=0.25, le=30)

    internal_api_base: str = "http://127.0.0.1:8080"
    internal_token: str = "dev-only-token"
    redis_url: str = "redis://redis:6379/0"
    public_rtmp_host: str = "localhost"
    public_rtmp_port: int = Field(default=1935, ge=1, le=65535)
    context_url_template: str = ""
    stage_context_file: str = "config/stages.json"
    transcriber_url: str = ""
    transcriber_health_url: str = "http://transcriber:8090/readyz"
    transcriber_poll_seconds: float = Field(default=2.0, ge=0.5, le=30)

    vad_threshold: float = Field(default=0.55, ge=0, le=1)
    vad_min_silence_ms: int = Field(default=420, ge=100, le=5000)
    vad_speech_pad_ms: int = Field(default=140, ge=0, le=1000)
    partial_segment_seconds: float = Field(default=1.5, ge=0.5, le=10)
    max_segment_seconds: int = Field(default=28, ge=3, le=120)
    ffmpeg_reconnect_seconds: float = Field(default=1.0, ge=0.1, le=30)
    stream_grace_seconds: float = Field(default=15.0, ge=0, le=300)

    capture_node_stale_seconds: int = Field(default=15, ge=5, le=300)
    worker_stale_seconds: int = Field(default=12, ge=5, le=300)
    allowed_origins: str = "*"
    db_path: str = "data/omnistage.db"
    web_db_path: str = ""
    retention_days: int = Field(default=30, ge=1, le=365)
    transport_mode: str = "redis"  # native installer sets "local"
    provider_mode: str = "auto"  # auto, cloud or local
    gemini_api_key: str = ""
    gemini_live_model: str = "gemini-3.5-transcribe-live"
    gemini_translation_model: str = "gemini-3.5-flash-lite"
    local_asr_model_path: str = ""
    local_asr_device: str = "cuda"
    gemma_api_url: str = "http://127.0.0.1:8092"
    gemma_model: str = "gemma-4-E2B-it"


@lru_cache
def get_settings() -> Settings:
    return Settings()
