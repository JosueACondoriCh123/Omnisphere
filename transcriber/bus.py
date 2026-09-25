from __future__ import annotations

import asyncio
import binascii
import json
import logging
import re
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from redis.exceptions import RedisError

from contracts.events import AudioSegment, CaptionEvent, CaptionText, TraceStamp, now_ms
from transcriber.config import TranscriberSettings
from transcriber.context import StageContext
from transcriber.engine import TranscriptionEngine

logger = logging.getLogger("nerdearla.transcriber.bus")

STAGE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
CHANNEL_PATTERN = re.compile(r"^stage:([a-zA-Z0-9_-]{1,64}):audio$")
BACKOFF_DELAYS = (0.5, 1.0, 2.0, 4.0, 5.0)


@dataclass
class BusStats:
    processed: int = 0
    published: int = 0
    silent: int = 0
    failures: int = 0
    queue_overflows: int = 0
    drafts_coalesced: int = 0
    last_error: str | None = None


def _overlaps(left: AudioSegment, right: AudioSegment) -> bool:
    return left.t0_ms < right.t1_ms and right.t0_ms < left.t1_ms


class CoalescingStageQueue:
    """Latest-draft-wins queue; committed clauses are never dropped."""

    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._items: deque[AudioSegment] = deque()
        self._available = asyncio.Event()
        self._inflight: AudioSegment | None = None

    def qsize(self) -> int:
        return len(self._items)

    def put_nowait(self, segment: AudioSegment) -> tuple[bool, int]:
        pending = list(self._items)
        coalesced = 0

        if not segment.is_clause_end:
            if (
                self._inflight is not None
                and self._inflight.is_clause_end
                and _overlaps(self._inflight, segment)
            ) or any(item.is_clause_end and _overlaps(item, segment) for item in pending):
                return False, 1

            kept: list[AudioSegment] = []
            for item in pending:
                if not item.is_clause_end and _overlaps(item, segment):
                    coalesced += 1
                else:
                    kept.append(item)
            if len(kept) >= self.maxsize:
                raise asyncio.QueueFull
            kept.append(segment)
            self._items = deque(kept)
        else:
            overlapping_drafts = [
                item
                for item in pending
                if not item.is_clause_end and _overlaps(item, segment)
            ]
            inflight_draft = bool(
                self._inflight is not None
                and not self._inflight.is_clause_end
                and _overlaps(self._inflight, segment)
            )
            newest_draft = None if inflight_draft else (
                max(overlapping_drafts, key=lambda item: item.seq)
                if overlapping_drafts
                else None
            )
            kept = []
            for item in pending:
                if item in overlapping_drafts and item is not newest_draft:
                    coalesced += 1
                else:
                    kept.append(item)
            kept.append(segment)
            self._items = deque(kept)

        self._available.set()
        return True, coalesced

    async def get(self) -> AudioSegment:
        while not self._items:
            self._available.clear()
            await self._available.wait()
        item = self._items.popleft()
        self._inflight = item
        if not self._items:
            self._available.clear()
        return item

    def task_done(self) -> None:
        self._inflight = None


