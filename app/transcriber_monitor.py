from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.config import Settings
from app.domain import utc_now
from app.state import RuntimeState

logger = logging.getLogger("nerdearla.transcriber_monitor")


class TranscriberMonitor:
    def __init__(self, settings: Settings, runtime: RuntimeState) -> None:
        self.settings = settings
        self.runtime = runtime
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="transcriber-monitor")

    async def close(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None

    @staticmethod
    def _error_from_payload(payload: dict[str, Any]) -> str:
        engine = payload.get("engine")
        if isinstance(engine, dict) and engine.get("last_error"):
            return str(engine["last_error"])[:500]
        bus = payload.get("bus")
        if isinstance(bus, dict) and bus.get("last_error"):
            return str(bus["last_error"])[:500]
        return str(payload.get("status") or "transcriber not ready")[:500]

    async def check_once(self, client: httpx.AsyncClient) -> None:
        try:
            response = await client.get(self.settings.transcriber_health_url)
            payload = response.json()
            if not isinstance(payload, dict):
                raise TypeError("invalid transcriber readiness payload")
            self.runtime.transcriber_model = str(payload.get("model") or "") or None
            self.runtime.transcriber_up = response.status_code == 200 and payload.get("status") == "ready"
            self.runtime.transcriber_error = (
                None if self.runtime.transcriber_up else self._error_from_payload(payload)
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self.runtime.transcriber_up = False
            self.runtime.transcriber_error = str(exc)[:500]
        self.runtime.transcriber_checked_at = utc_now()

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=3) as client:
            while not self._stop.is_set():
                await self.check_once(client)
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self.settings.transcriber_poll_seconds
                    )
                except TimeoutError:
                    pass
