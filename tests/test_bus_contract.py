from __future__ import annotations

import pytest

from app.config import Settings
from app.context import ContextProvider
from app.fanout import CaptionFanout
from app.state import RuntimeState
from contracts.events import AudioSegment, CaptionEvent, CaptionText, TraceStamp, now_ms


class RecordingHub:
    def __init__(self) -> None:
        self.items: list[tuple[str, str, dict]] = []

    async def publish(self, stage_id: str, lang: str, payload: dict) -> int:
        self.items.append((stage_id, lang, payload))
        return 1


def test_audio_segment_round_trip_preserves_pcm_and_clause_boundary() -> None:
    pcm = b"\x00\x00\xff\x7f" * 20
    segment = AudioSegment.from_pcm("1", 7, 100, 180, pcm, True, -18.5)
    decoded = AudioSegment.from_json(segment.to_json())

    assert decoded.pcm() == pcm
    assert decoded.is_clause_end is True
    assert (decoded.t0_ms, decoded.t1_ms) == (100, 180)


@pytest.mark.asyncio
async def test_caption_fanout_partitions_text_by_language() -> None:
    hub = RecordingHub()
    runtime = RuntimeState()
    fanout = CaptionFanout(
        Settings(), runtime, hub, ContextProvider(Settings())  # type: ignore[arg-type]
    )
    event = CaptionEvent(
        stage_id="1",
        t0_ms=0,
        t1_ms=900,
        state="committed",
        revision=3,
        tier=2,
        lang_detected="es",
        text=CaptionText(original="Hola", es="Hola", en="Hello"),
        emitted_at_ms=now_ms(),
        traces=[TraceStamp.make("vad", "1", 3).__dict__],
    )

    delivered = await fanout.dispatch(event.to_json())

    assert delivered == 2
    assert {(stage, lang, item["text"]) for stage, lang, item in hub.items} == {
        ("1", "es", "Hola"),
        ("1", "en", "Hello"),
    }
    assert all(item[2]["traces"][-1]["hop"] == "fanout" for item in hub.items)
    assert all(item[2]["type"] == "caption" for item in hub.items)
    assert all(item[2]["state"] == "committed" for item in hub.items)
    assert set(hub.items[0][2]) == {
        "type",
        "stage_id",
        "t0_ms",
        "t1_ms",
        "state",
        "revision",
        "tier",
        "lang",
        "text",
        "original",
        "emitted_at_ms",
        "traces",
    }
    snapshot = await runtime.caption_snapshot("1", "es")
    assert len(snapshot) == 1
    assert snapshot[0]["original"] == "Hola"
