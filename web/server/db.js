import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

export function openDatabase(filename) {
  if (filename !== ':memory:') mkdirSync(dirname(filename), { recursive: true });
  const db = new DatabaseSync(filename);
  db.exec('PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL; PRAGMA busy_timeout = 5000');
  db.exec(`
    CREATE TABLE IF NOT EXISTS operators (
      id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
      password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS logins (
      token_hash TEXT PRIMARY KEY, operator_id INTEGER NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
      csrf_token TEXT NOT NULL, expires_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS sessions (
      id INTEGER PRIMARY KEY, stage_id INTEGER NOT NULL CHECK(stage_id BETWEEN 1 AND 10),
      title TEXT NOT NULL, source_type TEXT NOT NULL CHECK(source_type IN ('obs','file','microphone')),
      permissions TEXT NOT NULL, created_by INTEGER NOT NULL REFERENCES operators(id),
      started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, ended_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS one_active_session_per_stage
      ON sessions(stage_id) WHERE ended_at IS NULL;
    CREATE TABLE IF NOT EXISTS captions (
      id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
      clause_id TEXT NOT NULL, lang TEXT NOT NULL CHECK(lang IN ('es','en')),
      t0_ms INTEGER NOT NULL CHECK(t0_ms >= 0),
      t1_ms INTEGER NOT NULL CHECK(t1_ms > t0_ms),
      text TEXT NOT NULL, original TEXT NOT NULL DEFAULT '', provider TEXT,
      revision INTEGER NOT NULL DEFAULT 0, tier INTEGER NOT NULL DEFAULT 0,
      emitted_at_ms INTEGER, audio_end_wall_ms INTEGER,
      UNIQUE(session_id, clause_id, lang)
    );
    CREATE INDEX IF NOT EXISTS captions_by_session_lang_time
      ON captions(session_id, lang, t0_ms, id);
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY, value TEXT NOT NULL
    );
  `);
  return db;
}

export function pruneExpired(db, now = Date.now()) {
  db.prepare('DELETE FROM logins WHERE expires_at <= ?').run(now);
  // A session without retention loses its captions when it ends. Retained
  // captions expire 30 days after the session finishes.
  const cutoff = new Date(now - 30 * 24 * 60 * 60 * 1000).toISOString();
  db.prepare(`DELETE FROM captions WHERE session_id IN (
    SELECT id FROM sessions WHERE ended_at IS NOT NULL AND
    (json_extract(permissions, '$.retain') = 0 OR datetime(ended_at) < datetime(?))
  )`).run(cutoff);
}

export function sessionRow(row) {
  return row && { ...row, stage_id: String(row.stage_id), permissions: JSON.parse(row.permissions) };
}

export function captionRows(db, sessionId, lang, limit = null) {
  const query = `SELECT c.clause_id, c.session_id, s.stage_id, c.lang, c.t0_ms, c.t1_ms,
    c.text, c.original, c.provider, c.revision, c.tier, c.emitted_at_ms,
    c.audio_end_wall_ms, 'committed' AS state
    FROM captions c JOIN sessions s ON s.id = c.session_id
    WHERE c.session_id = ? AND c.lang = ? ORDER BY c.t0_ms, c.id`;
  const rows = db.prepare(query).all(sessionId, lang).map((row) => ({ ...row, stage_id: String(row.stage_id) }));
  return limit == null ? rows : rows.slice(-limit);
}
