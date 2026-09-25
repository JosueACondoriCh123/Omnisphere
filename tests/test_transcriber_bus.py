from __future__ import annotations

import asyncio
from dataclasses import asdict
from typing import Any

import pytest
from fastapi.testclient import TestClient

from contracts.events import AudioSegment, CaptionEvent, TraceStamp
from transcriber.bus import CoalescingStageQueue, RedisTranscriber
from transcriber.config import TranscriberSettings
from transcriber.context import StageContext
from transcriber.engine import SegmentResult
from transcriber.main import app, get_engine


class FakePubSub:
    def __init__(self, messages: list[dict[str, Any]] | None = None) -> None:
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        if messages:
            for msg in messages:
                self._queue.put_nowait(msg)
        self.subscribed_patterns: list[str] = []
        self.closed = False

    def push(self, message: dict[str, Any]) -> None:
        self._queue.put_nowait(message)

    async def psubscribe(self, pattern: str) -> None:
        self.subscribed_patterns.append(pattern)

    async def listen(self):
        while not self.closed:
            try:
                msg = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                yield msg
            except (asyncio.TimeoutError, TimeoutError):
                continue
            except asyncio.CancelledError:
                break

    async def aclose(self) -> None:
        self.closed = True


class FakeRedis:
    def __init__(self, pubsub_messages: list[dict[str, Any]] | None = None) -> None:
        self.pubsub_instance = FakePubSub(pubsub_messages)
        self.published: list[tuple[str, str]] = []
        self.closed = False

    def pubsub(self) -> FakePubSub:
        return self.pubsub_instance

    async def publish(self, channel: str, message: str) -> int:
        self.published.append((channel, message))
        return 1

    async def aclose(self) -> None:
        self.closed = True


class StubEngine:
    def __init__(
        self,
        result: SegmentResult | None = None,
        error: Exception | None = None,
        delay_by_stage: dict[str, float] | None = None,
    ) -> None:
        self.result = result or SegmentResult(
            original="desplegamos el pod",
            source_language="es",
            captions={"es": "desplegamos el pod", "en": "we deploy the pod"},
            preserved_terms=("pod",),
        )
        self.error = error
        self.delay_by_stage = delay_by_stage or {}
        self.calls: list[dict[str, Any]] = []

    async def process(
        self, pcm: bytes, context: StageContext, is_clause_end: bool
    ) -> SegmentResult:
        if context.id in self.delay_by_stage:
            await asyncio.sleep(self.delay_by_stage[context.id])
        self.calls.append({
            "stage_id": context.id,
            "pcm_len": len(pcm),
            "is_clause_end": is_clause_end,
        })
        if self.error:
            raise self.error
        return self.result


def make_segment(
    stage_id: str = "stage-1",
    seq: int = 1,
    t0_ms: int = 1000,
    t1_ms: int = 2500,
    pcm: bytes = b"\x00\x01" * 800,
    is_clause_end: bool = True,
    traces: list[dict[str, Any]] | None = None,
) -> AudioSegment:
    segment = AudioSegment.from_pcm(
        stage_id=stage_id,
        seq=seq,
        t0_ms=t0_ms,
        t1_ms=t1_ms,
        pcm=pcm,
        is_clause_end=is_clause_end,
        rms_dbfs=-20.0,
    )
    if traces is not None:
        return AudioSegment(
            stage_id=segment.stage_id,
            seq=segment.seq,
            t0_ms=segment.t0_ms,
            t1_ms=segment.t1_ms,
            pcm_b64=segment.pcm_b64,
            is_clause_end=segment.is_clause_end,
            rms_dbfs=segment.rms_dbfs,
            traces=traces,
        )
    return segment


def make_pmessage(channel: str, segment_or_raw: AudioSegment | str | bytes) -> dict[str, Any]:
    data = (
        segment_or_raw.to_json()
        if isinstance(segment_or_raw, AudioSegment)
        else segment_or_raw
    )
    return {
        "type": "pmessage",
        "pattern": "stage:*:audio",
        "channel": channel,
        "data": data,
    }


