import pytest
from fastapi.testclient import TestClient

from app.main import app, runtime, settings, stage_metrics

client = TestClient(app)


def test_health() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_stage_catalog_comes_from_the_backend_context() -> None:
    items = client.get("/api/stages").json()["items"]
    by_id = {item["stage_id"]: item for item in items}
    assert by_id["1"]["name"] == "Sala 1"
    assert by_id["1"]["languages"] == ["es", "en"]
    assert len(items) == 10
    assert by_id["10"]["name"] == "Sala 10"


@pytest.mark.asyncio
async def test_active_stage_reports_and_clears_transcriber_alarm() -> None:
    old_paths = set(runtime.active_paths)
    old_up = runtime.transcriber_up
    old_error = runtime.transcriber_error
    try:
        runtime.active_paths = {"live/stage-1"}
        runtime.transcriber_up = False
        runtime.transcriber_error = "quota exhausted"
        down = await stage_metrics("1")
        assert down["transcriber_up"] is False
        assert "transcriber_socket_down" in {
            alarm["code"] for alarm in down["alarms"]
        }

        runtime.transcriber_up = True
        runtime.transcriber_error = None
        recovered = await stage_metrics("1")
        assert "transcriber_socket_down" not in {
            alarm["code"] for alarm in recovered["alarms"]
        }
    finally:
        runtime.active_paths = old_paths
        runtime.transcriber_up = old_up
        runtime.transcriber_error = old_error


def test_internal_event_requires_token() -> None:
    response = client.post(
        "/internal/stages/1/es/events",
        json={"type": "commit", "text": "Hola"},
    )
    assert response.status_code == 401


def test_partitioned_websocket_receives_its_event() -> None:
    with client.websocket_connect("/ws/stages/1/es") as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "snapshot"
        response = client.post(
            "/internal/stages/1/es/events",
            headers={"x-internal-token": settings.internal_token},
            json={
                "type": "commit",
                "text": "Hola, Nerdearla",
                "is_clause_end": True,
                "payload": {
                    "t0_ms": 100,
                    "t1_ms": 900,
                    "revision": 1,
                    "tier": 2,
                    "original": "Hola, Nerdearla",
                },
            },
        )
        assert response.status_code == 200
        assert response.json()["delivered"] == 1
        event = websocket.receive_json()
        assert event["type"] == "caption"
        assert event["state"] == "committed"
        assert event["text"] == "Hola, Nerdearla"
        assert event["stage_id"] == "1"
        assert event["lang"] == "es"

    with client.websocket_connect("/ws/stages/1/es") as websocket:
        snapshot = websocket.receive_json()
        assert snapshot["type"] == "snapshot"
        assert [caption["text"] for caption in snapshot["captions"]] == [
            "Hola, Nerdearla"
        ]
