from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.config import get_settings
from app.context import ContextProvider
from app.domain import (
    LANG_PATTERN,
    STAGE_ID_PATTERN,
    CaptureHeartbeat,
    CaptureRegistration,
    StreamEvent,
    WorkerHeartbeat,
    utc_now,
)
from app.fanout import CaptionFanout
from app.metrics import PIPELINE_METRICS
from app.orchestrator import StageOrchestrator
from app.state import CaptureNodeState, RuntimeState, WebSocketHub, WorkerState
from app.transcriber_monitor import TranscriberMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("nerdearla.api")

settings = get_settings()
runtime = RuntimeState()
hub = WebSocketHub()
context_provider = ContextProvider(settings)
orchestrator = StageOrchestrator(settings, runtime, hub, context_provider)
caption_fanout = CaptionFanout(settings, runtime, hub, context_provider)
transcriber_monitor = TranscriberMonitor(settings, runtime)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await caption_fanout.start()
    await transcriber_monitor.start()
    await orchestrator.start()
    try:
        yield
    finally:
        await orchestrator.close()
        await transcriber_monitor.close()
        await caption_fanout.close()


app = FastAPI(
    title="Nerdearla Carril 3 — Plomería",
    version="1.0.0",
    description="RTMP ingest, isolated room workers, Silero VAD and partitioned captions WS.",
    lifespan=lifespan,
)
origins = [origin.strip() for origin in settings.allowed_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def validate_partition(stage_id: str, lang: str | None = None) -> None:
    if not STAGE_ID_PATTERN.fullmatch(stage_id):
        raise HTTPException(status_code=422, detail="invalid stage id")
    if lang is not None and (
        not LANG_PATTERN.fullmatch(lang) or lang not in {"es", "en"}
    ):
        raise HTTPException(status_code=422, detail="invalid language")


def require_internal_token(
    x_internal_token: Annotated[str | None, Header()] = None,
) -> None:
    if not x_internal_token or x_internal_token != settings.internal_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "service": settings.service_name,
        "docs": "/docs",
        "health": "/healthz",
        "websocket": "/ws/stages/{id}/{lang}",
    }


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
async def readyz() -> Response:
    if runtime.mediamtx_connected and runtime.redis_connected and runtime.transcriber_up:
        return JSONResponse(
            {
                "status": "ready",
                "mediamtx": "ready",
                "redis": "ready",
                "transcriber": "ready",
            }
        )
    return JSONResponse(
        {
            "status": "not_ready",
            "mediamtx_error": runtime.mediamtx_error,
            "redis_error": runtime.redis_error,
            "transcriber_error": runtime.transcriber_error,
        },
        status_code=503,
    )


@app.get("/api/stages")
async def stages() -> dict[str, Any]:
    snapshot = await runtime.snapshot()
    catalog = {item.id: item for item in await context_provider.list()}
    stage_ids = {
        path.removeprefix("live/stage-") for path in snapshot["active_paths"]
    } | set(snapshot["workers"]) | set(catalog) | {
        node.stage_id for node in runtime.capture_nodes.values()
    }
    items = []
    for stage_id in sorted(stage_ids):
        context = catalog.get(stage_id) or await context_provider.get(stage_id)
        items.append(
            {
                **(await stage_metrics(stage_id)),
                "name": context.name,
                "session": context.session,
                "languages": context.languages,
            }
        )
    return {
        "items": items,
        "mediamtx_connected": snapshot["mediamtx_connected"],
        "transcriber_up": snapshot["transcriber_up"],
    }


@app.get("/api/stages/{stage_id}/context")
async def stage_context(stage_id: str) -> dict[str, Any]:
    validate_partition(stage_id)
    return (await context_provider.get(stage_id)).model_dump()


def _seconds_since(value: datetime | None) -> float | None:
    if value is None:
        return None
    return max(0.0, (datetime.now(UTC) - value).total_seconds())


