from types import SimpleNamespace

from fastapi.testclient import TestClient

import transcriber.main as main_mod
from transcriber.config import TranscriberSettings
from transcriber.config import get_settings as config_get_settings
from transcriber.engine import GeminiEngine


class ProbeModels:
    async def get(self, *, model: str):
        return SimpleNamespace(name=model)


def test_readyz_rejects_a_missing_api_key(monkeypatch) -> None:
    settings = TranscriberSettings(gemini_api_key="", bus_enabled=False)
    monkeypatch.setattr(main_mod, "_engine", None)
    monkeypatch.setattr(main_mod, "_bus", None)
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    main_mod.app.dependency_overrides[config_get_settings] = lambda: settings
    try:
        with TestClient(main_mod.app) as client:
            response = client.get("/readyz")
        assert response.status_code == 503
        assert response.json()["api_key_configured"] is False
    finally:
        main_mod.app.dependency_overrides.clear()


def test_readyz_accepts_a_valid_model_probe(monkeypatch) -> None:
    settings = TranscriberSettings(gemini_api_key="test-key", bus_enabled=False)
    client = SimpleNamespace(aio=SimpleNamespace(models=ProbeModels()))
    engine = GeminiEngine(settings, client=client)
    monkeypatch.setattr(main_mod, "_engine", engine)
    monkeypatch.setattr(main_mod, "_bus", None)
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    main_mod.app.dependency_overrides[config_get_settings] = lambda: settings
    try:
        with TestClient(main_mod.app) as test_client:
            response = test_client.get("/readyz")
        assert response.status_code == 200
        assert response.json()["engine"]["ready"] is True
    finally:
        main_mod.app.dependency_overrides.clear()
