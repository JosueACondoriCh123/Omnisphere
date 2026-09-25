from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

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
from app.hybrid import HybridPipeline
from app.metrics import PIPELINE_METRICS
from app.orchestrator import StageOrchestrator
from app.state import CaptureNodeState, RuntimeState, WebSocketHub, WorkerState
from app.storage import SessionStore
from app.transcriber_monitor import TranscriberMonitor
from app.web_storage import WebStore
from contracts.events import AudioSegment

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
store: SessionStore | None = None
web_store: WebStore | None = None
hybrid_pipeline: HybridPipeline | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global store, web_store, hybrid_pipeline
    store = SessionStore(settings.db_path, settings.retention_days)
    store.purge_expired()
    web_path = Path(settings.web_db_path) if settings.web_db_path else Path(settings.db_path).with_name("omnistage-web.db")
    if web_path.resolve() == Path(settings.db_path).resolve():
        raise ValueError("WEB_DB_PATH must differ from DB_PATH")
    web_store = WebStore(web_path)
    web_store.purge_expired()
    for session in store.list_sessions():
        if session["ended_at"] is not None or not all(
            session["permissions"].get(key) for key in ("publish", "retain")
        ):
            continue
        for lang in ("es", "en"):
            for caption in store.captions(session["id"], lang):
                web_store.record_caption(caption, session["expires_at"])
    async def retention_loop() -> None:
        while True:
            await asyncio.sleep(3600)
            if store is not None:
                store.purge_expired()
            if web_store is not None:
                web_store.purge_expired()

    retention_task = asyncio.create_task(retention_loop(), name="caption-retention")
    orchestrator.store = store
    caption_fanout.store = store
    caption_fanout.web_store = web_store
    if settings.transport_mode == "local":
        hybrid_pipeline = HybridPipeline(settings, runtime, context_provider, caption_fanout, store)
        saved_mode = store.get_setting("provider_mode")
        if saved_mode in {"auto", "cloud", "local"}:
            hybrid_pipeline.mode = saved_mode
        await hybrid_pipeline.start()
        runtime.redis_connected = True  # local transport does not require an external broker
    else:
        await caption_fanout.start()
        await transcriber_monitor.start()
    await orchestrator.start()
    try:
        yield
    finally:
        retention_task.cancel()
        await asyncio.gather(retention_task, return_exceptions=True)
        await orchestrator.close()
        if hybrid_pipeline is not None:
            await hybrid_pipeline.close()
            hybrid_pipeline = None
        else:
            await transcriber_monitor.close()
            await caption_fanout.close()
        caption_fanout.store = None
        caption_fanout.web_store = None
        orchestrator.store = None
        web_store.close()
        web_store = None
        store.close()
        store = None


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
    transport_ready = runtime.redis_connected if settings.transport_mode != "local" else hybrid_pipeline is not None
    if runtime.mediamtx_connected and transport_ready and runtime.transcriber_up:
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
            "provider": hybrid_pipeline.status() if hybrid_pipeline else None,
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
        active_session = store.current_session(stage_id) if store else None
        items.append(
            {
                **(await stage_metrics(stage_id)),
                "name": context.name,
                "session": active_session["title"] if active_session else context.session,
                "source_type": active_session["source_type"] if active_session else None,
                "languages": context.languages,
                "active_session_id": active_session["id"] if active_session else None,
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

    route_status = hybrid_pipeline.status()["stages"].get(stage_id, {}) if hybrid_pipeline else {}
    transcriber_ready = route_status.get("ready", runtime.transcriber_up)
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
    if stream_up and not transcriber_ready and not any(
        alarm["code"] == "transcriber_socket_down" for alarm in alarms
    ):
        alarms.append({"code": "transcriber_socket_down", "severity": "critical"})
    if route_status.get("dropped_clauses", 0):
        alarms.append({"code": "caption_overload", "severity": "critical"})

    hop_samples = PIPELINE_METRICS.stage_snapshot(stage_id)
    end_to_end = next((item for item in hop_samples if item["from_hop"] == "ingest"
                          and item["to_hop"] == "fanout"), None)

    return {
        "stage_id": stage_id,
        "stream_up": stream_up,
        "audio_up": audio_up,
        "capture_node_up": capture_alive,
        "worker_up": worker_alive,
        "worker_state": worker.state if worker else "stopped",
        "transcriber_up": transcriber_ready,
        "transcriber_error": runtime.transcriber_error,
        "transcriber_model": runtime.transcriber_model,
        "provider": route_status.get("provider") if hybrid_pipeline else "gemini-segment",
        "dropped_clauses": route_status.get("dropped_clauses", 0),
        "final_clause_count": route_status.get("final_clause_count", 0),
        "committed_clause_count": route_status.get("committed_clause_count", 0),
        "provider_ready": transcriber_ready,
        "cloud_audio_minutes": route_status.get("cloud_audio_minutes", 0),
        "translation_input_tokens": route_status.get("translation_input_tokens", 0),
        "translation_output_tokens": route_status.get("translation_output_tokens", 0),
        "pipeline_p95_ms": end_to_end["p95_ms"] if end_to_end else None,
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
        "hop_latencies": hop_samples,
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
        if settings.transport_mode == "local":
            current = store.current_session(stage_id) if store else None
            if not current or not current["permissions"].get("publish"):
                return {"delivered": 0}
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
            "audio_end_wall_ms": event.payload.get("audio_end_wall_ms"),
            "traces": list(event.payload.get("traces", [])),
        }
        if store is not None:
            session = store.current_session(stage_id) or store.start_session(stage_id)
            payload["session_id"] = session["id"]
            payload["provider"] = str(event.payload.get("provider") or "legacy")
            if event.type == "commit":
                payload, inserted = store.commit_caption(payload)
                if not inserted:
                    return {"delivered": 0}
        await runtime.record_committed(stage_id, lang, payload)
    else:
        payload = event.model_dump(mode="json")
        payload["stage_id"] = stage_id
        payload["lang"] = lang
    allowed = True
    if store is not None:
        current = store.current_session(stage_id)
        allowed = bool(current and current["permissions"].get("publish"))
        if (allowed and event.type == "commit" and web_store is not None
                and current["permissions"].get("retain")):
            web_store.record_caption(payload, current["expires_at"])
    delivered = await hub.publish(stage_id, lang, payload) if allowed else 0
    return {"delivered": delivered}


@app.websocket("/ws/stages/{stage_id}/{lang}")
async def stage_websocket(
    websocket: WebSocket, stage_id: str, lang: str
) -> None:
    await serve_stage_websocket(websocket, stage_id, lang)


async def serve_stage_websocket(
    websocket: WebSocket, stage_id: str, lang: str, public_store: WebStore | None = None
) -> None:
    if (
        not STAGE_ID_PATTERN.fullmatch(stage_id)
        or not LANG_PATTERN.fullmatch(lang)
        or lang not in {"es", "en"}
    ):
        await websocket.close(code=1008, reason="invalid partition")
        return

    async def snapshot_payload() -> dict[str, Any]:
        if public_store is not None:
            return public_store.snapshot(stage_id, lang)
        session = store.current_session(stage_id) if store else None
        return {
            "type": "snapshot",
            "stage_id": stage_id,
            "lang": lang,
            "session_id": session["id"] if session else None,
            "captions": (
                (store.captions(session["id"], lang) if session["permissions"].get("publish") else [])
                if store is not None and session is not None
                else await runtime.caption_snapshot(stage_id, lang)
            ),
        }

    await hub.connect(stage_id, lang, websocket, snapshot_payload)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await hub.disconnect(stage_id, lang, websocket)


def required_store() -> SessionStore:
    if store is None:
        raise HTTPException(503, "session storage is not ready")
    return store


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=256)


def _csrf_for(token: str) -> str:
    return hashlib.sha256((token + ":csrf").encode()).hexdigest()


def require_operator(request: Request) -> dict[str, str]:
    token = request.cookies.get("omnistage_operator", "")
    operator = required_store().operator_for_token(token) if token else None
    if operator is None:
        raise HTTPException(401, "operator login required")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        supplied = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(supplied, _csrf_for(token)):
            raise HTTPException(403, "invalid CSRF token")
    return operator


@app.get("/api/operator/bootstrap-status")
async def operator_bootstrap_status(request: Request) -> dict[str, bool]:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "setup is available only on this computer")
    return {"needs_setup": not required_store().has_operators()}