@app.get("/api/metrics/stages/{stage_id}")
async def stage_metrics(stage_id: str) -> dict[str, Any]:
    validate_partition(stage_id)
    worker = runtime.workers.get(stage_id)
    matching_nodes = [
        node for node in runtime.capture_nodes.values() if node.stage_id == stage_id
    ]
    freshest_node = max(matching_nodes, key=lambda node: node.heartbeat_at, default=None)
    path = f"live/stage-{stage_id}"
    stream_up = path in runtime.active_paths

    worker_age = _seconds_since(worker.heartbeat_at) if worker else None
    audio_age = _seconds_since(worker.audio_seen_at) if worker else None
    capture_age = _seconds_since(freshest_node.heartbeat_at) if freshest_node else None
    worker_alive = bool(
        worker
        and worker_age is not None
        and worker_age <= settings.worker_stale_seconds
        and worker.state != "failed"
    )
    capture_alive = bool(
        freshest_node
        and capture_age is not None
        and capture_age <= settings.capture_node_stale_seconds
        and freshest_node.ffmpeg_alive
    )
    audio_up = bool(stream_up and worker_alive and audio_age is not None and audio_age <= 5)
    network_ms = freshest_node.rtt_ms if freshest_node else None
    inference_ms = worker.inference_ms if worker else None
    subscriber_counts = await hub.counts()
    websocket_clients = sum(
        count
        for partition, count in subscriber_counts.items()
        if partition.startswith(f"{stage_id}:")
    )
    latency_ms = (
        round((network_ms or 0) + (inference_ms or 0), 2)
        if network_ms is not None or inference_ms is not None
        else None
    )

    alarms: list[dict[str, str]] = []
    if stream_up and not audio_up:
        alarms.append({"code": "audio_signal_down", "severity": "critical"})
    if latency_ms is not None and latency_ms > 1500:
        alarms.append({"code": "latency_over_1500ms", "severity": "critical"})
    if worker and (
        worker.state in {"degraded", "failed"}
        or (worker.error and "transcriber" in worker.error.lower())
    ):
        alarms.append({"code": "transcriber_socket_down", "severity": "critical"})
    if stream_up and not runtime.transcriber_up and not any(
        alarm["code"] == "transcriber_socket_down" for alarm in alarms
    ):
        alarms.append({"code": "transcriber_socket_down", "severity": "critical"})

    return {
        "stage_id": stage_id,
        "stream_up": stream_up,
        "audio_up": audio_up,
        "capture_node_up": capture_alive,
        "worker_up": worker_alive,
        "worker_state": worker.state if worker else "stopped",
        "transcriber_up": runtime.transcriber_up,
        "transcriber_error": runtime.transcriber_error,
        "transcriber_model": runtime.transcriber_model,
        "network_ms": network_ms,
        "inference_ms": inference_ms,
        "latency_ms": latency_ms,
        "vad_backlog_ms": worker.vad_backlog_ms if worker else None,
        "redis_publish_ms": worker.redis_publish_ms if worker else None,
        "segments_published": worker.segments_published if worker else 0,
        "ffmpeg_restarts": worker.ffmpeg_restarts if worker else 0,
        "audio_samples": worker.audio_samples if worker else 0,
        "websocket_clients": websocket_clients,
        "audio_age_seconds": round(audio_age, 2) if audio_age is not None else None,
        "hop_latencies": PIPELINE_METRICS.stage_snapshot(stage_id),
        "alarms": alarms,
    }


@app.get("/api/metrics/stages")
async def all_stage_metrics() -> dict[str, Any]:
    stage_ids = {
        path.removeprefix("live/stage-") for path in runtime.active_paths
    } | set(runtime.workers) | {node.stage_id for node in runtime.capture_nodes.values()}
    return {"items": [await stage_metrics(item) for item in sorted(stage_ids)]}


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics() -> str:
    stage_ids = {
        path.removeprefix("live/stage-") for path in runtime.active_paths
    } | set(runtime.workers) | {node.stage_id for node in runtime.capture_nodes.values()}
    lines = [
        "# HELP nerdearla_stage_stream_up Whether the MediaMTX path is ready.",
        "# TYPE nerdearla_stage_stream_up gauge",
        "# HELP nerdearla_stage_audio_up Whether normalized PCM is arriving.",
        "# TYPE nerdearla_stage_audio_up gauge",
        "# HELP nerdearla_network_latency_ms Capture-node HTTP round-trip latency.",
        "# TYPE nerdearla_network_latency_ms gauge",
        "# HELP nerdearla_inference_latency_ms Latest upstream inference latency.",
        "# TYPE nerdearla_inference_latency_ms gauge",
        "# HELP nerdearla_transcriber_up Whether Gemini and the transcription bus are ready.",
        "# TYPE nerdearla_transcriber_up gauge",
        "# HELP nerdearla_vad_backlog_ms Wall-clock lag behind decoded PCM.",
        "# TYPE nerdearla_vad_backlog_ms gauge",
        "# HELP nerdearla_redis_publish_ms Latest Redis publish duration.",
        "# TYPE nerdearla_redis_publish_ms gauge",
        "# HELP nerdearla_websocket_clients Current clients for a stage.",
        "# TYPE nerdearla_websocket_clients gauge",
    ]
    lines.extend(PIPELINE_METRICS.prometheus())
    for stage_id in sorted(stage_ids):
        metrics = await stage_metrics(stage_id)
        label = f'stage_id="{stage_id}"'
        lines.append(f"nerdearla_stage_stream_up{{{label}}} {int(metrics['stream_up'])}")
        lines.append(f"nerdearla_stage_audio_up{{{label}}} {int(metrics['audio_up'])}")
        lines.append(
            f"nerdearla_transcriber_up{{{label}}} {int(metrics['transcriber_up'])}"
        )
        if metrics["network_ms"] is not None:
            lines.append(
                f"nerdearla_network_latency_ms{{{label}}} {metrics['network_ms']}"
            )
        if metrics["inference_ms"] is not None:
            lines.append(
                f"nerdearla_inference_latency_ms{{{label}}} {metrics['inference_ms']}"
            )
        if metrics["vad_backlog_ms"] is not None:
            lines.append(
                f"nerdearla_vad_backlog_ms{{{label}}} {metrics['vad_backlog_ms']}"
            )
        if metrics["redis_publish_ms"] is not None:
            lines.append(
                f"nerdearla_redis_publish_ms{{{label}}} {metrics['redis_publish_ms']}"
            )
        lines.append(
            f"nerdearla_websocket_clients{{{label}}} {metrics['websocket_clients']}"
        )
    return "\n".join(lines) + "\n"