async def wait_for_published(fake_redis: FakeRedis, count: int = 1, timeout: float = 2.0) -> list[tuple[str, str]]:
    start = asyncio.get_event_loop().time()
    while len(fake_redis.published) < count:
        if asyncio.get_event_loop().time() - start > timeout:
            break
        await asyncio.sleep(0.02)
    return fake_redis.published


@pytest.mark.asyncio
async def test_coalescing_queue_keeps_one_draft_before_commit() -> None:
    queue = CoalescingStageQueue(maxsize=2)
    first = make_segment(seq=1, t0_ms=1000, t1_ms=2500, is_clause_end=False)
    latest = make_segment(seq=2, t0_ms=1000, t1_ms=4000, is_clause_end=False)
    commit = make_segment(seq=3, t0_ms=1000, t1_ms=4500, is_clause_end=True)

    assert queue.put_nowait(first) == (True, 0)
    assert queue.put_nowait(latest) == (True, 1)
    assert queue.put_nowait(commit) == (True, 0)
    assert (await queue.get()).seq == 2
    queue.task_done()
    assert (await queue.get()).seq == 3
    queue.task_done()


@pytest.mark.asyncio
async def test_commit_skips_queued_drafts_when_a_draft_is_inflight() -> None:
    queue = CoalescingStageQueue(maxsize=2)
    first = make_segment(seq=1, t0_ms=1000, t1_ms=2500, is_clause_end=False)
    latest = make_segment(seq=2, t0_ms=1000, t1_ms=4000, is_clause_end=False)
    commit = make_segment(seq=3, t0_ms=1000, t1_ms=4500, is_clause_end=True)

    queue.put_nowait(first)
    assert (await queue.get()).seq == 1
    queue.put_nowait(latest)
    accepted, coalesced = queue.put_nowait(commit)
    assert accepted is True
    assert coalesced == 1
    queue.task_done()
    assert (await queue.get()).seq == 3
    queue.task_done()


# 1. is_clause_end=True produce un único committed
@pytest.mark.asyncio
async def test_clause_end_produces_single_committed() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=1, is_clause_end=True)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    published = await wait_for_published(fake_redis, 1)
    await transcriber.close()

    assert len(published) == 1
    channel, payload = published[0]
    assert channel == "stage:stage-1:captions"
    event = CaptionEvent.from_json(payload)
    assert event.state == "committed"
    assert event.revision == 1


# 2. is_clause_end=False produce un único draft
@pytest.mark.asyncio
async def test_force_cut_produces_single_draft() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=2, is_clause_end=False)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    published = await wait_for_published(fake_redis, 1)
    await transcriber.close()

    assert len(published) == 1
    channel, payload = published[0]
    assert channel == "stage:stage-1:captions"
    event = CaptionEvent.from_json(payload)
    assert event.state == "draft"
    assert event.tier == 1
    assert event.traces[-1]["hop"] == "tier1"


# 3. El evento conserva tiempos, revisión y trazas, y termina en tier2b
@pytest.mark.asyncio
async def test_event_preserves_timings_revision_and_traces_ending_in_tier2b() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    vad_trace = asdict(TraceStamp.make("vad", "stage-1", 42))
    seg = make_segment(stage_id="stage-1", seq=42, t0_ms=1200, t1_ms=3400, traces=[vad_trace])
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    published = await wait_for_published(fake_redis, 1)
    await transcriber.close()

    assert len(published) == 1
    event = CaptionEvent.from_json(published[0][1])
    assert event.t0_ms == 1200
    assert event.t1_ms == 3400
    assert event.revision == 42
    assert event.tier == 2
    assert len(event.traces) >= 2
    assert event.traces[0]["hop"] == "vad"
    last_trace = event.traces[-1]
    assert last_trace["hop"] == "tier2b"
    assert last_trace["stage_id"] == "stage-1"
    assert last_trace["seq"] == 42