@app.post("/api/operator/bootstrap", status_code=201)
async def operator_bootstrap(request: Request, credentials: Credentials) -> dict[str, str]:
    if request.client is None or request.client.host not in {"127.0.0.1", "::1", "testclient"}:
        raise HTTPException(403, "setup is available only on this computer")
    db = required_store()
    if db.has_operators():
        raise HTTPException(409, "operator setup is complete")
    try:
        operator_id = db.create_operator(credentials.email, credentials.password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    db.audit(operator_id, "bootstrap", operator_id)
    return {"operator_id": operator_id}


@app.post("/api/operator/login")
async def operator_login(credentials: Credentials, response: Response) -> dict[str, str]:
    db = required_store()
    operator = db.authenticate(credentials.email, credentials.password)
    if operator is None:
        raise HTTPException(401, "invalid credentials")
    token = db.issue_token(operator["id"])
    response.set_cookie(
        "omnistage_operator", token, httponly=True, samesite="strict", max_age=12 * 3600,
        secure=False, path="/api/operator",
    )
    db.audit(operator["id"], "login", operator["id"])
    return {**operator, "csrf_token": _csrf_for(token)}


@app.post("/api/operator/logout")
async def operator_logout(
    request: Request, response: Response, operator: Annotated[dict[str, str], Depends(require_operator)]
) -> dict[str, str]:
    required_store().revoke_token(request.cookies["omnistage_operator"])
    response.delete_cookie("omnistage_operator", path="/api/operator")
    required_store().audit(operator["id"], "logout", operator["id"])
    return {"status": "ok"}


@app.get("/api/operator/me")
async def operator_me(
    request: Request, operator: Annotated[dict[str, str], Depends(require_operator)]
) -> dict[str, str]:
    return {**operator, "csrf_token": _csrf_for(request.cookies["omnistage_operator"])}


@app.post("/api/operator/users", status_code=201)
async def create_operator(
    credentials: Credentials, operator: Annotated[dict[str, str], Depends(require_operator)]
) -> dict[str, str]:
    try:
        operator_id = required_store().create_operator(credentials.email, credentials.password)
    except (ValueError, sqlite3.IntegrityError) as exc:
        raise HTTPException(422, str(exc)) from exc
    required_store().audit(operator["id"], "create_operator", operator_id)
    return {"operator_id": operator_id}


@app.get("/api/operator/sessions")
async def operator_sessions(
    operator: Annotated[dict[str, str], Depends(require_operator)], stage_id: str | None = None
) -> dict[str, Any]:
    if stage_id is not None:
        validate_partition(stage_id)
    return {"items": required_store().list_sessions(stage_id)}


@app.get("/api/operator/sessions/{session_id}/captions")
async def operator_captions(
    session_id: str, lang: str, operator: Annotated[dict[str, str], Depends(require_operator)]
) -> dict[str, Any]:
    validate_partition("1", lang)
    session = required_store().get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return {"session": session, "captions": required_store().captions(session_id, lang)}


def _subtitle_time(ms: int, separator: str) -> str:
    ms = max(0, ms)
    hour, rem = divmod(ms, 3_600_000)
    minute, rem = divmod(rem, 60_000)
    second, milli = divmod(rem, 1000)
    return f"{hour:02}:{minute:02}:{second:02}{separator}{milli:03}"


@app.get("/api/operator/sessions/{session_id}/export")
async def operator_export(
    session_id: str,
    lang: str,
    format: str,
    operator: Annotated[dict[str, str], Depends(require_operator)],
) -> Response:
    validate_partition("1", lang)
    if format not in {"srt", "vtt", "txt"}:
        raise HTTPException(422, "format must be srt, vtt or txt")
    session = required_store().get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    captions = required_store().captions(session_id, lang)
    if format == "txt":
        body = "\n".join(item["text"] for item in captions if item["text"])
    else:
        sep = "," if format == "srt" else "."
        lines = [
            f"{index}\n{_subtitle_time(item['t0_ms'], sep)} --> {_subtitle_time(item['t1_ms'], sep)}\n{item['text']}"
            for index, item in enumerate(captions, 1) if item["text"]
        ]
        body = ("WEBVTT\n\n" if format == "vtt" else "") + "\n\n".join(lines) + "\n"
    required_store().audit(operator["id"], "export", session_id)
    return Response(
        body,
        media_type={"srt": "application/x-subrip", "vtt": "text/vtt", "txt": "text/plain"}[format],
        headers={"Content-Disposition": f'attachment; filename="omnistage_{session_id[:8]}_{lang}.{format}"'},
    )


class PermissionUpdate(BaseModel):
    capture: bool = False
    transcribe: bool = False
    translate: bool = False
    cloud: bool = False
    publish: bool = False
    retain: bool = False
    train: bool = False
    evidence_reference: str = Field(default="", max_length=500)


class SessionCreate(BaseModel):
    stage_id: str
    title: str = Field(min_length=1, max_length=200)
    source_type: str = Field(default="obs", pattern="^(obs|file|microphone)$")
    permissions: PermissionUpdate


@app.post("/api/operator/sessions", status_code=201)
async def create_session(
    value: SessionCreate,
    operator: Annotated[dict[str, str], Depends(require_operator)],
) -> dict[str, Any]:
    validate_partition(value.stage_id)
    if settings.transport_mode == "local" and value.stage_id not in {
        stage.id for stage in await context_provider.list()
    }:
        raise HTTPException(422, "stage is not configured in the native catalog")
    if not all((value.permissions.capture, value.permissions.transcribe,
                value.permissions.translate, value.permissions.publish,
                value.permissions.retain, value.permissions.evidence_reference.strip())):
        raise HTTPException(422, "capture, transcription, translation, publication, retention and evidence are required")
    active = required_store().current_session(value.stage_id)
    if active and active["permissions"]:
        raise HTTPException(409, "end the current session before preparing another")
    session = required_store().start_session(
        value.stage_id, value.title, value.source_type, value.permissions.model_dump()
    )
    required_store().audit(operator["id"], "start_session", session["id"])
    return session


@app.post("/api/operator/sessions/{session_id}/end")
async def end_session(
    session_id: str,
    operator: Annotated[dict[str, str], Depends(require_operator)],
) -> dict[str, str]:
    session = required_store().get_session(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    if session["ended_at"] is not None:
        return {"status": "already_ended"}
    active = required_store().current_session(session["stage_id"])
    if active is None or active["id"] != session_id:
        raise HTTPException(409, "session is not active")
    required_store().end_session(session["stage_id"])
    if session["stage_id"] in orchestrator.workers:
        await orchestrator.stop_worker(session["stage_id"], "operator_end")
    required_store().audit(operator["id"], "end_session", session_id)
    return {"status": "ok"}


@app.put("/api/operator/sessions/{session_id}/permissions")
async def operator_permissions(
    session_id: str,
    permissions: PermissionUpdate,
    operator: Annotated[dict[str, str], Depends(require_operator)],
) -> dict[str, str]:
    if any((permissions.capture, permissions.transcribe, permissions.translate,
            permissions.cloud, permissions.publish, permissions.retain,
            permissions.train)) and not permissions.evidence_reference.strip():
        raise HTTPException(422, "permission evidence reference is required")
    if not required_store().set_permissions(session_id, permissions.model_dump()):
        raise HTTPException(404, "session not found")
    if web_store is not None and (not permissions.publish or not permissions.retain):
        web_store.revoke_session(session_id)
    required_store().audit(operator["id"], "permissions", session_id)
    if hybrid_pipeline is not None:
        session = required_store().get_session(session_id)
        if session and session["stage_id"] in hybrid_pipeline.routes:
            await hybrid_pipeline._choose_provider(hybrid_pipeline.routes[session["stage_id"]])
    return {"status": "ok"}


@app.post(
    "/internal/audio/stages/{stage_id}/segments",
    dependencies=[Depends(require_internal_token)],
)
async def native_audio_segment(stage_id: str, request: Request) -> dict[str, str]:
    validate_partition(stage_id)
    if hybrid_pipeline is None:
        raise HTTPException(503, "native audio transport is disabled")
    raw = await request.body()
    if len(raw) > 1_500_000:
        raise HTTPException(413, "audio segment exceeds limit")
    try:
        segment = AudioSegment.from_json(raw)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(422, "invalid audio segment") from exc
    if segment.stage_id != stage_id:
        raise HTTPException(409, "stage mismatch")
    await hybrid_pipeline.feed_segment(segment)
    return {"status": "accepted"}


@app.post(
    "/internal/audio/stages/{stage_id}/cloud-failed",
    dependencies=[Depends(require_internal_token)],
)
async def native_cloud_failed(stage_id: str) -> dict[str, str]:
    validate_partition(stage_id)
    if hybrid_pipeline is None:
        raise HTTPException(503, "native audio transport is disabled")
    route = await hybrid_pipeline.route(stage_id)
    hybrid_pipeline._mark_cloud_failed(route, "capture frame backlog")
    await hybrid_pipeline._choose_provider(route)
    return {"provider": route.provider}


@app.websocket("/internal/audio/stages/{stage_id}/frames")
async def native_audio_frames(websocket: WebSocket, stage_id: str) -> None:
    token = websocket.headers.get("x-internal-token", "")
    if token != settings.internal_token or not STAGE_ID_PATTERN.fullmatch(stage_id) or hybrid_pipeline is None:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            payload = await websocket.receive_bytes()
            if len(payload) < 10 or len(payload) > 32_008:
                await websocket.close(code=1009)
                return
            t1_ms = int.from_bytes(payload[:8], "big")
            await hybrid_pipeline.feed_frame(stage_id, t1_ms, payload[8:])
    except WebSocketDisconnect:
        pass


class ProviderMode(BaseModel):
    mode: str


@app.get("/api/operator/provider")
async def operator_provider(
    operator: Annotated[dict[str, str], Depends(require_operator)]
) -> dict[str, Any]:
    if hybrid_pipeline is None:
        return {"mode": "legacy", "stages": {}}
    return hybrid_pipeline.status()


@app.put("/api/operator/provider")
async def update_provider(
    value: ProviderMode,
    operator: Annotated[dict[str, str], Depends(require_operator)],
) -> dict[str, Any]:
    if hybrid_pipeline is None:
        raise HTTPException(503, "native provider routing is disabled")
    try:
        await hybrid_pipeline.set_mode(value.mode)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    required_store().audit(operator["id"], "provider_mode", value.mode)
    required_store().set_setting("provider_mode", value.mode)
    return hybrid_pipeline.status()


@app.get("/{asset_path:path}")
async def operator_asset(asset_path: str) -> Response:
    """Electron's loopback origin serves the operator UI from the same web build."""
    import os
    from pathlib import Path

    if asset_path.startswith(("api/", "internal/", "ws/")):
        raise HTTPException(404, "not found")
    root = Path(os.environ.get("OMNISTAGE_WEB_DIST", "web/dist")).resolve()
    requested = (root / asset_path).resolve()
    if not requested.is_relative_to(root):
        raise HTTPException(404, "not found")
    if requested.is_file():
        return FileResponse(requested)
    index = root / "index.html"
    if not index.is_file():
        raise HTTPException(503, "web build is not installed")
    return FileResponse(index)
