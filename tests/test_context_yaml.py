from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.context import ContextProvider


@pytest.mark.asyncio
async def test_context_provider_loads_agenda_yaml() -> None:
    base_dir = Path(__file__).resolve().parent.parent
    agenda_file = base_dir / "evaluation" / "corpus" / "agenda.yaml"

    settings = Settings(stage_context_file=str(agenda_file))
    provider = ContextProvider(settings)

    # Test stage-en
    ctx_en = await provider.get("stage-en")
    assert ctx_en.id == "stage-en"
    assert "Keynote" in ctx_en.name
    assert "Kubernetes" in ctx_en.glossary
    assert "OpenTelemetry" in ctx_en.glossary
    assert ctx_en.languages == ["en"]
    assert len(ctx_en.speakers) == 1
    assert ctx_en.speakers[0]["name"] == "Sarah Connor"

    # Test stage-es
    ctx_es = await provider.get("stage-es")
    assert ctx_es.id == "stage-es"
    assert "Spring Boot" in ctx_es.glossary
    assert "Kafka" in ctx_es.glossary
    assert ctx_es.languages == ["es"]

    # Test stage-spanglish
    ctx_sp = await provider.get("stage-spanglish")
    assert ctx_sp.id == "stage-spanglish"
    assert "deployar" in ctx_sp.glossary
    assert "rollbackear" in ctx_sp.glossary
    assert "troubleshooting" in ctx_sp.glossary

    # Test nonexistent stage fallback
    ctx_unknown = await provider.get("stage-unknown")
    assert ctx_unknown.id == "stage-unknown"
    assert ctx_unknown.name == "Stage stage-unknown"
    assert ctx_unknown.languages == ["es"]
    assert ctx_unknown.glossary == []
