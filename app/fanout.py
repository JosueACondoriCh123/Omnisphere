from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from typing import Any

from redis.exceptions import RedisError

from app.config import Settings
from app.context import ContextProvider
from app.metrics import PIPELINE_METRICS
from app.state import RuntimeState, WebSocketHub
from app.storage import SessionStore
from contracts.events import CaptionEvent, TraceStamp

logger = logging.getLogger("nerdearla.fanout")


class CaptionFanout:
    """Bridge the shared Redis caption contract to partitioned client sockets."""

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
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.store: SessionStore | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="caption-fanout")

    async def close(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self) -> None:
        import redis.asyncio as redis

        while not self._stop.is_set():
            client = None
            pubsub = None
            try:
                client = redis.from_url(self.settings.redis_url)
                pubsub = client.pubsub()
                await pubsub.psubscribe("stage:*:captions")
                self.runtime.redis_connected = True
                self.runtime.redis_error = None
                async for message in pubsub.listen():
                    if self._stop.is_set():
                        break
                    if message.get("type") != "pmessage":
                        continue
                    await self.dispatch(message["data"])
            except asyncio.CancelledError:
                raise
            except (RedisError, OSError, ValueError, TypeError, KeyError) as exc:
                self.runtime.redis_connected = False
                self.runtime.redis_error = str(exc)[:300]
                logger.warning("Redis caption fanout unavailable: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=1)
                except TimeoutError:
                    pass
            finally:
                if pubsub:
                    await pubsub.aclose()
                if client:
                    await client.aclose()

    async def dispatch(self, raw: str | bytes) -> int:
        event = CaptionEvent.from_json(raw)
        if event.session_id and self.store is not None:
            active = self.store.current_session(event.stage_id)
            if active is None or active["id"] != event.session_id:
                return 0
        fanout_trace = asdict(TraceStamp.make("fanout", event.stage_id, event.revision))
        traces = [*event.traces, fanout_trace]
        PIPELINE_METRICS.observe(event.stage_id, traces)

        vad_at = next(
            (item.get("t_wall_ms") for item in event.traces if item.get("hop") == "vad"),
            None,
        )
        tier2_at = next(
            (
                item.get("t_wall_ms")
                for item in reversed(event.traces)
                if item.get("hop") in {"tier2a", "tier2b"}
            ),
            None,
        )
        worker = self.runtime.workers.get(event.stage_id)
        if worker and isinstance(vad_at, int) and isinstance(tier2_at, int):
            worker.inference_ms = max(0, tier2_at - vad_at)

        texts: dict[str, str] = {}
        if event.text.es:
            texts["es"] = event.text.es
        if event.text.en:
            texts["en"] = event.text.en
        if event.text.original:
            if event.lang_detected in {"es", "en"}:
                texts.setdefault(event.lang_detected, event.text.original)
            elif not texts:
                context = await self.context_provider.get(event.stage_id)
                lang = next(
                    (item for item in context.languages if item in {"es", "en"}), "es"
                )
                texts[lang] = event.text.original

        session = self.store.current_session(event.stage_id) if self.store is not None else None
        if self.store is not None and session is None:
            session = self.store.start_session(event.stage_id)
        payloads: list[dict[str, Any]] = []
        for lang, text in texts.items():
            payload: dict[str, Any] = {
                "type": "caption",
                "stage_id": event.stage_id,
                "lang": lang,
                "text": text,
                "original": event.text.original,
                "t0_ms": event.t0_ms,
                "t1_ms": event.t1_ms,
                "state": event.state,
                "revision": event.revision,
                "tier": event.tier,
                "emitted_at_ms": event.emitted_at_ms,
                "traces": traces,
            }
            if event.audio_end_wall_ms is not None:
                payload["audio_end_wall_ms"] = event.audio_end_wall_ms
            if self.store is not None:
                assert session is not None
                payload["session_id"] = event.session_id or session["id"]
                payload["provider"] = getattr(event, "provider", "legacy")
            payloads.append(payload)
        saved = (
            self.store.commit_captions(payloads)
            if self.store is not None and event.state == "committed"
            else [(payload, True) for payload in payloads]
        )
        delivered = 0
        for payload, inserted in saved:
            if not inserted:
                continue
            lang = str(payload["lang"])
            await self.runtime.record_committed(event.stage_id, lang, payload)
            assert self.store is None or session is not None
            if self.store is None or session["permissions"].get("publish"):
                delivered += await self.hub.publish(event.stage_id, lang, payload)
        return delivered
