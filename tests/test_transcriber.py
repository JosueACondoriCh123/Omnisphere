from __future__ import annotations

import base64
import json
import struct

import pytest
from fastapi.testclient import TestClient

from transcriber.audio import PCM_SAMPLE_RATE, pcm_duration_ms, pcm_to_wav
from transcriber.context import StageContext, decode_stage_context
from transcriber.engine import EngineUnavailable, SegmentResult, build_prompt, parse_response
from transcriber.main import app, get_engine

CONTEXT = {
    "id": "stage-1",
    "name": "Stage 1",
    "session": "Scaling eBPF observability",
    "languages": ["es", "en"],
    "glossary": ["Kubernetes", "Spring Boot", "OpenTelemetry"],
    "speakers": [{"name": "Sarah Connor"}],
}


def encode_context(data: dict) -> str:
    raw = json.dumps(data).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class StubEngine:
    def __init__(self, result: SegmentResult | None = None, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[int, bool]] = []

    async def process(self, pcm: bytes, context: StageContext, is_clause_end: bool):
        self.calls.append((len(pcm), is_clause_end))
        if self.error:
            raise self.error
        return self.result


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def use_engine(engine: StubEngine) -> None:
    app.dependency_overrides[get_engine] = lambda: engine


def post_segment(client: TestClient, pcm: bytes = b"\x00\x01" * 800, **overrides):
    headers = {
        "content-type": "audio/L16;rate=16000;channels=1",
        "x-stage-id": "stage-1",
        "x-is-clause-end": "true",
        "x-stage-context": encode_context(CONTEXT),
    }
    headers.update(overrides)
    return client.post("/v1/audio/segments", content=pcm, headers=headers)


# --- audio --------------------------------------------------------------------


def test_wav_header_declares_the_pcm_contract() -> None:
    pcm = b"\x00\x01" * 1000
    wav = pcm_to_wav(pcm)
    assert wav[:4] == b"RIFF"
    assert wav[8:12] == b"WAVE"
    assert len(wav) == len(pcm) + 44
    channels, sample_rate = struct.unpack("<HI", wav[22:28])
    assert channels == 1
    assert sample_rate == PCM_SAMPLE_RATE


def test_duration_matches_sixteen_kilohertz_mono() -> None:
    one_second = b"\x00\x00" * PCM_SAMPLE_RATE
    assert pcm_duration_ms(one_second) == 1000


# --- context ------------------------------------------------------------------


def test_context_header_round_trip() -> None:
    ctx = decode_stage_context(encode_context(CONTEXT), "stage-1")
    assert ctx.session == "Scaling eBPF observability"
    assert ctx.target_languages() == ["es", "en"]


def test_glossary_and_speakers_become_protected_terms() -> None:
    ctx = decode_stage_context(encode_context(CONTEXT), "stage-1")
    terms = ctx.protected_terms()
    # Without this, "Spring Boot" is rendered as "Bota de Primavera".
    assert "Spring Boot" in terms
    assert "Sarah Connor" in terms


def test_malformed_context_degrades_instead_of_failing() -> None:
    # A caption without terminology hints beats a 400 during a live talk.
    for bad in ("not-base64!!", base64.urlsafe_b64encode(b"[]").decode(), ""):
        ctx = decode_stage_context(bad, "stage-9")
        assert ctx.id == "stage-9"
        assert ctx.target_languages() == ["es"]


def test_languages_are_deduplicated_and_defaulted() -> None:
    assert StageContext(languages=["es", "ES", "en"]).target_languages() == ["es", "en"]
    assert StageContext(languages=[]).target_languages() == ["es"]


# --- prompt -------------------------------------------------------------------


def test_prompt_carries_agenda_terminology() -> None:
    ctx = decode_stage_context(encode_context(CONTEXT), "stage-1")
    prompt = build_prompt(ctx, ["es", "en"], is_clause_end=True)
    assert "Kubernetes" in prompt
    assert "Sarah Connor" in prompt
    assert "es, en" in prompt