@app.post("/api/capture-nodes/register", status_code=201)
async def register_capture_node(registration: CaptureRegistration) -> dict[str, Any]:
    runtime.capture_nodes[registration.node_id] = CaptureNodeState(
        node_id=registration.node_id,
        stage_id=registration.stage_id,
        hostname=registration.hostname,
        source=registration.source,
        version=registration.version,
    )
    logger.info(
        "Capture node %s registered for stage %s",
        registration.node_id,
        registration.stage_id,
    )
    return {
        "node_id": registration.node_id,
        "stage_id": registration.stage_id,
        "rtmp_path": f"/live/stage-{registration.stage_id}",
        "rtmp_url": (
            f"rtmp://{settings.public_rtmp_host}:{settings.public_rtmp_port}"
            f"/live/stage-{registration.stage_id}"
        ),
        "heartbeat_seconds": 5,
    }


@app.post("/api/capture-nodes/{node_id}/heartbeat")
async def capture_heartbeat(node_id: str, heartbeat: CaptureHeartbeat) -> dict[str, str]:
    node = runtime.capture_nodes.get(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="capture node is not registered")
    if node.stage_id != heartbeat.stage_id:
        raise HTTPException(status_code=409, detail="capture node stage mismatch")
    node.heartbeat_at = utc_now()
    node.rtt_ms = heartbeat.rtt_ms
    node.ffmpeg_alive = heartbeat.ffmpeg_alive
    node.bytes_sent = heartbeat.bytes_sent
    return {"status": "ok"}


@app.post(
    "/internal/workers/{stage_id}/heartbeat",
    dependencies=[Depends(require_internal_token)],
)
async def worker_heartbeat(stage_id: str, heartbeat: WorkerHeartbeat) -> dict[str, str]:
    validate_partition(stage_id)
    worker = runtime.workers.setdefault(stage_id, WorkerState(stage_id=stage_id))
    worker.pid = heartbeat.pid
    worker.state = heartbeat.state
    worker.heartbeat_at = utc_now()
    worker.audio_seen_at = heartbeat.audio_seen_at
    worker.ffmpeg_alive = heartbeat.ffmpeg_alive
    worker.error = heartbeat.error
    worker.inference_ms = heartbeat.inference_ms
    worker.vad_backlog_ms = heartbeat.vad_backlog_ms
    worker.redis_publish_ms = heartbeat.redis_publish_ms
    worker.segments_published = heartbeat.segments_published
    worker.ffmpeg_restarts = heartbeat.ffmpeg_restarts
    worker.audio_samples = heartbeat.audio_samples
    return {"status": "ok"}


@app.post(
    "/internal/stages/{stage_id}/{lang}/events",
    dependencies=[Depends(require_internal_token)],
)
async def publish_event(stage_id: str, lang: str, event: StreamEvent) -> dict[str, int]:
    validate_partition(stage_id, lang)
    if event.type in {"vad_start", "vad_end"}:
        return {"delivered": 0}
    if event.type in {"draft", "commit"}:
        payload = {
            "type": "caption",
            "stage_id": stage_id,
            "t0_ms": int(event.payload.get("t0_ms", 0)),
            "t1_ms": int(event.payload.get("t1_ms", 0)),
            "state": "draft" if event.type == "draft" else "committed",
            "revision": int(event.payload.get("revision", event.seq or 0)),
            "tier": int(event.payload.get("tier", 0)),
            "lang": lang,
            "text": event.text or "",
            "original": str(event.payload.get("original", event.text or "")),
            "emitted_at_ms": int(event.emitted_at.timestamp() * 1000),
            "traces": list(event.payload.get("traces", [])),
        }
        await runtime.record_committed(stage_id, lang, payload)
    else:
        payload = event.model_dump(mode="json")
        payload["stage_id"] = stage_id
        payload["lang"] = lang
    delivered = await hub.publish(stage_id, lang, payload)
    return {"delivered": delivered}


@app.websocket("/ws/stages/{stage_id}/{lang}")
async def stage_websocket(websocket: WebSocket, stage_id: str, lang: str) -> None:
    if (
        not STAGE_ID_PATTERN.fullmatch(stage_id)
        or not LANG_PATTERN.fullmatch(lang)
        or lang not in {"es", "en"}
    ):
        await websocket.close(code=1008, reason="invalid partition")
        return

    async def snapshot_payload() -> dict[str, Any]:
        return {
            "type": "snapshot",
            "stage_id": stage_id,
            "lang": lang,
            "captions": await runtime.caption_snapshot(stage_id, lang),
        }

    await hub.connect(stage_id, lang, websocket, snapshot_payload)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(stage_id, lang, websocket)
