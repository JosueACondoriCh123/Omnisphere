from fastapi.testclient import TestClient

from app.main import app, settings

client = TestClient(app)


def test_health() -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


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