def test_prompt_warns_when_segment_was_force_cut() -> None:
    ctx = decode_stage_context(encode_context(CONTEXT), "stage-1")
    assert "mid-sentence" in build_prompt(ctx, ["es"], is_clause_end=False)
    assert "mid-sentence" not in build_prompt(ctx, ["es"], is_clause_end=True)


# --- response parsing ---------------------------------------------------------


def test_parse_response_keeps_requested_languages_only() -> None:
    raw = json.dumps(
        {
            "original": "we deploy the pod",
            "source_language": "en",
            "captions": [
                {"lang": "es", "text": "desplegamos el pod"},
                {"lang": "en", "text": "we deploy the pod"},
                {"lang": "pt", "text": "ignored"},
            ],
            "preserved_terms": ["pod"],
        }
    )
    result = parse_response(raw, ["es", "en"])
    assert set(result.captions) == {"es", "en"}
    assert result.preserved_terms == ("pod",)


def test_missing_language_falls_back_to_the_original() -> None:
    raw = json.dumps(
        {"original": "hola", "source_language": "es", "captions": [{"lang": "es", "text": "hola"}]}
    )
    result = parse_response(raw, ["es", "en"])
    # Untranslated text beats a gap on screen.
    assert result.captions["en"] == "hola"


def test_empty_transcription_is_reported_as_silent() -> None:
    assert parse_response(json.dumps({"original": "  ", "source_language": ""}), ["es"]).is_silent


# --- endpoint -----------------------------------------------------------------


def test_clause_end_publishes_one_commit_per_language(client: TestClient) -> None:
    use_engine(
        StubEngine(
            SegmentResult(
                original="we deploy the pod",
                source_language="en",
                captions={"es": "desplegamos el pod", "en": "we deploy the pod"},
                preserved_terms=("pod",),
            )
        )
    )
    events = post_segment(client).json()["events"]
    assert [e["lang"] for e in events] == ["es", "en"]
    assert {e["type"] for e in events} == {"commit"}
    assert events[0]["text"] == "desplegamos el pod"
    assert events[0]["payload"]["preserved_terms"] == ["pod"]


def test_force_cut_segment_publishes_a_draft(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="and then we", source_language="en", captions={"es": "y entonces"})))
    events = post_segment(client, **{"x-is-clause-end": "false"}).json()["events"]
    # Not a finished clause, so it must not be styled as settled text.
    assert {e["type"] for e in events} == {"draft"}
    assert all(e["is_clause_end"] is False for e in events)


def test_sequences_increase_per_stage(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="uno", source_language="es", captions={"es": "uno", "en": "one"})))
    first = post_segment(client).json()["events"]
    second = post_segment(client).json()["events"]
    assert second[0]["seq"] > first[-1]["seq"]


def test_silence_publishes_nothing(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="   ", source_language="")))
    assert post_segment(client).json()["events"] == []


def test_engine_failure_returns_503_so_the_worker_degrades(client: TestClient) -> None:
    use_engine(StubEngine(error=EngineUnavailable("quota exhausted")))
    # 503 is what raises transcriber_socket_down on the operations dashboard.
    assert post_segment(client).status_code == 503


def test_invalid_stage_id_is_rejected(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="x", source_language="es", captions={"es": "x"})))
    assert post_segment(client, **{"x-stage-id": "../etc/passwd"}).status_code == 400


def test_empty_body_is_rejected(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="x", source_language="es", captions={"es": "x"})))
    assert post_segment(client, pcm=b"").status_code == 400


def test_oversized_segment_is_rejected(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="x", source_language="es", captions={"es": "x"})))
    huge = b"\x00" * (41 * PCM_SAMPLE_RATE * 2)
    assert post_segment(client, pcm=huge).status_code == 413


def test_missing_context_header_still_produces_spanish(client: TestClient) -> None:
    use_engine(StubEngine(SegmentResult(original="hola", source_language="es", captions={"es": "hola"})))
    events = post_segment(client, **{"x-stage-context": ""}).json()["events"]
    assert [e["lang"] for e in events] == ["es"]


def test_health_reports_the_configured_model(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["service"] == "nerdearla-transcriber"
    assert body["model"]
