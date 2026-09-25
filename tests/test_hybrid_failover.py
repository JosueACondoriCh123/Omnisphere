import asyncio
import sys
import types

import pytest

import app.hybrid as hybrid_module
from app.config import Settings
from app.context import ContextProvider
from app.fanout import CaptionFanout
from app.hybrid import HybridPipeline, StageRoute
from app.state import RuntimeState, WebSocketHub
from app.storage import SessionStore
from contracts.events import AudioSegment
from transcriber.local import LocalResult


@pytest.mark.asyncio
async def test_cloud_to_local_replays_pending_clause_once(tmp_path, monkeypatch):
    settings = Settings(
        db_path=str(tmp_path / "pilot.db"), transport_mode="local",
        gemini_api_key="test-key", provider_mode="auto",
    )
    store = SessionStore(settings.db_path)
    store.start_session("1", "Autorizada", permissions={
        "capture": True, "transcribe": True, "translate": True,
        "cloud": True, "publish": True, "retain": True,
    })
    runtime = RuntimeState()
    context = ContextProvider(settings)
    fanout = CaptionFanout(settings, runtime, WebSocketHub(), context)
    fanout.store = store
    pipeline = HybridPipeline(settings, runtime, context, fanout, store)

    async def idle_cloud(_route):
        await asyncio.Event().wait()

    async def local_result(_pcm, _glossary):
        return LocalResult("Hola", "es", "Hola", "Hello")

    monkeypatch.setattr(pipeline, "_cloud_worker", idle_cloud)
    monkeypatch.setattr(pipeline.local, "process", local_result)
    segment = AudioSegment.from_pcm("1", 1, 100, 500, b"\x00\x00" * 6400, True, -20)
    await pipeline.feed_segment(segment)
    assert pipeline.routes["1"].provider == "cloud"
    assert store.captions(store.current_session("1")["id"], "es") == []
    await pipeline.set_mode("local")
    for _ in range(100):
        if store.captions(store.current_session("1")["id"], "es"):
            break
        await asyncio.sleep(0.01)
    captions = store.captions(store.current_session("1")["id"], "es")
    assert len(captions) == 1
    assert captions[0]["provider"] == "local-gemma4"
    assert len(store.captions(store.current_session("1")["id"], "en")) == 1
    session_id = store.current_session("1")["id"]
    store.set_permissions(session_id, {"capture": True, "transcribe": True,
                                       "translate": True, "publish": True, "retain": False})
    await pipeline.feed_segment(AudioSegment.from_pcm("1", 2, 700, 900, b"\x00\x00" * 3200, True, -20))
    await asyncio.sleep(0.02)
    assert store.captions(session_id, "es") == []
    await pipeline.close()
    store.close()


@pytest.mark.asyncio
async def test_cloud_final_waits_for_real_audio_segment_and_recovers(tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "pilot.db"), transport_mode="local",
                        gemini_api_key="test-key", provider_mode="auto")
    store = SessionStore(settings.db_path)
    session = store.start_session("1", "Autorizada", permissions={
        "capture": True, "transcribe": True, "translate": True,
        "cloud": True, "publish": True, "retain": True,
    })
    runtime = RuntimeState()
    fanout = CaptionFanout(settings, runtime, WebSocketHub(), ContextProvider(settings))
    fanout.store = store
    pipeline = HybridPipeline(settings, runtime, ContextProvider(settings), fanout, store)

    async def idle_cloud(_route):
        await asyncio.Event().wait()

    async def translate(_text, _glossary):
        return "es", "Hola", "Hello", 2, 2

    monkeypatch.setattr(pipeline, "_cloud_worker", idle_cloud)
    monkeypatch.setattr(pipeline.cloud_translation, "translate", translate)
    route = await pipeline.route("1")
    await pipeline._cloud_text(route, "Hola", True)
    assert store.captions(session["id"], "es") == []
    assert len(route.cloud_finals) == 1
    segment = AudioSegment.from_pcm("1", 1, 100, 500, b"\x00\x00" * 6400,
                                    True, -20, audio_end_wall_ms=123456)
    await pipeline.feed_segment(segment)
    captions = store.captions(session["id"], "es")
    assert len(captions) == 1
    assert captions[0]["audio_end_wall_ms"] == 123456
    assert len(store.captions(session["id"], "en")) == 1
    await pipeline._cloud_text(route, "late duplicate", True)
    assert len(store.captions(session["id"], "es")) == 1
    await pipeline.set_mode("local")
    route.failed_cloud = True
    route.cloud_retry_at = 0
    pipeline.mode = "auto"
    await pipeline.feed_frame("1", 600, b"\x00\x00" * 1600)
    assert route.provider == "cloud"
    await pipeline.close()
    store.close()


