"""Durable session, caption and operator storage for a single event host."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SessionStore:
    def __init__(self, path: str | Path, retention_days: int = 30) -> None:
        self.path = Path(path)
        self.retention_days = retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                stage_id TEXT NOT NULL,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'obs',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                expires_at TEXT NOT NULL,
                permissions_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS sessions_stage ON sessions(stage_id, started_at DESC);
            CREATE TABLE IF NOT EXISTS captions (
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                clause_id TEXT NOT NULL,
                lang TEXT NOT NULL,
                t0_ms INTEGER NOT NULL,
                t1_ms INTEGER NOT NULL,
                revision INTEGER NOT NULL,
                text TEXT NOT NULL,
                original TEXT NOT NULL,
                provider TEXT NOT NULL,
                emitted_at_ms INTEGER NOT NULL,
                audio_end_wall_ms INTEGER,
                PRIMARY KEY(session_id, clause_id, lang)
            );
            CREATE INDEX IF NOT EXISTS captions_order ON captions(session_id, lang, t0_ms);
            CREATE TABLE IF NOT EXISTS operators (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                disabled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS operator_tokens (
                token_hash TEXT PRIMARY KEY,
                operator_id TEXT NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operator_id TEXT NOT NULL,
                action TEXT NOT NULL,
                target TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(captions)")}
        if "audio_end_wall_ms" not in columns:
            self._db.execute("ALTER TABLE captions ADD COLUMN audio_end_wall_ms INTEGER")
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM runtime_settings WHERE key=?", (key,)).fetchone()
            return str(row["value"]) if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO runtime_settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
            )
            self._db.commit()

    def current_session(self, stage_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM sessions WHERE stage_id=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (stage_id,),
            ).fetchone()
            return self._session(row) if row else None

    @staticmethod
    def _session(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["permissions"] = json.loads(result.pop("permissions_json"))
        return result

    def start_session(
        self,
        stage_id: str,
        title: str = "",
        source_type: str = "obs",
        permissions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            active = self.current_session(stage_id)
            if active:
                if permissions and not active["permissions"]:
                    self._db.execute(
                        "UPDATE sessions SET title=?, source_type=?, permissions_json=? WHERE id=?",
                        (title or active["title"], source_type,
                         json.dumps(permissions, ensure_ascii=False), active["id"]),
                    )
                    self._db.commit()
                    return self.current_session(stage_id) or active
                return active
            session_id = uuid.uuid4().hex
            started = datetime.now(UTC)
            self._db.execute(
                "INSERT INTO sessions VALUES (?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    session_id,
                    stage_id,
                    title or f"Sala {stage_id}",
                    source_type,
                    started.isoformat(),
                    (started + timedelta(days=self.retention_days)).isoformat(),
                    json.dumps(permissions or {}, ensure_ascii=False),
                ),
            )
            self._db.commit()
            return self.current_session(stage_id) or {}

    def end_session(self, stage_id: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE sessions SET ended_at=? WHERE stage_id=? AND ended_at IS NULL",
                (_now(), stage_id),
            )
            self._db.commit()

    def list_sessions(self, stage_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if stage_id is None:
                rows = self._db.execute("SELECT * FROM sessions ORDER BY started_at DESC").fetchall()
            else:
                rows = self._db.execute(
                    "SELECT * FROM sessions WHERE stage_id=? ORDER BY started_at DESC", (stage_id,)
                ).fetchall()
            return [self._session(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            return self._session(row) if row else None

    def set_permissions(self, session_id: str, permissions: dict[str, Any]) -> bool:
        with self._lock:
            cur = self._db.execute(
                "UPDATE sessions SET permissions_json=? WHERE id=?",
                (json.dumps(permissions, ensure_ascii=False), session_id),
            )
            if cur.rowcount and not permissions.get("retain", False):
                self._db.execute("DELETE FROM captions WHERE session_id=?", (session_id,))
            self._db.commit()
            return cur.rowcount > 0

    def commit_caption(
        self, payload: dict[str, Any], *, _commit: bool = True
    ) -> tuple[dict[str, Any], bool]:
        """Upsert one confirmed caption before publication, idempotent across providers."""
        if payload.get("state") != "committed":
            raise ValueError("only committed captions may be persisted")
        with self._lock:
            session = self.current_session(str(payload["stage_id"]))
            if session is None:
                session = self.start_session(str(payload["stage_id"]))
            session_id = str(payload.get("session_id") or session["id"])
            if session_id != session["id"]:
                raise ValueError("caption session does not match active stage session")
            clause_id = str(
                payload.get("clause_id")
                or uuid.uuid5(uuid.NAMESPACE_URL, f"{session_id}:{payload['t0_ms']}").hex
            )
            result = {
                **payload,
                "session_id": session_id,
                "clause_id": clause_id,
                "provider": str(payload.get("provider") or "legacy"),
            }
            prior = self._db.execute(
                "SELECT revision FROM captions WHERE session_id=? AND clause_id=? AND lang=?",
                (session_id, clause_id, payload["lang"]),
            ).fetchone()
            if prior is not None:
                return result, False
            overlap = self._db.execute(
                """SELECT 1 FROM captions WHERE session_id=? AND lang=?
                AND t0_ms < ? AND t1_ms > ? LIMIT 1""",
                (session_id, payload["lang"], int(payload["t1_ms"]), int(payload["t0_ms"])),
            ).fetchone()
            if overlap is not None:
                return result, False
            self._db.execute(
                """INSERT INTO captions
                (session_id, clause_id, lang, t0_ms, t1_ms, revision, text, original, provider,
                 emitted_at_ms, audio_end_wall_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id,
                    clause_id,
                    payload["lang"],
                    int(payload["t0_ms"]),
                    int(payload["t1_ms"]),
                    int(payload.get("revision") or 0),
                    str(payload.get("text") or ""),
                    str(payload.get("original") or ""),
                    result["provider"],
                    int(payload.get("emitted_at_ms") or 0),
                    int(payload["audio_end_wall_ms"]) if payload.get("audio_end_wall_ms") is not None else None,
                ),
            )
            if _commit:
                self._db.commit()
            return result, True

    def commit_captions(
        self, payloads: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], bool]]:
        """Commit both languages in one transaction before either is emitted."""
        if not payloads:
            return []
        with self._lock:
            stage_id = str(payloads[0]["stage_id"])
            if any(str(item["stage_id"]) != stage_id for item in payloads):
                raise ValueError("caption batch mixes stages")
            if self.current_session(stage_id) is None:
                self.start_session(stage_id)
            self._db.execute("SAVEPOINT caption_batch")
            try:
                results = [self.commit_caption(item, _commit=False) for item in payloads]
                self._db.execute("RELEASE SAVEPOINT caption_batch")
                self._db.commit()
                return results
            except Exception:
                self._db.execute("ROLLBACK TO SAVEPOINT caption_batch")
                self._db.execute("RELEASE SAVEPOINT caption_batch")
                raise

    def captions(self, session_id: str, lang: str) -> list[dict[str, Any]]:
        with self._lock:
            session = self.get_session(session_id)
            if session is None:
                return []
            rows = self._db.execute(
                "SELECT * FROM captions WHERE session_id=? AND lang=? ORDER BY t0_ms, t1_ms",
                (session_id, lang),
            ).fetchall()
            return [
                {"type": "caption", "stage_id": session["stage_id"], "state": "committed", "tier": 2,
                 "traces": [], **dict(row)}
                for row in rows
            ]

    def purge_expired(self) -> int:
        with self._lock:
            cur = self._db.execute("DELETE FROM sessions WHERE expires_at < ?", (_now(),))
            self._db.execute("DELETE FROM operator_tokens WHERE expires_at < ?", (_now(),))
            self._db.commit()
            return cur.rowcount

    @staticmethod
    def _password_hash(password: str, salt: bytes | None = None) -> str:
        salt = salt or os.urandom(16)
        digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
        return f"{salt.hex()}:{digest.hex()}"

    def has_operators(self) -> bool:
        with self._lock:
            return self._db.execute("SELECT 1 FROM operators LIMIT 1").fetchone() is not None

    def create_operator(self, email: str, password: str) -> str:
        if len(password) < 12:
            raise ValueError("password must contain at least 12 characters")
        operator_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO operators(id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (operator_id, email.strip().lower(), self._password_hash(password), _now()),
            )
            self._db.commit()
        return operator_id

    def authenticate(self, email: str, password: str) -> dict[str, str] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, email, password_hash FROM operators WHERE email=? AND disabled=0",
                (email.strip().lower(),),
            ).fetchone()
            if row is None:
                return None
            try:
                salt_hex, expected = row["password_hash"].split(":", 1)
                actual = self._password_hash(password, bytes.fromhex(salt_hex)).split(":", 1)[1]
            except ValueError:
                return None
            if not secrets.compare_digest(actual, expected):
                return None
            return {"id": row["id"], "email": row["email"]}

    def issue_token(self, operator_id: str) -> str:
        raw = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        expires = (datetime.now(UTC) + timedelta(hours=12)).isoformat()
        with self._lock:
            self._db.execute(
                "INSERT INTO operator_tokens VALUES (?, ?, ?)", (token_hash, operator_id, expires)
            )
            self._db.commit()
        return raw

    def operator_for_token(self, token: str) -> dict[str, str] | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self._lock:
            row = self._db.execute(
                """SELECT o.id, o.email FROM operator_tokens t JOIN operators o ON o.id=t.operator_id
                WHERE t.token_hash=? AND t.expires_at>? AND o.disabled=0""",
                (token_hash, _now()),
            ).fetchone()
            return dict(row) if row else None

    def revoke_token(self, token: str) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM operator_tokens WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
            self._db.commit()

    def audit(self, operator_id: str, action: str, target: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO audit_log(operator_id, action, target, created_at) VALUES (?, ?, ?, ?)",
                (operator_id, action, target, _now()),
            )
            self._db.commit()