# 4. Español e inglés viajan dentro del mismo CaptionEvent
@pytest.mark.asyncio
async def test_spanish_and_english_travel_in_same_caption_event() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine(
        result=SegmentResult(
            original="desplegamos el pod",
            source_language="es",
            captions={"es": "desplegamos el pod", "en": "we deploy the pod"},
        )
    )
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=3)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    published = await wait_for_published(fake_redis, 1)
    await transcriber.close()

    assert len(published) == 1
    event = CaptionEvent.from_json(published[0][1])
    assert event.text.original == "desplegamos el pod"
    assert event.text.es == "desplegamos el pod"
    assert event.text.en == "we deploy the pod"


# 5. Un resultado silencioso no publica
@pytest.mark.asyncio
async def test_silent_result_does_not_publish() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine(
        result=SegmentResult(original="   ", source_language="", captions={})
    )
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=4)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    await asyncio.sleep(0.15)
    await transcriber.close()

    assert len(fake_redis.published) == 0
    assert transcriber.stats.silent == 1
    assert transcriber.stats.published == 0


# 6. Un fallo del engine incrementa failures y no publica
@pytest.mark.asyncio
async def test_engine_failure_increments_failures_and_does_not_publish() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine(error=RuntimeError("quota exceeded"))
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=5)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    await asyncio.sleep(0.15)
    await transcriber.close()

    assert len(fake_redis.published) == 0
    assert transcriber.stats.failures == 1
    assert "quota exceeded" in (transcriber.stats.last_error or "")


# 7. JSON inválido no detiene el siguiente mensaje válido
@pytest.mark.asyncio
async def test_invalid_json_does_not_stop_next_valid_message() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    fake_redis.pubsub_instance.push(
        {"type": "pmessage", "pattern": "stage:*:audio", "channel": "stage:stage-1:audio", "data": "broken{json"}
    )
    seg_valid = make_segment(stage_id="stage-1", seq=6)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg_valid))

    published = await wait_for_published(fake_redis, 1)
    await transcriber.close()

    assert len(published) == 1
    event = CaptionEvent.from_json(published[0][1])
    assert event.revision == 6


# 8. Un canal cuya sala no coincide con el payload es rechazado
@pytest.mark.asyncio
async def test_stage_id_mismatch_between_channel_and_payload_is_rejected() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    # Canal declara stage-1, pero el segmento trae stage-2
    seg_mismatch = make_segment(stage_id="stage-2", seq=7)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg_mismatch))

    await asyncio.sleep(0.15)
    await transcriber.close()

    assert len(fake_redis.published) == 0
    assert transcriber.stats.processed == 0


# 9. Un duplicado se publica una sola vez
@pytest.mark.asyncio
async def test_duplicate_segment_is_published_only_once() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=8, t0_ms=1000, t1_ms=2000)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))

    await asyncio.sleep(0.2)
    await transcriber.close()

    assert len(fake_redis.published) == 1
    assert transcriber.stats.published == 1


# 10. Dos segmentos de una misma sala conservan orden
@pytest.mark.asyncio
async def test_two_segments_of_same_room_preserve_order() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg1 = make_segment(stage_id="stage-1", seq=10)
    seg2 = make_segment(stage_id="stage-1", seq=11)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg1))
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg2))

    published = await wait_for_published(fake_redis, 2)
    await transcriber.close()

    assert len(published) == 2
    e1 = CaptionEvent.from_json(published[0][1])
    e2 = CaptionEvent.from_json(published[1][1])
    assert e1.revision == 10
    assert e2.revision == 11


# 11. Una sala lenta no bloquea otra sala
@pytest.mark.asyncio
async def test_slow_room_does_not_block_another_room() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True, max_parallel_stages=4)
    # Sala 1 tarda 0.25 segundos; Sala 2 es inmediata
    engine = StubEngine(delay_by_stage={"stage-1": 0.25, "stage-2": 0.0})
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg_slow = make_segment(stage_id="stage-1", seq=20)
    seg_fast = make_segment(stage_id="stage-2", seq=30)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg_slow))
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-2:audio", seg_fast))

    # Esperamos a que la sala rápida publique primero
    start = asyncio.get_event_loop().time()
    while len(fake_redis.published) < 1:
        if asyncio.get_event_loop().time() - start > 1.0:
            break
        await asyncio.sleep(0.01)

    first_published = CaptionEvent.from_json(fake_redis.published[0][1])
    # La sala 2 debió salir primero
    assert first_published.stage_id == "stage-2"
    assert first_published.revision == 30

    published_all = await wait_for_published(fake_redis, 2, timeout=1.0)
    await transcriber.close()

    assert len(published_all) == 2
    second_published = CaptionEvent.from_json(published_all[1][1])
    assert second_published.stage_id == "stage-1"


