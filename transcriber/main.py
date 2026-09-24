from __future__ import annotations

import logging
import re
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from transcriber.audio import pcm_duration_ms
from transcriber.config import TranscriberSettings, get_settings
from transcriber.context import decode_stage_context
from transcriber.engine import (
    EngineUnavailable,
    GeminiEngine,
    TranscriptionEngine,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nerdearla.transcriber")

STAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

app = FastAPI(title="Nerdearla transcriber", version="0.1.0")

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
        _engine = GeminiEngine(settings)
    return _engine


def next_sequence(stage_id: str) -> int:
    value = _sequences.get(stage_id, 0) + 1
    _sequences[stage_id] = value
    return value


@app.get("/health")
async def health(
    settings: Annotated[TranscriberSettings, Depends(get_settings)],
) -> dict[str, Any]:
    return {
        "service": settings.service_name,
        "model": settings.transcription_model,
        "api_key_configured": bool(settings.gemini_api_key),
        "stages_seen": sorted(_sequences),
    }


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