@pytest.mark.asyncio
async def test_old_session_caption_cannot_enter_new_session(tmp_path):
    settings = Settings(db_path=str(tmp_path / "pilot.db"), transport_mode="local",
                        provider_mode="local")
    store = SessionStore(settings.db_path)
    permissions = {"capture": True, "transcribe": True, "translate": True,
                   "publish": True, "retain": True}
    first = store.start_session("1", permissions=permissions)
    runtime = RuntimeState()
    context = ContextProvider(settings)
    fanout = CaptionFanout(settings, runtime, WebSocketHub(), context)
    fanout.store = store
    pipeline = HybridPipeline(settings, runtime, context, fanout, store)
    old_segment = AudioSegment.from_pcm("1", 1, 100, 500, b"\x00\x00" * 6400,
                                        True, -20, session_id=first["id"])
    store.end_session("1")
    second = store.start_session("1", permissions=permissions)
    await pipeline._publish(old_segment, "Hola", "es", "Hola", "Hello",
                            "local-gemma4", final=True)
    assert store.captions(second["id"], "es") == []
    await pipeline.close()
    store.close()


@pytest.mark.asyncio
async def test_live_session_renews_before_limit_without_fabricated_caption(tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "pilot.db"), transport_mode="local",
                        gemini_api_key="test-key", provider_mode="cloud")
    store = SessionStore(settings.db_path)
    runtime = RuntimeState()
    context = ContextProvider(settings)
    fanout = CaptionFanout(settings, runtime, WebSocketHub(), context)
    fanout.store = store
    pipeline = HybridPipeline(settings, runtime, context, fanout, store)
    route = StageRoute("1", provider="cloud")
    connected = 0
    stream_ends = 0

    class FakeSession:
        async def __aenter__(self):
            nonlocal connected
            connected += 1
            return self

        async def __aexit__(self, *_args):
            return None

        async def send_realtime_input(self, **kwargs):
            nonlocal stream_ends
            stream_ends += int(kwargs.get("audio_stream_end", False))

        async def receive(self):
            while True:
                await asyncio.sleep(1)
                if False:
                    yield None

    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = lambda **_kwargs: types.SimpleNamespace(  # type: ignore[attr-defined]
        aio=types.SimpleNamespace(live=types.SimpleNamespace(connect=lambda **_kwargs: FakeSession()))
    )
    fake_genai.types = types.SimpleNamespace(  # type: ignore[attr-defined]
        LiveConnectConfig=lambda **_kwargs: object(),
        AudioTranscriptionConfig=lambda **_kwargs: object(),
    )
    import google

    monkeypatch.setattr(google, "genai", fake_genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setattr(hybrid_module, "LIVE_RENEWAL_SECONDS", 0.02)
    monkeypatch.setattr(hybrid_module, "LIVE_FINAL_GRACE_SECONDS", 0.02)
    task = asyncio.create_task(pipeline._cloud_worker(route))
    for _ in range(100):
        if connected >= 2:
            break
        await asyncio.sleep(0.01)
    assert connected >= 2
    assert stream_ends >= 1
    assert store.list_sessions() == []
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await pipeline.close()
    store.close()


@pytest.mark.asyncio
async def test_local_confirmed_clauses_leave_pending_buffer(tmp_path, monkeypatch):
    settings = Settings(db_path=str(tmp_path / "pilot.db"), transport_mode="local",
                        provider_mode="local")
    store = SessionStore(settings.db_path)
    session = store.start_session("1", permissions={
        "capture": True, "transcribe": True, "translate": True,
        "publish": True, "retain": True,
    })
    runtime = RuntimeState()
    context = ContextProvider(settings)
    fanout = CaptionFanout(settings, runtime, WebSocketHub(), context)
    fanout.store = store
    pipeline = HybridPipeline(settings, runtime, context, fanout, store)

    async def local_result(_pcm, _glossary):
        return LocalResult("Hola", "es", "Hola", "Hello")

    monkeypatch.setattr(pipeline.local, "process", local_result)
    for index in range(4):
        await pipeline.feed_segment(AudioSegment.from_pcm(
            "1", index, index * 1000, index * 1000 + 500,
            b"\x00\x00" * 6400, True, -20,
        ))
        for _ in range(100):
            if len(store.captions(session["id"], "es")) == index + 1:
                break
            await asyncio.sleep(0.01)
    route = pipeline.routes["1"]
    assert not route.pending
    assert route.dropped_clauses == 0
    assert len(store.captions(session["id"], "en")) == 4
    await pipeline.close()
    store.close()
