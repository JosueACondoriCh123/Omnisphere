from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import time
from dataclasses import dataclass

import httpx

from app.config import Settings
from app.context import ContextProvider
from app.domain import StageContext, stage_id_from_path, utc_now
from app.state import RuntimeState, WebSocketHub, WorkerState
from app.storage import SessionStore

logger = logging.getLogger("nerdearla.orchestrator")


@dataclass
class WorkerProcess:
    stage_id: str
    context: StageContext
    process: asyncio.subprocess.Process
    log_task: asyncio.Task[None]


class StageOrchestrator:
    """Turns MediaMTX path state into isolated per-stage worker processes."""

    def __init__(
        self,
        settings: Settings,
        runtime: RuntimeState,
        hub: WebSocketHub,
        context_provider: ContextProvider,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.hub = hub
        self.context_provider = context_provider
        self.workers: dict[str, WorkerProcess] = {}
        self.store: SessionStore | None = None
        self._offline_since: dict[str, float] = {}
        self._stop = asyncio.Event()
        self._monitor_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._monitor_task = asyncio.create_task(self._monitor(), name="mediamtx-monitor")

    async def close(self) -> None:
        self._stop.set()
        if self._monitor_task:
            self._monitor_task.cancel()
            await asyncio.gather(self._monitor_task, return_exceptions=True)
        await asyncio.gather(
            *(self.stop_worker(stage_id, "service_shutdown") for stage_id in list(self.workers)),
            return_exceptions=True,
        )

    async def _monitor(self) -> None:
        async with httpx.AsyncClient(timeout=3) as client:
            while not self._stop.is_set():
                try:
                    response = await client.get(f"{self.settings.mediamtx_api_url}/v3/paths/list")
                    response.raise_for_status()
                    payload = response.json()
                    active = self._active_stages(payload)
                    self.runtime.mediamtx_connected = True
                    self.runtime.mediamtx_error = None
                    self.runtime.active_paths = {
                        f"live/stage-{stage_id}" for stage_id in active
                    }
                    await self._reconcile(active)
                except asyncio.CancelledError:
                    raise
                except (httpx.HTTPError, OSError, RuntimeError, ValueError) as exc:
                    self.runtime.mediamtx_connected = False
                    self.runtime.mediamtx_error = str(exc)[:300]
                    logger.warning("MediaMTX control API unavailable: %s", exc)

                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.mediamtx_poll_seconds
                    )
                except TimeoutError:
                    pass

    @staticmethod
    def _active_stages(payload: dict) -> set[str]:
        active: set[str] = set()
        for item in payload.get("items", []):
            stage_id = stage_id_from_path(str(item.get("name", "")))
            if stage_id and item.get("ready", False):
                active.add(stage_id)
        return active

    async def _reconcile(self, active: set[str]) -> None:
        for stage_id, worker in list(self.workers.items()):
            if worker.process.returncode is not None:
                logger.error(
                    "Worker for stage %s exited with code %s",
                    stage_id,
                    worker.process.returncode,
                )
                await self._forget_worker(stage_id)

        for stage_id in sorted(active):
            self._offline_since.pop(stage_id, None)
            if stage_id not in self.workers:
                await self.start_worker(stage_id)

        for stage_id in sorted(set(self.workers) - active):
            offline_since = self._offline_since.setdefault(stage_id, time.monotonic())
            offline_for = time.monotonic() - offline_since
            if offline_for >= self.settings.stream_grace_seconds:
                await self.stop_worker(stage_id, "stream_stopped")

    async def start_worker(self, stage_id: str) -> None:
        # The context request intentionally precedes process creation: this is the
        # stream_started -> context -> isolated worker contract.
        try:
            context = await self.context_provider.get(stage_id)
        except Exception as exc:
            logger.exception("Could not load context for stage %s", stage_id)
            self.runtime.workers[stage_id] = WorkerState(
                stage_id=stage_id, state="failed", error=f"context: {exc}"
            )
            return

        context_b64 = base64.urlsafe_b64encode(
            context.model_dump_json().encode("utf-8")
        ).decode("ascii")
        environment = os.environ.copy()
        environment.pop("GEMINI_API_KEY", None)
        environment["NERDEARLA_STAGE_CONTEXT_B64"] = context_b64
        if self.store is not None:
            session = self.store.start_session(stage_id, context.session or context.name)
            environment["OMNISTAGE_SESSION_ID"] = session["id"]
            environment["OMNISTAGE_SESSION_STARTED_AT"] = session["started_at"]
        stream_url = f"{self.settings.mediamtx_rtsp_base}/live/stage-{stage_id}"

        worker_binary = os.environ.get("OMNISTAGE_WORKER_BIN")
        process = await asyncio.create_subprocess_exec(
            *([worker_binary] if worker_binary else [sys.executable, "-m", "app.room_worker"]),
            "--stage",
            stage_id,
            "--stream-url",
            stream_url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=environment,
        )
        log_task = asyncio.create_task(
            self._drain_logs(stage_id, process), name=f"worker-log-{stage_id}"
        )
        self.workers[stage_id] = WorkerProcess(stage_id, context, process, log_task)
        self._offline_since.pop(stage_id, None)
        self.runtime.workers[stage_id] = WorkerState(
            stage_id=stage_id,
            pid=process.pid,
            state="starting",
            ffmpeg_alive=False,
        )
        event = {
            "type": "stream_started",
            "stage_id": stage_id,
            "session_id": session["id"] if self.store is not None else None,
            "emitted_at": utc_now().isoformat(),
            "context": context.model_dump(),
        }
        for lang in context.languages:
            await self.hub.publish(stage_id, lang, event)
        logger.info("Started isolated worker pid=%s for stage %s", process.pid, stage_id)

    async def stop_worker(self, stage_id: str, reason: str) -> None:
        worker = self.workers.get(stage_id)
        if not worker:
            return
        if worker.process.returncode is None:
            worker.process.terminate()
            try:
                await asyncio.wait_for(worker.process.wait(), timeout=6)
            except TimeoutError:
                worker.process.kill()
                await worker.process.wait()
        event = {
            "type": "stream_stopped",
            "stage_id": stage_id,
            "reason": reason,
            "emitted_at": utc_now().isoformat(),
        }
        for lang in worker.context.languages:
            await self.hub.publish(stage_id, lang, event)
        await self._forget_worker(stage_id)
        if self.store is not None:
            self.store.end_session(stage_id)
        self._offline_since.pop(stage_id, None)
        self.runtime.workers.pop(stage_id, None)
        logger.info("Stopped worker for stage %s (%s)", stage_id, reason)

    async def _forget_worker(self, stage_id: str) -> None:
        worker = self.workers.pop(stage_id, None)
        if worker:
            worker.log_task.cancel()
            await asyncio.gather(worker.log_task, return_exceptions=True)

    @staticmethod
    async def _drain_logs(stage_id: str, process: asyncio.subprocess.Process) -> None:
        if not process.stdout:
            return
        while line := await process.stdout.readline():
            message = line.decode("utf-8", errors="replace").rstrip()
            try:
                decoded = json.loads(message)
                logger.info("worker[%s] %s", stage_id, decoded)
            except json.JSONDecodeError:
                logger.info("worker[%s] %s", stage_id, message)