# 12. Una cola llena incrementa queue_overflows
@pytest.mark.asyncio
async def test_full_queue_increments_queue_overflows() -> None:
    fake_redis = FakeRedis()
    # Cola muy chica: tamaño 2
    settings = TranscriberSettings(bus_enabled=True, bus_queue_size=2)
    # El engine se retrasa para que la cola se sature
    engine = StubEngine(delay_by_stage={"stage-overflow": 0.5})
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    # Enviar 5 segmentos rápidamente a la misma sala
    for i in range(1, 6):
        seg = make_segment(
            stage_id="stage-overflow",
            seq=i,
            t0_ms=i * 100,
            t1_ms=i * 100 + 50,
            is_clause_end=False,
        )
        fake_redis.pubsub_instance.push(make_pmessage("stage:stage-overflow:audio", seg))

    await asyncio.sleep(0.1)
    await transcriber.close()

    assert transcriber.stats.queue_overflows >= 1


# 13. close() cancela tareas y cierra las conexiones
@pytest.mark.asyncio
async def test_close_cancels_tasks_and_closes_connections() -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine(delay_by_stage={"stage-1": 1.0})
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    await transcriber.start()
    seg = make_segment(stage_id="stage-1", seq=99)
    fake_redis.pubsub_instance.push(make_pmessage("stage:stage-1:audio", seg))
    await asyncio.sleep(0.05)

    await transcriber.close()

    assert transcriber._status == "stopped"
    assert transcriber._redis_connected is False
    assert transcriber._main_task is None
    assert len(transcriber._stage_workers) == 0
    assert fake_redis.pubsub_instance.closed is True


# 14. Las pruebas HTTP existentes continúan pasando con el bus desactivado por defecto
def test_http_endpoint_and_health_work_with_bus_disabled_by_default() -> None:
    with TestClient(app) as client:
        # 1. Health incluye bus con enabled=False y redis_connected=False
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "bus" in data
        assert data["bus"]["enabled"] is False
        assert data["bus"]["redis_connected"] is False

        # 2. Endpoint HTTP /v1/audio/segments sigue funcionando
        engine = StubEngine()
        app.dependency_overrides[get_engine] = lambda: engine
        headers = {
            "content-type": "audio/L16;rate=16000;channels=1",
            "x-stage-id": "stage-1",
            "x-is-clause-end": "true",
        }
        res = client.post("/v1/audio/segments", content=b"\x00\x01" * 800, headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert "events" in body
        assert len(body["events"]) >= 1
    app.dependency_overrides.clear()


def test_health_reports_exact_bus_shape_when_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = FakeRedis()
    settings = TranscriberSettings(bus_enabled=True)
    engine = StubEngine()
    transcriber = RedisTranscriber(settings, engine, redis_client=fake_redis)

    import transcriber.main as main_mod
    monkeypatch.setattr(main_mod, "_bus", transcriber)
    from transcriber.config import get_settings
    app.dependency_overrides[get_settings] = lambda: settings

    try:
        with TestClient(app) as client:
            resp = client.get("/health")
            assert resp.status_code == 200
            bus_data = resp.json()["bus"]
            assert bus_data == {
                "enabled": True,
                "status": "connected",
                "redis_connected": True,
                "queued": 0,
                "processed": 0,
                "published": 0,
                "silent": 0,
                "failures": 0,
                "queue_overflows": 0,
                "drafts_coalesced": 0,
                "last_error": None,
            }
    finally:
        app.dependency_overrides.clear()