class RedisTranscriber:
    """Redis bus bridge from raw audio segments to transcription captions."""

    def __init__(
        self,
        settings: TranscriberSettings,
        engine: TranscriptionEngine | Any,
        redis_client: Any | None = None,
    ) -> None:
        self.settings = settings
        self._engine = engine
        self._redis = redis_client
        self._owns_redis = redis_client is None

        self.stats = BusStats()
        self._status = "connected" if (settings.bus_enabled and redis_client) else ("connecting" if settings.bus_enabled else "disabled")
        self._redis_connected = bool(settings.bus_enabled and redis_client)

        self._stop = asyncio.Event()
        self._main_task: asyncio.Task[None] | None = None
        self._stage_queues: dict[str, CoalescingStageQueue] = {}
        self._stage_workers: dict[str, asyncio.Task[None]] = {}
        self._stage_semaphore = asyncio.Semaphore(self.settings.max_parallel_stages)
        self._dedup_lru: OrderedDict[tuple[str, int, int, int], None] = OrderedDict()
        self._contexts: dict[str, StageContext] = {}

        self._load_contexts()

    @property
    def engine(self) -> TranscriptionEngine:
        if callable(self._engine):
            return self._engine()
        return self._engine

    def _load_contexts(self) -> None:
        context_path = Path(self.settings.stage_context_file)
        try:
            if context_path.is_file():
                raw = context_path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict):
                    for stage_id, stage_data in data.items():
                        if isinstance(stage_data, dict):
                            item = dict(stage_data)
                            item.setdefault("id", str(stage_id))
                            self._contexts[str(stage_id)] = StageContext.model_validate(item)
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
            logger.warning("Failed to load stage contexts from %s: %s", context_path, exc)

    def get_context(self, stage_id: str) -> StageContext:
        if stage_id in self._contexts:
            return self._contexts[stage_id]
        return StageContext(id=stage_id, languages=["es"])

    def health_status(self) -> dict[str, Any]:
        queued = sum(q.qsize() for q in self._stage_queues.values())
        return {
            "enabled": self.settings.bus_enabled,
            "status": self._status,
            "redis_connected": self._redis_connected,
            "queued": queued,
            "processed": self.stats.processed,
            "published": self.stats.published,
            "silent": self.stats.silent,
            "failures": self.stats.failures,
            "queue_overflows": self.stats.queue_overflows,
            "drafts_coalesced": self.stats.drafts_coalesced,
            "last_error": self.stats.last_error,
        }

    async def start(self) -> None:
        if not self.settings.bus_enabled:
            self._status = "disabled"
            return
        self._stop.clear()
        self._main_task = asyncio.create_task(self._run(), name="transcriber-bus-main")

    async def close(self) -> None:
        self._stop.set()
        self._status = "stopped"
        self._redis_connected = False

        if self._main_task:
            self._main_task.cancel()
            await asyncio.gather(self._main_task, return_exceptions=True)
            self._main_task = None

        for worker in self._stage_workers.values():
            worker.cancel()
        if self._stage_workers:
            await asyncio.gather(*self._stage_workers.values(), return_exceptions=True)
            self._stage_workers.clear()

        if self._redis is not None and self._owns_redis:
            try:
                await self._redis.aclose()
            except (RedisError, OSError) as exc:
                logger.debug("Error closing Redis client: %s", exc)
            self._redis = None

    def _get_or_create_stage_queue(self, stage_id: str) -> CoalescingStageQueue:
        if stage_id not in self._stage_queues:
            queue = CoalescingStageQueue(self.settings.bus_queue_size)
            self._stage_queues[stage_id] = queue
            self._stage_workers[stage_id] = asyncio.create_task(
                self._stage_worker(stage_id, queue),
                name=f"transcriber-stage-worker-{stage_id}",
            )
        return self._stage_queues[stage_id]

    async def _run(self) -> None:
        import redis.asyncio as aioredis

        backoff_idx = 0
        pubsub = None

        while not self._stop.is_set():
            try:
                if self._redis is None:
                    self._redis = aioredis.from_url(self.settings.redis_url)
                    self._owns_redis = True

                self._status = "connecting"
                pubsub = self._redis.pubsub()
                await pubsub.psubscribe("stage:*:audio")

                self._status = "connected"
                self._redis_connected = True
                backoff_idx = 0
                logger.info("Subscribed to stage:*:audio on Redis")

                async for message in pubsub.listen():
                    if self._stop.is_set():
                        break
                    if not isinstance(message, dict) or message.get("type") != "pmessage":
                        continue
                    channel = message.get("channel")
                    channel_str = channel.decode("utf-8") if isinstance(channel, bytes) else str(channel or "")
                    await self._handle_incoming_message(channel_str, message.get("data"))

            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001  # Supervisor loop must survive transport and connection failures
                self._redis_connected = False
                self._status = "reconnecting"
                self.stats.last_error = str(exc)
                delay = BACKOFF_DELAYS[min(backoff_idx, len(BACKOFF_DELAYS) - 1)]
                backoff_idx += 1
                logger.warning("Redis transcriber connection error: %s. Reconnecting in %.1fs...", exc, delay)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=delay)
                except (TimeoutError, asyncio.TimeoutError):
                    _ = None
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.aclose()
                    except (RedisError, OSError) as exc:
                        logger.debug("Error closing pubsub: %s", exc)
                    pubsub = None

    async def _handle_incoming_message(self, channel: str, raw_data: Any) -> None:
        match = CHANNEL_PATTERN.fullmatch(channel)
        if not match:
            logger.warning("Rejected message on unrecognized channel: %s", channel)
            return
        channel_stage_id = match.group(1)

        try:
            if isinstance(raw_data, bytes):
                raw_str = raw_data.decode("utf-8")
            elif isinstance(raw_data, str):
                raw_str = raw_data
            else:
                logger.warning("Rejected non-text payload on channel: %s", channel)
                return
            segment = AudioSegment.from_json(raw_str)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            logger.warning("Rejected invalid AudioSegment JSON on channel: %s", channel)
            return

        if not STAGE_ID_PATTERN.fullmatch(segment.stage_id):
            logger.warning("Rejected segment with invalid stage_id")
            return

        if segment.stage_id != channel_stage_id:
            logger.warning(
                "Rejected segment stage mismatch: channel=%s payload=%s",
                channel_stage_id,
                segment.stage_id,
            )
            return

        try:
            pcm = segment.pcm()
        except (ValueError, binascii.Error):
            logger.warning("Rejected segment with invalid base64 PCM for stage %s", channel_stage_id)
            return

        if not pcm or len(pcm) > self.settings.max_segment_bytes:
            logger.warning(
                "Rejected segment with invalid PCM length (%d bytes) for stage %s",
                len(pcm) if pcm else 0,
                channel_stage_id,
            )
            return

        # Deduplication LRU check
        dedup_key = (segment.stage_id, segment.seq, segment.t0_ms, segment.t1_ms)
        if dedup_key in self._dedup_lru:
            logger.debug("Duplicate segment suppressed for stage %s seq %d", segment.stage_id, segment.seq)
            return
        self._dedup_lru[dedup_key] = None
        if len(self._dedup_lru) > 1024:
            self._dedup_lru.popitem(last=False)

        # Enqueue for the specific stage
        queue = self._get_or_create_stage_queue(segment.stage_id)
        try:
            accepted, coalesced = queue.put_nowait(segment)
            self.stats.drafts_coalesced += coalesced
            if not accepted:
                logger.debug(
                    "Discarded stale draft for stage %s seq=%d",
                    segment.stage_id,
                    segment.seq,
                )
        except asyncio.QueueFull:
            self.stats.queue_overflows += 1
            logger.error(
                "Stage %s queue is full (size %d), dropping segment seq=%d",
                segment.stage_id,
                self.settings.bus_queue_size,
                segment.seq,
            )

    async def _stage_worker(self, stage_id: str, queue: CoalescingStageQueue) -> None:
        while not self._stop.is_set():
            try:
                segment = await queue.get()
            except asyncio.CancelledError:
                break

            try:
                async with self._stage_semaphore:
                    await self._process_segment(segment)
            except asyncio.CancelledError:
                break
            except Exception:  # Worker loop must not crash on unhandled stage processing error
                logger.exception("Unexpected error in stage worker %s", stage_id)
            finally:
                queue.task_done()

    async def _process_segment(self, segment: AudioSegment) -> None:
        self.stats.processed += 1
        context = self.get_context(segment.stage_id)
        call_started_trace = (
            [asdict(TraceStamp.make("tier2a", segment.stage_id, segment.seq))]
            if segment.is_clause_end
            else []
        )

        try:
            pcm = segment.pcm()
            result = await self.engine.process(pcm, context, segment.is_clause_end)
        except Exception as exc:  # noqa: BLE001  # Engine calls external SDK/LLM where any error must be recorded without killing worker
            self.stats.failures += 1
            self.stats.last_error = str(exc)
            logger.error("Transcription engine failed for stage %s seq %d: %s", segment.stage_id, segment.seq, exc)
            return

        self.stats.last_error = None

        if result.is_silent:
            self.stats.silent += 1
            logger.info("Silence detected for stage %s seq %d; skipping caption publish", segment.stage_id, segment.seq)
            return

        completed_hop = "tier2b" if segment.is_clause_end else "tier1"
        event = CaptionEvent(
            stage_id=segment.stage_id,
            t0_ms=segment.t0_ms,
            t1_ms=segment.t1_ms,
            state="committed" if segment.is_clause_end else "draft",
            revision=segment.seq,
            tier=2 if segment.is_clause_end else 1,
            lang_detected=result.source_language or "unknown",
            text=CaptionText(
                original=result.original,
                es=result.captions.get("es", ""),
                en=result.captions.get("en", ""),
            ),
            emitted_at_ms=now_ms(),
            traces=[
                *segment.traces,
                *call_started_trace,
                asdict(TraceStamp.make(completed_hop, segment.stage_id, segment.seq)),
            ],
        )

        caption_channel = f"stage:{segment.stage_id}:captions"
        try:
            if self._redis is not None:
                await self._redis.publish(caption_channel, event.to_json())
                self.stats.published += 1
            else:
                self.stats.failures += 1
                self.stats.last_error = "Redis client is not connected"
                logger.error("Cannot publish caption: Redis client is not connected")
        except (RedisError, OSError) as exc:
            self.stats.failures += 1
            self.stats.last_error = str(exc)
            logger.error("Failed to publish caption on %s: %s", caption_channel, exc)
