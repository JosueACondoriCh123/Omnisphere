"""Native single-host transport and cloud/local caption routing.

Workers send non-overlapping PCM frames for Live transcription and VAD windows
for the offline engine. No Redis broker is required by the Windows runtime.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from app.config import Settings
from app.context import ContextProvider
from app.fanout import CaptionFanout
from app.state import RuntimeState
from app.storage import SessionStore
from contracts.events import AudioSegment, CaptionEvent, CaptionText, TraceStamp, now_ms
from transcriber.local import FasterWhisperASR, Gemma4Translator, LocalCaptionEngine

logger = logging.getLogger("omnistage.hybrid")
LIVE_RENEWAL_SECONDS = 530
LIVE_FINAL_GRACE_SECONDS = 2


class CloudFallback(RuntimeError):
    pass


@dataclass
class StageRoute:
    stage_id: str
    session_id: str | None = None
    frame_queue: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=120))
    recent_frames: deque[bytes] = field(default_factory=lambda: deque(maxlen=80))
    local_segments: deque[AudioSegment] = field(default_factory=deque)
    pending: deque[AudioSegment] = field(default_factory=lambda: deque(maxlen=128))
    segment_ready: asyncio.Event = field(default_factory=asyncio.Event)
    provider: str = "local"
    cloud_connected: bool = False
    last_frame_ms: int = 0
    cloud_task: asyncio.Task[None] | None = None
    local_task: asyncio.Task[None] | None = None
    failed_cloud: bool = False
    cloud_retry_at: float = 0.0
    cloud_finals: deque[str] = field(default_factory=deque)
    cloud_match_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    committed_windows: set[int] = field(default_factory=set)
    final_windows: set[int] = field(default_factory=set)
    cloud_audio_ms: int = 0
    translation_input_tokens: int = 0
    translation_output_tokens: int = 0
    dropped_clauses: int = 0


class CloudTranslator:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None

    async def translate(self, text: str, glossary: list[str]) -> tuple[str, str, str, int, int]:
        from google import genai
        from google.genai import types

        if self._client is None:
            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        prompt = (
            "Detect whether this caption is Spanish or English. Translate it to the other language. "
            "Keep technical terms, product names, commands and Spanglish unchanged. "
            "Return JSON with source_language ('es' or 'en') and translation. "
            f"Protected terms: {', '.join(glossary[:100])}. Caption: {text}"
        )
        response = await self._client.aio.models.generate_content(
            model=self.settings.gemini_translation_model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        data = json.loads(response.text or "{}")
        source = str(data.get("source_language") or "")
        translated = str(data.get("translation") or "").strip()
        if source not in {"es", "en"} or not translated:
            raise ValueError("cloud translation returned incomplete data")
        usage = response.usage_metadata
        return (
            source, text, translated,
            int(getattr(usage, "prompt_token_count", 0) or 0),
            int(getattr(usage, "candidates_token_count", 0) or 0),
        )


class HybridPipeline:
    def __init__(
        self,
        settings: Settings,
        runtime: RuntimeState,
        context_provider: ContextProvider,
        fanout: CaptionFanout,
        store: SessionStore,
    ) -> None:
        self.settings = settings
        self.runtime = runtime
        self.context_provider = context_provider
        self.fanout = fanout
        self.store = store
        self.mode = settings.provider_mode if settings.provider_mode in {"auto", "cloud", "local"} else "auto"
        self.routes: dict[str, StageRoute] = {}
        self.asr = FasterWhisperASR(settings.local_asr_model_path, settings.local_asr_device)
        self.gemma = Gemma4Translator(settings.gemma_api_url, settings.gemma_model)
        self.local = LocalCaptionEngine(self.asr, self.gemma)
        self.cloud_translation = CloudTranslator(settings)
        self._closed = False
        self.local_ready = False
        self._model_warm_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._model_warm_task = asyncio.create_task(self._warm_local(), name="local-model-warmup")

    async def _warm_local(self) -> None:
        while not self._closed and not self.local_ready:
            try:
                await self.asr.warm()
                if not await self.gemma.ready():
                    raise RuntimeError("Gemma 4 server is not ready")
                self.local_ready = True
                self.runtime.transcriber_up = True
                self.runtime.transcriber_error = None
                self.runtime.transcriber_model = self.settings.gemma_model
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - model loaders raise backend-specific exceptions
                self.local_ready = False
                self.runtime.transcriber_error = str(exc)[:300]
                logger.warning("Local model warmup failed: %s", exc)
                await asyncio.sleep(2)

    async def close(self) -> None:
        self._closed = True
        if self._model_warm_task:
            self._model_warm_task.cancel()
            await asyncio.gather(self._model_warm_task, return_exceptions=True)
        tasks = [task for route in self.routes.values() for task in (route.cloud_task, route.local_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.gemma.close()

    def _cloud_allowed(self, stage_id: str) -> bool:
        session = self.store.current_session(stage_id)
        permission = (session or {}).get("permissions") or {}
        return bool(permission.get("cloud") and self.settings.gemini_api_key)

    def _transcription_allowed(self, stage_id: str) -> bool:
        session = self.store.current_session(stage_id)
        permission = (session or {}).get("permissions") or {}
        return all(bool(permission.get(key)) for key in
                   ("capture", "transcribe", "translate", "publish", "retain"))

    async def route(self, stage_id: str) -> StageRoute:
        session = self.store.current_session(stage_id)
        session_id = session["id"] if session else None
        if stage_id not in self.routes:
            route = StageRoute(stage_id, session_id=session_id)
            self.routes[stage_id] = route
            route.local_task = asyncio.create_task(self._local_worker(route), name=f"local-{stage_id}")
            await self._choose_provider(route)
        route = self.routes[stage_id]
        if route.session_id != session_id:
            route.session_id = session_id
            if route.local_task:
                task = route.local_task
                route.local_task = None
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if route.cloud_task:
                task = route.cloud_task
                route.cloud_task = None
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            route.pending.clear()
            route.local_segments.clear()
            route.cloud_finals.clear()
            route.committed_windows.clear()
            route.final_windows.clear()
            route.dropped_clauses = 0
            route.cloud_audio_ms = 0
            route.translation_input_tokens = 0
            route.translation_output_tokens = 0
            route.failed_cloud = False
            route.cloud_retry_at = 0
            while not route.frame_queue.empty():
                route.frame_queue.get_nowait()
            route.local_task = asyncio.create_task(self._local_worker(route), name=f"local-{stage_id}")
            await self._choose_provider(route)
        return route

    async def _choose_provider(self, route: StageRoute) -> None:
        use_cloud = (self.mode != "local" and self._transcription_allowed(route.stage_id)
                     and self._cloud_allowed(route.stage_id) and not route.failed_cloud)
        route.provider = "cloud" if use_cloud else "local"
        if route.provider == "cloud" and route.cloud_task is None:
            while not route.frame_queue.empty():
                route.frame_queue.get_nowait()
            route.cloud_task = asyncio.create_task(self._cloud_worker(route), name=f"live-{route.stage_id}")
        if route.provider == "local" and route.cloud_task is not None:
            route.cloud_finals.clear()
            route.cloud_task.cancel()
            await asyncio.gather(route.cloud_task, return_exceptions=True)
            route.cloud_task = None
            for segment in route.pending:
                if segment.is_clause_end and segment.t0_ms not in route.committed_windows:
                    self._queue_local(route, segment)
            route.pending.clear()

    async def set_mode(self, mode: str) -> None:
        if mode not in {"auto", "cloud", "local"}:
            raise ValueError("mode must be auto, cloud or local")
        self.mode = mode
        for route in self.routes.values():
            if mode == "cloud":
                route.failed_cloud = False
            await self._choose_provider(route)

    async def feed_frame(self, stage_id: str, t1_ms: int, pcm: bytes) -> None:
        if not self._transcription_allowed(stage_id):
            self.runtime.transcriber_error = "session permissions are incomplete"
            return
        route = await self.route(stage_id)
        route.last_frame_ms = t1_ms
        route.recent_frames.append(pcm)
        if route.failed_cloud and self.mode != "local" and time.monotonic() >= route.cloud_retry_at:
            route.failed_cloud = False
            await self._choose_provider(route)
        if route.provider == "cloud":
            try:
                route.frame_queue.put_nowait(pcm)
            except asyncio.QueueFull:
                logger.error("Cloud frame queue overflow for stage %s", stage_id)
                self._mark_cloud_failed(route, "cloud frame queue overflow")
                await self._choose_provider(route)

    async def feed_segment(self, segment: AudioSegment) -> None:
        if not self._transcription_allowed(segment.stage_id):
            self.runtime.transcriber_error = "session permissions are incomplete"
            return
        route = await self.route(segment.stage_id)
        segment = replace(segment, session_id=route.session_id)
        if segment.is_clause_end:
            route.final_windows.add(segment.t0_ms)
        if len(route.pending) == route.pending.maxlen and route.pending[0].is_clause_end:
            route.dropped_clauses += 1
        route.pending.append(segment)
        if route.provider == "local":
            self._queue_local(route, segment)
        elif segment.is_clause_end:
            await self._drain_cloud_finals(route)

    @staticmethod
    def _queue_local(route: StageRoute, segment: AudioSegment) -> None:
        route.local_segments = deque(
            item for item in route.local_segments
            if item.is_clause_end or item.t0_ms != segment.t0_ms
        )
        if segment.is_clause_end:
            finals = [item for item in route.local_segments if item.is_clause_end]
            drafts = [item for item in route.local_segments if not item.is_clause_end]
            route.local_segments = deque([*finals, segment, *drafts])
        else:
            route.local_segments.append(segment)
        while len(route.local_segments) > 48:
            draft = next((item for item in route.local_segments if not item.is_clause_end), None)
            if draft is None:
                route.local_segments.pop()
                route.dropped_clauses += 1
                break
            route.local_segments.remove(draft)
        route.segment_ready.set()

    def _mark_cloud_failed(self, route: StageRoute, reason: str) -> None:
        route.failed_cloud = True
        route.cloud_retry_at = time.monotonic() + 10
        route.cloud_connected = False
        route.provider = "local"
        route.cloud_finals.clear()
        self.runtime.transcriber_error = reason[:300]
        for segment in route.pending:
            if segment.is_clause_end and segment.t0_ms not in route.committed_windows:
                self._queue_local(route, segment)
        route.pending.clear()

    def _safe_cloud_error(self, error: Exception) -> str:
        message = str(error) or type(error).__name__
        if self.settings.gemini_api_key:
            message = message.replace(self.settings.gemini_api_key, "[redacted]")
        return message[:300]

    async def _drain_cloud_finals(self, route: StageRoute) -> None:
        async with route.cloud_match_lock:
            while route.provider == "cloud" and route.cloud_finals:
                segment = next(
                    (item for item in route.pending
                     if item.is_clause_end and item.t0_ms not in route.committed_windows),
                    None,
                )
                if segment is None:
                    return
                text = route.cloud_finals[0]
                try:
                    context = await self.context_provider.get(route.stage_id)
                    source, original, translated, input_tokens, output_tokens = (
                        await self.cloud_translation.translate(text, list(context.glossary))
                    )
                    es = original if source == "es" else translated
                    en = original if source == "en" else translated
                    await self._publish(segment, original, source, es, en, "gemini-live", final=True)
                except Exception as exc:  # noqa: BLE001 - SDK transports raise backend-specific exceptions
                    reason = self._safe_cloud_error(exc)
                    logger.warning("Cloud caption failed for %s: %s", route.stage_id, reason)
                    self._mark_cloud_failed(route, reason)
                    return
                route.cloud_finals.popleft()
                route.translation_input_tokens += input_tokens
                route.translation_output_tokens += output_tokens
                route.committed_windows.add(segment.t0_ms)
                while route.pending and route.pending[0].t0_ms <= segment.t0_ms:
                    route.pending.popleft()

    async def _local_worker(self, route: StageRoute) -> None:
        while not self._closed:
            if not route.local_segments:
                route.segment_ready.clear()
                await route.segment_ready.wait()
            if not route.local_segments:
                continue
            segment = route.local_segments.popleft()
            if segment.t0_ms in route.committed_windows:
                continue
            if not self._transcription_allowed(route.stage_id):
                continue
            try:
                context = await self.context_provider.get(route.stage_id)
                result = await self.local.process(segment.pcm(), list(context.glossary))
                self.runtime.transcriber_up = True
                self.local_ready = True
                self.runtime.transcriber_error = None
                self.runtime.transcriber_model = self.settings.gemma_model
                if result.original:
                    await self._publish(
                        segment, result.original, result.source_language, result.es, result.en,
                        "local-gemma4", final=segment.is_clause_end,
                    )
                    if segment.is_clause_end:
                        route.committed_windows.add(segment.t0_ms)
                        while route.pending and route.pending[0].t0_ms <= segment.t0_ms:
                            route.pending.popleft()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - inference backends raise multiple exception classes
                self.local_ready = False
                self.runtime.transcriber_up = False
                self.runtime.transcriber_error = str(exc)[:300]
                logger.error("Local inference failed for %s: %s", route.stage_id, exc)
                if (segment.is_clause_end and segment.session_id == route.session_id
                        and segment.t0_ms not in route.committed_windows):
                    route.local_segments.appendleft(segment)
                    route.segment_ready.set()
                    await asyncio.sleep(0.5)

    async def _publish(
        self,
        segment: AudioSegment,
        original: str,
        source: str,
        es: str,
        en: str,
        provider: str,
        *,
        final: bool,
    ) -> None:
        if not self._transcription_allowed(segment.stage_id):
            return
        current = self.store.current_session(segment.stage_id)
        if segment.session_id is None or current is None or current["id"] != segment.session_id:
            return
        hop = "tier2b" if final else "tier1"
        event = CaptionEvent(
            stage_id=segment.stage_id,
            t0_ms=segment.t0_ms,
            t1_ms=segment.t1_ms,
            state="committed" if final else "draft",
            revision=segment.seq,
            tier=2 if final else 1,
            lang_detected=source,
            text=CaptionText(original=original, es=es, en=en),
            emitted_at_ms=now_ms(),
            traces=[*segment.traces, asdict(TraceStamp.make(hop, segment.stage_id, segment.seq))],
            provider=provider,
            audio_end_wall_ms=segment.audio_end_wall_ms,
            session_id=segment.session_id,
        )
        await self.fanout.dispatch(event.to_json())

    async def _cloud_worker(self, route: StageRoute) -> None:
        from google import genai
        from google.genai import types

        try:
            client = genai.Client(api_key=self.settings.gemini_api_key)
            context = await self.context_provider.get(route.stage_id)
            vocabulary = [term.strip() for term in context.glossary
                          if isinstance(term, str) and term.strip()][:100]
            config = types.LiveConnectConfig(
                response_modalities=["TEXT"],
                input_audio_transcription=types.AudioTranscriptionConfig(
                    language_codes=[], custom_vocabulary=vocabulary,
                ),
            )
            while route.provider == "cloud" and not self._closed:
                async with client.aio.live.connect(model=self.settings.gemini_live_model, config=config) as session:
                    route.cloud_connected = True
                    self.runtime.transcriber_up = True
                    self.runtime.transcriber_model = self.settings.gemini_live_model
                    stop_sending = asyncio.Event()
                    async def send(stop_event: asyncio.Event = stop_sending) -> None:
                        while route.provider == "cloud" and not self._closed and not stop_event.is_set():
                            try:
                                pcm = await asyncio.wait_for(route.frame_queue.get(), timeout=0.1)
                            except TimeoutError:
                                continue
                            await session.send_realtime_input(
                                audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000")
                            )
                            route.cloud_audio_ms += len(pcm) * 1000 // 32_000

                    async def receive() -> None:
                        async for response in session.receive():
                            content = response.server_content
                            if content is None:
                                continue
                            interim = getattr(content, "interim_input_transcription", None)
                            final = getattr(content, "input_transcription", None)
                            if interim and interim.text:
                                await self._cloud_text(route, interim.text, False)
                            if final and final.text:
                                await self._cloud_text(route, final.text, True)

                    send_task = asyncio.create_task(send())
                    receive_task = asyncio.create_task(receive())
                    done: set[asyncio.Task[None]] = set()
                    try:
                        done, _ = await asyncio.wait(
                            (send_task, receive_task), timeout=LIVE_RENEWAL_SECONDS,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if not done:
                            stop_sending.set()
                            await asyncio.wait_for(send_task, timeout=1)
                            await session.send_realtime_input(audio_stream_end=True)
                            try:
                                await asyncio.wait_for(asyncio.shield(receive_task), timeout=LIVE_FINAL_GRACE_SECONDS)
                            except TimeoutError:
                                pass
                    finally:
                        for task in (send_task, receive_task):
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(send_task, receive_task, return_exceptions=True)
                    for task in done:
                        if not task.cancelled() and task.exception():
                            raise task.exception()  # type: ignore[misc]
                    if done and route.provider == "cloud" and not self._closed:
                        raise CloudFallback("Gemini Live session ended before renewal")
                    if not done:
                        # The old Live session may end before its last final response.
                        # Replay only uncommitted, real VAD clauses through the local engine.
                        for segment in route.pending:
                            if segment.is_clause_end and segment.t0_ms not in route.committed_windows:
                                self._queue_local(route, segment)
                        route.pending.clear()
                        route.cloud_finals.clear()
                    route.cloud_connected = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK transports raise backend-specific exceptions
            reason = self._safe_cloud_error(exc)
            logger.error("Gemini Live failed for %s: %s", route.stage_id, reason)
            self._mark_cloud_failed(route, reason)
        finally:
            route.cloud_connected = False
            route.cloud_task = None

    async def _cloud_text(self, route: StageRoute, text: str, final: bool) -> None:
        if not text.strip() or not final or route.provider != "cloud":
            return
        route.cloud_finals.append(text.strip())
        await self._drain_cloud_finals(route)

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "stages": {
                stage_id: {
                    "provider": route.provider,
                    "ready": route.cloud_connected if route.provider == "cloud" else self.local_ready,
                    "cloud_failed": route.failed_cloud,
                    "cloud_retry_seconds": max(0, round(route.cloud_retry_at - time.monotonic(), 1))
                    if route.failed_cloud else 0,
                    "frame_backlog": route.frame_queue.qsize(),
                    "local_backlog": len(route.local_segments),
                    "dropped_clauses": route.dropped_clauses,
                    "final_clause_count": len(route.final_windows),
                    "committed_clause_count": len(route.committed_windows),
                    "unmatched_cloud_finals": len(route.cloud_finals),
                    "cloud_audio_minutes": round(route.cloud_audio_ms / 60_000, 3),
                    "translation_input_tokens": route.translation_input_tokens,
                    "translation_output_tokens": route.translation_output_tokens,
                    "cloud_cost_usd_estimate": round(
                        route.cloud_audio_ms / 60_000 * 0.009
                        + route.translation_input_tokens / 1_000_000 * 0.30
                        + route.translation_output_tokens / 1_000_000 * 2.50, 5
                    ),
                }
                for stage_id, route in self.routes.items()
            },
        }
