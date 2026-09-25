from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from transcriber.audio import pcm_duration_ms
from transcriber.bus import RedisTranscriber
from transcriber.config import TranscriberSettings, get_settings
from transcriber.context import decode_stage_context
from transcriber.engine import (
    EngineUnavailable,
    GeminiEngine,
    StubTranscriptionEngine,
    TranscriptionEngine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nerdearla.transcriber")

STAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_bus: RedisTranscriber | None = None
_probe_task: asyncio.Task[None] | None = None


async def _probe_engine(engine: GeminiEngine, settings: TranscriberSettings) -> None:
    while True:
        ready = bool(engine.health_status()["ready"])
        delay = (
            settings.model_probe_success_seconds
            if ready
            else settings.model_probe_retry_seconds
        )
        await asyncio.sleep(delay)
        await engine.probe()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _bus, _probe_task
    settings = get_settings()
    engine = get_engine(settings)
    if _bus is None:
        _bus = RedisTranscriber(settings, engine)
    if settings.bus_enabled:
        await _bus.start()
    if isinstance(engine, GeminiEngine):
        await engine.probe()
        _probe_task = asyncio.create_task(
            _probe_engine(engine, settings), name="gemini-model-probe"
        )
    try:
        yield
    finally:
        if _probe_task is not None:
            _probe_task.cancel()
            await asyncio.gather(_probe_task, return_exceptions=True)
            _probe_task = None
        if _bus is not None:
            await _bus.close()
            _bus = None


app = FastAPI(title="Nerdearla transcriber", version="0.1.0", lifespan=lifespan)

# Monotonic per stage. Note for integration: the room worker keeps its own
# counter for vad_start/vad_end events, so the two sequences interleave on the
# same channel. Consumers must treat `seq` as ordering within a source, not as
# a global identifier.
_sequences: dict[str, int] = {}
_engine: TranscriptionEngine | None = None


def get_engine(
    settings: Annotated[TranscriberSettings, Depends(get_settings)],
) -> TranscriptionEngine:
    global _engine
    if _engine is None:
        if settings.transcription_engine == "stub":
            _engine = StubTranscriptionEngine(settings)
        else:
            _engine = GeminiEngine(settings)
    return _engine


def get_bus() -> RedisTranscriber | None:
    return _bus


def next_sequence(stage_id: str) -> int:
    value = _sequences.get(stage_id, 0) + 1
    _sequences[stage_id] = value
    return value


@app.get("/health")
async def health(
    settings: Annotated[TranscriberSettings, Depends(get_settings)],
) -> dict[str, Any]:
    bus_status = _bus.health_status() if _bus is not None else {
        "enabled": settings.bus_enabled,
        "status": "disabled",
        "redis_connected": False,
        "queued": 0,
        "processed": 0,
        "published": 0,
        "silent": 0,
        "failures": 0,
        "queue_overflows": 0,
        "drafts_coalesced": 0,
        "last_error": None,
    }
    engine_status = (
        _engine.health_status()
        if _engine is not None and hasattr(_engine, "health_status")
        else {
            "ready": False,
            "last_error": "engine not initialized",
            "last_checked_ms": None,
            "last_success_ms": None,
        }
    )
    return {
        "service": settings.service_name,
        "model": settings.transcription_model,
        "api_key_configured": bool(settings.gemini_api_key),
        "stages_seen": sorted(_sequences),
        "bus": bus_status,
        "engine": engine_status,
        "engine_mode": settings.transcription_engine,
    }


@app.get("/readyz")
async def readyz(
    settings: Annotated[TranscriberSettings, Depends(get_settings)],
) -> Response:
    bus_status = _bus.health_status() if _bus is not None else {
        "redis_connected": False,
        "status": "disabled",
    }
    engine_status = (
        _engine.health_status()
        if _engine is not None and hasattr(_engine, "health_status")
        else {"ready": False, "last_error": "engine not initialized"}
    )
    bus_ready = not settings.bus_enabled or bool(bus_status["redis_connected"])
    if settings.transcription_engine == "stub":
        ready = bus_ready
    else:
        ready = bool(settings.gemini_api_key) and bool(engine_status.get("ready")) and bus_ready
    payload = {
        "status": "ready" if ready else "not_ready",
        "model": settings.transcription_model,
        "api_key_configured": bool(settings.gemini_api_key),
        "engine": engine_status,
        "bus": bus_status,
    }
    return JSONResponse(payload, status_code=200 if ready else 503)


@app.post("/v1/audio/segments")
async def ingest_segment(
    request: Request,
    settings: Annotated[TranscriberSettings, Depends(get_settings)],
    engine: Annotated[TranscriptionEngine, Depends(get_engine)],
    x_stage_id: Annotated[str, Header()],
    x_is_clause_end: Annotated[str, Header()] = "false",
    x_stage_context: Annotated[str, Header()] = "",
) -> dict[str, Any]:
    """Transcribe and translate one VAD segment.

    Implements the transcriber side of docs/contracts.md: raw s16le PCM body,
    stage metadata in headers, `events` in the response.
    """
    if not STAGE_ID_PATTERN.fullmatch(x_stage_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid stage id")

    pcm = await request.body()
    if not pcm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty audio body")
    if len(pcm) > settings.max_segment_bytes:
        # Literal 413: Starlette renamed the constant and the project pins a
        # range of FastAPI versions that straddles the rename.
        raise HTTPException(413, f"segment exceeds {settings.max_segment_seconds}s")

    is_clause_end = x_is_clause_end.strip().lower() == "true"
    context = decode_stage_context(x_stage_context, x_stage_id)

    started = time.perf_counter()
    try:
        result = await engine.process(pcm, context, is_clause_end)
    except EngineUnavailable as exc:
        # 503 lets the room worker mark itself degraded, which is what raises
        # the transcriber_socket_down alarm on the operations dashboard.
        logger.error("Stage %s: engine unavailable: %s", x_stage_id, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)

    if result.is_silent:
        # Silence still costs a call, so it is worth logging, but publishing an
        # empty caption would blank the screen mid-talk.
        logger.info("Stage %s: no intelligible speech in segment", x_stage_id)
        return {"events": []}

    # A segment cut at the safety limit is not a finished clause, so it ships as
    # a draft: the audience sees it immediately, styled as provisional.
    event_type = "commit" if is_clause_end else "draft"
    payload = {
        "source_language": result.source_language,
        "preserved_terms": list(result.preserved_terms),
        "audio_ms": pcm_duration_ms(pcm),
        "engine_ms": elapsed_ms,
    }

    events = [
        {
            "lang": lang,
            "type": event_type,
            "text": result.captions.get(lang, ""),
            "seq": next_sequence(x_stage_id),
            "is_clause_end": is_clause_end,
            "payload": payload,
        }
        for lang in context.target_languages()
    ]
    return {"events": events}
