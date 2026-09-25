from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import main
from app.public import public_app
from app.storage import SessionStore


def _caption(stage: str, t0: int, session_id: str) -> dict:
    return {
        "type": "caption", "stage_id": stage, "lang": "es", "state": "committed",
        "t0_ms": t0, "t1_ms": t0 + 500, "text": "Hola", "original": "Hola",
        "revision": 1, "provider": "local-gemma4", "session_id": session_id,
    }


def test_commits_survive_reopen_and_deduplicate_provider_failover(tmp_path):
    path = tmp_path / "sessions.db"
    db = SessionStore(path)
    session = db.start_session("1", "Charla", permissions={"publish": True})
    first, created = db.commit_caption(_caption("1", 100, session["id"]))
    assert created and first["session_id"] == session["id"]
    replay = {**_caption("1", 100, session["id"]), "provider": "gemini-live"}
    _, created = db.commit_caption(replay)
    assert not created
    _, created = db.commit_caption({**replay, "t0_ms": 120, "t1_ms": 600})
    assert not created
    db.close()
    reopened = SessionStore(path)
    reopened.set_setting("provider_mode", "local")
    assert len(reopened.captions(session["id"], "es")) == 1
    assert reopened.captions(session["id"], "es")[0]["provider"] == "local-gemma4"
    reopened.close()
    final = SessionStore(path)
    assert final.get_setting("provider_mode") == "local"
    final.close()


def test_bilingual_commit_is_atomic_before_publish(tmp_path):
    db = SessionStore(tmp_path / "atomic.db")
    session = db.start_session("1", permissions={"publish": True})
    es = _caption("1", 100, session["id"])
    en = {**es, "lang": "en", "text": "Hello", "session_id": "wrong-session"}
    with pytest.raises(ValueError, match="session"):
        db.commit_captions([es, en])
    assert db.captions(session["id"], "es") == []
    en["session_id"] = session["id"]
    saved = db.commit_captions([es, en])
    assert all(inserted for _, inserted in saved)
    assert len(db.captions(session["id"], "es")) == 1
    assert len(db.captions(session["id"], "en")) == 1
    db.close()


def test_preflight_can_fill_session_started_by_obs_and_retention_is_configurable(tmp_path):
    db = SessionStore(tmp_path / "sessions.db", retention_days=7)
    early = db.start_session("2")
    prepared = db.start_session("2", "Charla preparada", "microphone", {"capture": True})
    assert prepared["id"] == early["id"]
    assert prepared["title"] == "Charla preparada"
    assert prepared["permissions"] == {"capture": True}
    expiry = datetime.fromisoformat(prepared["expires_at"])
    assert timedelta(days=6, hours=23) < expiry - datetime.now(UTC) < timedelta(days=7)
    db.close()


def test_operator_archive_requires_login_and_public_origin_rejects_controls(tmp_path, monkeypatch):
    db = SessionStore(tmp_path / "sessions.db")
    monkeypatch.setattr(main, "store", db)
    local = TestClient(main.app)
    public = TestClient(public_app)
    assert local.get("/api/operator/sessions").status_code == 401
    assert public.get("/api/operator/sessions").status_code == 404
    assert public.get("/admin").status_code == 404
    assert public.get("/metrics").status_code == 404

    created = local.post("/api/operator/bootstrap", json={"email": "op@example.com", "password": "long-password-123"})
    assert created.status_code == 201
    login = local.post("/api/operator/login", json={"email": "op@example.com", "password": "long-password-123"})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert local.post("/api/operator/sessions", json={}).status_code == 403
    session = local.post("/api/operator/sessions", headers={"x-csrf-token": csrf}, json={
        "stage_id": "1", "title": "Charla", "source_type": "obs",
        "permissions": {"capture": True, "transcribe": True, "translate": True,
                        "publish": True, "retain": True, "evidence_reference": "consent-1"},
    })
    assert session.status_code == 201
    session_id = session.json()["id"]
    db.commit_caption(_caption("1", 100, session_id))
    exported = local.get(f"/api/operator/sessions/{session_id}/export?lang=es&format=srt")
    assert exported.status_code == 200
    assert "00:00:00,100 --> 00:00:00,600" in exported.text
    assert local.post(f"/api/operator/sessions/{session_id}/end", headers={"x-csrf-token": csrf}).status_code == 200
    second = local.post("/api/operator/sessions", headers={"x-csrf-token": csrf}, json={
        "stage_id": "1", "title": "Otra charla", "source_type": "obs",
        "permissions": {"capture": True, "transcribe": True, "translate": True,
                        "publish": True, "retain": True, "evidence_reference": "consent-2"},
    })
    assert second.status_code == 201
    assert local.post(f"/api/operator/sessions/{session_id}/end", headers={"x-csrf-token": csrf}).json()["status"] == "already_ended"
    assert db.current_session("1")["id"] == second.json()["id"]
    db.close()


def test_public_catalog_hides_unpublished_session(tmp_path, monkeypatch):
    db = SessionStore(tmp_path / "private.db")
    monkeypatch.setattr(main, "store", db)
    db.start_session("1", "Ponencia privada", permissions={"publish": False})
    public = TestClient(public_app)
    item = next(row for row in public.get("/api/stages").json()["items"] if row["stage_id"] == "1")
    assert item["session"] != "Ponencia privada"
    assert item["active_session_id"] is None
    db.close()
