from __future__ import annotations

import asyncio
from collections import OrderedDict, defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from app.domain import utc_now


@dataclass
class WorkerState:
    stage_id: str
    pid: int | None = None
    state: str = "starting"
    started_at: datetime = field(default_factory=utc_now)
    heartbeat_at: datetime = field(default_factory=utc_now)
    audio_seen_at: datetime | None = None
    ffmpeg_alive: bool = False
    error: str | None = None
    inference_ms: float | None = None
    vad_backlog_ms: float = 0
    redis_publish_ms: float | None = None
    segments_published: int = 0
    ffmpeg_restarts: int = 0
    audio_samples: int = 0


@dataclass
class CaptureNodeState:
    node_id: str
    stage_id: str
    hostname: str
    source: str
    version: str
    registered_at: datetime = field(default_factory=utc_now)
    heartbeat_at: datetime = field(default_factory=utc_now)
    rtt_ms: float | None = None
    ffmpeg_alive: bool = True
    bytes_sent: int | None = None


class RuntimeState:
    def __init__(self) -> None:
        self.started_at = utc_now()
        self.mediamtx_connected = False
        self.mediamtx_error: str | None = None
        self.redis_connected = False
        self.redis_error: str | None = None
        self.active_paths: set[str] = set()
        self.workers: dict[str, WorkerState] = {}
        self.capture_nodes: dict[str, CaptureNodeState] = {}
        self._committed: dict[
            tuple[str, str], OrderedDict[tuple[int, int], dict[str, Any]]
        ] = defaultdict(OrderedDict)
        self._lock = asyncio.Lock()

    async def record_committed(
        self, stage_id: str, lang: str, caption: dict[str, Any]
    ) -> None:
        if caption.get("state") != "committed":
            return
        key = (int(caption["t0_ms"]), int(caption["t1_ms"]))
        async with self._lock:
            backlog = self._committed[(stage_id, lang)]
            previous = backlog.get(key)
            if previous and int(previous.get("revision", 0)) > int(
                caption.get("revision", 0)
            ):
                return
            backlog[key] = dict(caption)
            backlog.move_to_end(key)
            while len(backlog) > 1_000:
                backlog.popitem(last=False)

    async def caption_snapshot(self, stage_id: str, lang: str) -> list[dict[str, Any]]:
        async with self._lock:
            captions = list(self._committed.get((stage_id, lang), {}).values())
        return sorted(captions, key=lambda item: (item["t0_ms"], item["t1_ms"]))

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "started_at": self.started_at,
                "mediamtx_connected": self.mediamtx_connected,
                "mediamtx_error": self.mediamtx_error,
                "redis_connected": self.redis_connected,
                "redis_error": self.redis_error,
                "active_paths": sorted(self.active_paths),
                "workers": {key: asdict(value) for key, value in self.workers.items()},
                "capture_nodes": {
                    key: asdict(value) for key, value in self.capture_nodes.items()
                },
            }


class WebSocketHub:
    def __init__(self) -> None:
        self._subscribers: dict[tuple[str, str], set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(
        self,
        stage_id: str,
        lang: str,
        websocket: WebSocket,
        initial_payload: Callable[[], Awaitable[dict[str, Any]]] | None = None,
    ) -> None:
        await websocket.accept()
        async with self._lock:
            if initial_payload is not None:
                await websocket.send_json(await initial_payload())
            self._subscribers[(stage_id, lang)].add(websocket)

    async def disconnect(self, stage_id: str, lang: str, websocket: WebSocket) -> None:
        async with self._lock:
            subscribers = self._subscribers[(stage_id, lang)]
            subscribers.discard(websocket)
            if not subscribers:
                self._subscribers.pop((stage_id, lang), None)

    async def publish(self, stage_id: str, lang: str, payload: dict[str, Any]) -> int:
        async with self._lock:
            targets = list(self._subscribers.get((stage_id, lang), set()))

        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json(payload)
            except (RuntimeError, WebSocketDisconnect):
                stale.append(websocket)

        for websocket in stale:
            await self.disconnect(stage_id, lang, websocket)
        return len(targets) - len(stale)

    async def counts(self) -> dict[str, int]:
        async with self._lock:
            return {
                f"{stage_id}:{lang}": len(sockets)
                for (stage_id, lang), sockets in self._subscribers.items()
            }
