"""Exercise the cloud caption handoff through storage and both live languages."""

import asyncio
import sys
import types
from dataclasses import replace

import pytest

from app.config import Settings
from app.context import ContextProvider
from app.fanout import CaptionFanout
from app.hybrid import HybridPipeline, StageRoute
from app.state import RuntimeState, WebSocketHub
from app.storage import SessionStore
from contracts.events import AudioSegment
from transcriber.local import LocalResult


class RecordingSocket:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def accept(self) -> None:
        pass

    async def send_json(self, payload: dict) -> None:
        self.messages.append(payload)


@pytest.mark.asyncio
async def test_cloud_caption_and_local_fallback_reach_archive_and_both_sockets(
    tmp_path, monkeypatch
) -> None:
    settings = Settings(
        db_path=str(tmp_path / "captions.db"), transport_mode="local",
        gemini_api_key="simulated-key", provider_mode="auto",
    )
    store = SessionStore(settings.db_path)
    session = store.start_session("1", permissions={
        "capture": True, "transcribe": True, "translate": True,
        "cloud": True, "publish": True, "retain": True,
    })
    runtime = RuntimeState()
    hub = WebSocketHub()
    context = ContextProvider(settings)
    fanout = CaptionFanout(settings, runtime, hub, context)
    fanout.store = store
    pipeline = HybridPipeline(settings, runtime, context, fanout, store)

    async def translate(text, _glossary):
        return "es", text, "Hello from cloud", 2, 2

    async def local_result(_pcm, _glossary):
        return LocalResult("Sigue local", "es", "Sigue local", "Continuing locally")

    monkeypatch.setattr(pipeline.cloud_translation, "translate", translate)
    monkeypatch.setattr(pipeline.local, "process", local_result)

    async def snapshot(lang):
        return {"type": "snapshot", "stage_id": "1", "lang": lang,
                "captions": store.captions(session["id"], lang)}

    sockets = {lang: RecordingSocket() for lang in ("es", "en")}
    try:
        for lang, socket in sockets.items():
            await hub.connect("1", lang, socket, lambda lang=lang: snapshot(lang))

        route = StageRoute("1", session_id=session["id"], provider="cloud")
        pipeline.routes["1"] = route
        route.local_task = asyncio.create_task(pipeline._local_worker(route))
        first = AudioSegment.from_pcm(
            "1", 1, 100, 500, b"\x00\x00" * 6400, True, -20,
            audio_end_wall_ms=123456,
        )
        await pipeline.feed_segment(first)
        await pipeline._cloud_text(route, "Hola desde nube", True)

        es = store.captions(session["id"], "es")
        en = store.captions(session["id"], "en")
        assert len(es) == len(en) == 1
        assert es[0]["provider"] == en[0]["provider"] == "gemini-live"
        assert es[0]["clause_id"] == en[0]["clause_id"]
        assert es[0]["audio_end_wall_ms"] == 123456
        assert [item["type"] for item in sockets["es"].messages] == ["snapshot", "caption"]
        assert [item["text"] for item in sockets["en"].messages[1:]] == ["Hello from cloud"]

        # Replayed cloud events must not duplicate archive rows or socket messages.
        await pipeline._publish(
            replace(first, session_id=session["id"]), "Hola desde nube", "es",
            "Hola desde nube", "Hello from cloud", "gemini-live", final=True,
        )
        assert len(store.captions(session["id"], "es")) == 1
        assert len(sockets["es"].messages) == 2

        second = AudioSegment.from_pcm("1", 2, 700, 1100, b"\x00\x00" * 6400,
                                       True, -20)
        await pipeline.feed_segment(second)
        pipeline._mark_cloud_failed(route, "simulated disconnect")
        for _ in range(100):
            if len(store.captions(session["id"], "es")) == 2:
                break
            await asyncio.sleep(0.01)
        assert route.provider == "local"
        assert [item["provider"] for item in store.captions(session["id"], "es")] == [
            "gemini-live", "local-gemma4",
        ]
        assert len(store.captions(session["id"], "en")) == 2
        for socket in sockets.values():
            assert [item["type"] for item in socket.messages] == [
                "snapshot", "caption", "caption",
            ]
    finally:
        await pipeline.close()
        store.close()


@pytest.mark.asyncio
async def test_cloud_connection_error_never_exposes_the_key(tmp_path, monkeypatch, caplog) -> None:
    settings = Settings(
        db_path=str(tmp_path / "captions.db"), transport_mode="local",
        gemini_api_key="private-test-key", provider_mode="cloud",
    )
    store = SessionStore(settings.db_path)
    runtime = RuntimeState()
    context = ContextProvider(settings)
    fanout = CaptionFanout(settings, runtime, WebSocketHub(), context)
    pipeline = HybridPipeline(settings, runtime, context, fanout, store)

    def reject_connection(**_kwargs):
        raise RuntimeError("Gemini rejected private-test-key")

    fake_genai = types.ModuleType("google.genai")
    fake_genai.Client = lambda **_kwargs: types.SimpleNamespace(  # type: ignore[attr-defined]
        aio=types.SimpleNamespace(live=types.SimpleNamespace(connect=reject_connection)))
    fake_genai.types = types.SimpleNamespace(  # type: ignore[attr-defined]
        LiveConnectConfig=lambda **_kwargs: object(),
        AudioTranscriptionConfig=lambda **_kwargs: object(),
    )
    import google

    monkeypatch.setattr(google, "genai", fake_genai, raising=False)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    route = StageRoute("1", provider="cloud")
    try:
        await pipeline._cloud_worker(route)
        assert route.provider == "local"
        assert "private-test-key" not in caplog.text
        assert "private-test-key" not in str(runtime.transcriber_error)
    finally:
        await pipeline.close()
        store.close()
