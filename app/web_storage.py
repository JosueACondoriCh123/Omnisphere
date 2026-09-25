"""Separate SQLite projection containing only data published to the web."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


PUBLIC_STAGE_FIELDS = (
    "stage_id", "name", "session", "languages", "active_session_id",
    "stream_up", "audio_up", "provider_ready",
)
PUBLIC_CAPTION_FIELDS = (
    "type", "stage_id", "session_id", "clause_id", "lang", "state",
    "t0_ms", "t1_ms", "revision", "tier", "text", "emitted_at_ms",
)


class WebStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=5000")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS stages (
                stage_id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                active_session_id TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS captions (
                session_id TEXT NOT NULL,
                clause_id TEXT NOT NULL,
                lang TEXT NOT NULL CHECK (lang IN ('es', 'en')),
                stage_id TEXT NOT NULL,
                t0_ms INTEGER NOT NULL,
                t1_ms INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (session_id, clause_id, lang)
            );
            CREATE INDEX IF NOT EXISTS web_captions_order
                ON captions (session_id, lang, t0_ms, t1_ms);
            CREATE INDEX IF NOT EXISTS web_captions_expiry ON captions (expires_at);
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def replace_stages(self, items: list[dict[str, Any]]) -> None:
        """Keep a public-only catalog; private session names never enter this file."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            stage_ids = []
            for item in items:
                public = {field: item.get(field) for field in PUBLIC_STAGE_FIELDS}
                stage_id = str(public["stage_id"])
                public["stage_id"] = stage_id
                stage_ids.append(stage_id)
                self._db.execute(
                    """INSERT INTO stages (stage_id, payload_json, active_session_id, updated_at)
                    VALUES (?, ?, ?, ?) ON CONFLICT(stage_id) DO UPDATE SET
                    payload_json=excluded.payload_json,
                    active_session_id=excluded.active_session_id,
                    updated_at=excluded.updated_at""",
                    (stage_id, json.dumps(public, ensure_ascii=False),
                     public["active_session_id"], now),
                )
            if stage_ids:
                placeholders = ",".join("?" for _ in stage_ids)
                self._db.execute(
                    f"DELETE FROM stages WHERE stage_id NOT IN ({placeholders})", stage_ids
                )
            else:
                self._db.execute("DELETE FROM stages")
            self._db.commit()

    def stages(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT payload_json FROM stages").fetchall()
            items = [json.loads(row["payload_json"]) for row in rows]
            return sorted(items, key=lambda item: (not str(item["stage_id"]).isdigit(),
                                                   int(item["stage_id"]) if str(item["stage_id"]).isdigit()
                                                   else str(item["stage_id"])))

    def record_caption(self, payload: dict[str, Any], expires_at: str) -> bool:
        if payload.get("state") != "committed":
            raise ValueError("only confirmed captions enter the web database")
        public = {field: payload.get(field) for field in PUBLIC_CAPTION_FIELDS}
        public["type"] = "caption"
        public["state"] = "committed"
        public["tier"] = public["tier"] or 2
        public["revision"] = public["revision"] or 0
        public["emitted_at_ms"] = public["emitted_at_ms"] or 0
        if not all(public.get(field) for field in ("stage_id", "session_id", "clause_id", "lang")):
            raise ValueError("caption needs stage, session, clause and language")
        with self._lock:
            cur = self._db.execute(
                """INSERT OR IGNORE INTO captions
                (session_id, clause_id, lang, stage_id, t0_ms, t1_ms, payload_json, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (public["session_id"], public["clause_id"], public["lang"],
                 public["stage_id"], public["t0_ms"], public["t1_ms"],
                 json.dumps(public, ensure_ascii=False), expires_at),
            )
            self._db.commit()
            return cur.rowcount > 0

    def snapshot(self, stage_id: str, lang: str) -> dict[str, Any]:
        with self._lock:
            stage = self._db.execute(
                "SELECT active_session_id FROM stages WHERE stage_id=?", (stage_id,)
            ).fetchone()
            session_id = stage["active_session_id"] if stage else None
            rows = self._db.execute(
                """SELECT payload_json FROM captions
                WHERE session_id=? AND stage_id=? AND lang=? AND expires_at>=?
                ORDER BY t0_ms, t1_ms""",
                (session_id, stage_id, lang, datetime.now(UTC).isoformat()),
            ).fetchall() if session_id else []
            return {
                "type": "snapshot", "stage_id": stage_id, "lang": lang,
                "session_id": session_id,
                "captions": [json.loads(row["payload_json"]) for row in rows],
            }

    def revoke_session(self, session_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM captions WHERE session_id=?", (session_id,))
            self._db.commit()

    def purge_expired(self) -> int:
        with self._lock:
            cur = self._db.execute(
                "DELETE FROM captions WHERE expires_at < ?", (datetime.now(UTC).isoformat(),)
            )
            self._db.commit()
            return cur.rowcount
