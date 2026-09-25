from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import transcriber.main as main_mod
from transcriber.config import TranscriberSettings
from transcriber.config import get_settings as config_get_settings
from transcriber.context import StageContext
from transcriber.engine import StubTranscriptionEngine


def test_settings_defaults() -> None:
    settings = TranscriberSettings()
    assert settings.transcription_engine == "gemini"
    assert settings.allow_stub_engine is False


def test_stub_engine_requires_allow_flag() -> None:
    settings = TranscriberSettings(transcription_engine="stub", allow_stub_engine=False)
    with pytest.raises(RuntimeError, match="ALLOW_STUB_ENGINE=true is required"):
        StubTranscriptionEngine(settings)


@pytest.mark.asyncio
async def test_stub_engine_deterministic_output() -> None:
    settings = TranscriberSettings(transcription_engine="stub", allow_stub_engine=True)
    engine = StubTranscriptionEngine(settings)
    context = StageContext(id="1", languages=["es", "en"])

    # Draft (is_clause_end=False)
    draft_result = await engine.process(b"\x00" * 100, context, is_clause_end=False)
    assert draft_result.original == "desplegamos"
    assert draft_result.captions["es"] == "desplegamos"
    assert draft_result.captions["en"] == "we deploy"
    assert draft_result.is_silent is False

    # Commit (is_clause_end=True)
    commit_result = await engine.process(b"\x00" * 100, context, is_clause_end=True)
    assert commit_result.original == "desplegamos el pod"
    assert commit_result.captions["es"] == "desplegamos el pod"
    assert commit_result.captions["en"] == "we deploy the pod"
    assert "pod" in commit_result.preserved_terms


def test_health_reports_engine_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = TranscriberSettings(
        transcription_engine="stub",
        allow_stub_engine=True,
        bus_enabled=False,
    )
    engine = StubTranscriptionEngine(settings)
    monkeypatch.setattr(main_mod, "_engine", engine)
    monkeypatch.setattr(main_mod, "_bus", None)
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    main_mod.app.dependency_overrides[config_get_settings] = lambda: settings
    try:
        with TestClient(main_mod.app) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["engine_mode"] == "stub"
        assert data["engine"]["mode"] == "stub"
    finally:
        main_mod.app.dependency_overrides.clear()


def test_readyz_with_stub_engine_no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = TranscriberSettings(
        gemini_api_key="",
        transcription_engine="stub",
        allow_stub_engine=True,
        bus_enabled=False,
    )
    engine = StubTranscriptionEngine(settings)
    monkeypatch.setattr(main_mod, "_engine", engine)
    monkeypatch.setattr(main_mod, "_bus", None)
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    main_mod.app.dependency_overrides[config_get_settings] = lambda: settings
    try:
        with TestClient(main_mod.app) as client:
            resp = client.get("/readyz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
    finally:
        main_mod.app.dependency_overrides.clear()
