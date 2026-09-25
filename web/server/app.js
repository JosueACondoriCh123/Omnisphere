import { createServer } from 'node:http';
import { createHash, randomBytes, scryptSync, timingSafeEqual } from 'node:crypto';
import { openDatabase, pruneExpired, sessionRow, captionRows } from './db.js';

const SESSION_MS = 12 * 60 * 60 * 1000;
const PUBLIC_ORIGINS = (process.env.OMNISTAGE_PUBLIC_CORS_ORIGINS || '')
  .split(',').map((origin) => origin.trim()).filter(Boolean);
const fail = (status, detail) => Object.assign(new Error(detail), { status });
const hash = (value) => createHash('sha256').update(value).digest('hex');

function passwordHash(password, salt = randomBytes(16).toString('hex')) {
  return `${salt}:${scryptSync(password, salt, 64).toString('hex')}`;
}

function validPassword(password, encoded) {
  if (typeof password !== 'string' || !encoded) return false;
  const [salt, value] = encoded.split(':');
  const actual = Buffer.from(passwordHash(password, salt).split(':')[1], 'hex');
  const expected = Buffer.from(value || '', 'hex');
  return expected.length === actual.length && timingSafeEqual(actual, expected);
}

function send(res, status, body, headers = {}) {
  const json = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'x-content-type-options': 'nosniff',
    ...headers,
  });
  res.end(json);
}

async function readJson(req) {
  let body = '';
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 1024 * 1024) throw fail(413, 'Solicitud demasiado grande.');
  }
  try { return body ? JSON.parse(body) : {}; }
  catch { throw fail(400, 'JSON inválido.'); }
}

function sessionIdFrom(pathname) {
  const match = /^\/api\/operator\/sessions\/(\d+)(?:\/(end|captions|export))?$/.exec(pathname);
  return match && { id: Number(match[1]), action: match[2] || '' };
}

function textExport(captions, lang, format) {
  const text = captions.map((caption) => caption[lang] || caption.text);
  if (format === 'txt') return text.join('\n');
  const clock = (value, separator) => {
    const ms = Math.max(0, value);
    const h = Math.floor(ms / 3600000);
    const m = Math.floor(ms / 60000) % 60;
    const s = Math.floor(ms / 1000) % 60;
    return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}${separator}${String(ms % 1000).padStart(3, '0')}`;
  };
  const separator = format === 'vtt' ? '.' : ',';
  const cues = captions.map((caption, index) => `${format === 'srt' ? `${index + 1}\n` : ''}${clock(caption.t0_ms, separator)} --> ${clock(caption.t1_ms, separator)}\n${text[index]}\n`).join('\n');
  return `${format === 'vtt' ? 'WEBVTT\n\n' : ''}${cues}`;
}

function sameOrigin(req) {
  const origin = req.headers.origin;
  if (!origin) return true;
  try {
    const url = new URL(origin);
    return url.host === req.headers.host || ['localhost', '127.0.0.1'].includes(url.hostname)
      && ['localhost', '127.0.0.1'].includes((req.headers.host || '').split(':')[0]);
  }
  catch { return false; }
}

function publicCors(req) {
  const origin = req.headers.origin;
  return PUBLIC_ORIGINS.includes(origin) ? { 'access-control-allow-origin': origin, vary: 'Origin' } : {};
}

function socketFrame(value) {
  const payload = Buffer.from(JSON.stringify(value));
  let header;
  if (payload.length < 126) header = Buffer.from([0x81, payload.length]);
  else if (payload.length <= 65535) header = Buffer.from([0x81, 126, payload.length >> 8, payload.length & 255]);
  else {
    header = Buffer.alloc(10);
    header[0] = 0x81;
    header[1] = 127;
    header.writeBigUInt64BE(BigInt(payload.length), 2);
  }
  return Buffer.concat([header, payload]);
}

export function createApp({ db = openDatabase(process.env.OMNISTAGE_DB_PATH || 'data/omnistage.sqlite') } = {}) {
  pruneExpired(db);
  const sockets = new Map();
  const sessionFor = (req) => {
    const token = /(?:^|;\s*)omni_session=([^;]+)/.exec(req.headers.cookie || '')?.[1];
    if (!token) throw fail(401, 'Iniciá sesión de operador.');
    const row = db.prepare(`SELECT o.id, o.email, l.csrf_token FROM logins l
      JOIN operators o ON o.id = l.operator_id WHERE l.token_hash = ? AND l.expires_at > ?`)
      .get(hash(token), Date.now());
    if (!row) throw fail(401, 'Sesión vencida.');
    return row;
  };
  const protectedWrite = (req) => {
    const user = sessionFor(req);
    if (!sameOrigin(req) || req.headers['x-csrf-token'] !== user.csrf_token) {
      throw fail(403, 'Token de seguridad inválido.');
    }
    return user;
  };
  const broadcast = (stage, lang, value) => {
    for (const socket of sockets.get(`${stage}:${lang}`) || []) {
      if (!socket.destroyed) socket.write(socketFrame(value));
    }
  };

  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
      const path = url.pathname;
      const method = req.method;
      if (method === 'GET' && path === '/healthz') return send(res, 200, { ok: true });
      if (method === 'OPTIONS' && path === '/api/stages') {
        return send(res, 204, null, { ...publicCors(req), 'access-control-allow-methods': 'GET, OPTIONS' });
      }
      if (method === 'GET' && path === '/api/time') return send(res, 200, { wall_ms: Date.now() }, publicCors(req));
      if (method === 'GET' && path === '/api/stages') {
        const rows = db.prepare('SELECT id, stage_id, title FROM sessions WHERE ended_at IS NULL ORDER BY stage_id').all();
        return send(res, 200, { items: rows.map((row) => ({ stage_id: String(row.stage_id), name: `Sala ${row.stage_id}`, session: row.title, session_id: row.id, languages: ['es', 'en'] })) }, publicCors(req));
      }
      if (method === 'GET' && path === '/api/operator/bootstrap-status') {
        return send(res, 200, { needs_setup: !db.prepare('SELECT id FROM operators LIMIT 1').get() });
      }
      if (method === 'POST' && path === '/api/operator/bootstrap') {
        if (!sameOrigin(req)) throw fail(403, 'Origen inválido.');
        const { email, password } = await readJson(req);
        if (!validCredentials(email, password)) throw fail(400, 'Correo o contraseña inválidos; usá al menos 12 caracteres.');
        const result = db.prepare(`INSERT INTO operators(email, password_hash)
          SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM operators)`)
          .run(email.trim().toLowerCase(), passwordHash(password));
        if (!result.changes) throw fail(409, 'El operador inicial ya existe.');
        return send(res, 201, { ok: true });
      }
      if (method === 'POST' && path === '/api/operator/login') {
        if (!sameOrigin(req)) throw fail(403, 'Origen inválido.');
        const { email, password } = await readJson(req);
        const user = typeof email === 'string' ? db.prepare('SELECT * FROM operators WHERE email = ?').get(email.trim().toLowerCase()) : null;
        if (!user || !validPassword(password, user.password_hash)) throw fail(401, 'Credenciales inválidas.');
        const token = randomBytes(32).toString('hex');
        const csrf = randomBytes(24).toString('hex');
        db.prepare('INSERT INTO logins(token_hash, operator_id, csrf_token, expires_at) VALUES (?, ?, ?, ?)')
          .run(hash(token), user.id, csrf, Date.now() + SESSION_MS);
        return send(res, 200, { id: user.id, email: user.email, csrf_token: csrf }, {
          'set-cookie': `omni_session=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${SESSION_MS / 1000}`,
        });
      }
      if (method === 'GET' && path === '/api/operator/me') return send(res, 200, sessionFor(req));
      if (method === 'POST' && path === '/api/operator/logout') {
        protectedWrite(req);
        const token = /(?:^|;\s*)omni_session=([^;]+)/.exec(req.headers.cookie || '')?.[1];
        db.prepare('DELETE FROM logins WHERE token_hash = ?').run(hash(token));
        return send(res, 200, { ok: true }, { 'set-cookie': 'omni_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0' });
      }
      if (method === 'POST' && path === '/api/operator/users') {
        protectedWrite(req);
        const { email, password } = await readJson(req);
        if (!validCredentials(email, password)) throw fail(400, 'Correo o contraseña inválidos; usá al menos 12 caracteres.');
        try {
          const result = db.prepare('INSERT INTO operators(email, password_hash) VALUES (?, ?)')
            .run(email.trim().toLowerCase(), passwordHash(password));
          return send(res, 201, { id: Number(result.lastInsertRowid), email: email.trim().toLowerCase() });
        } catch (error) {
          if (String(error).includes('UNIQUE')) throw fail(409, 'El operador ya existe.');
          throw error;
        }
      }
      if (method === 'GET' && path === '/api/metrics/stages') {
        sessionFor(req);
        const rows = db.prepare('SELECT id, stage_id, source_type FROM sessions WHERE ended_at IS NULL ORDER BY stage_id').all();
        return send(res, 200, { items: rows.map((row) => ({ stage_id: String(row.stage_id), active_session_id: row.id, source_type: row.source_type, stream_up: false, audio_up: false, transcriber_up: false, provider: null, latency_ms: null, alarms: [] })) });
      }
      if (method === 'GET' && path === '/api/operator/provider') {
        sessionFor(req);
        return send(res, 200, { mode: db.prepare("SELECT value FROM settings WHERE key = 'provider_mode'").get()?.value || 'auto', stages: {} });
      }
      if (method === 'PUT' && path === '/api/operator/provider') {
        protectedWrite(req);
        const { mode } = await readJson(req);
        if (!['auto', 'cloud', 'local'].includes(mode)) throw fail(400, 'Modo inválido.');
        db.prepare("INSERT INTO settings(key, value) VALUES ('provider_mode', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value").run(mode);
        return send(res, 200, { mode, stages: {} });
      }
      if (method === 'GET' && path === '/api/operator/sessions') {
        sessionFor(req);
        const rows = db.prepare('SELECT * FROM sessions ORDER BY id DESC LIMIT 200').all().map(sessionRow);
        return send(res, 200, { items: rows });
      }
      if (method === 'POST' && path === '/api/operator/sessions') {
        const user = protectedWrite(req);
        const body = await readJson(req);
        const stage = Number(body.stage_id);
        const title = String(body.title || '').trim();
        const permissions = body.permissions;
        if (!Number.isInteger(stage) || stage < 1 || stage > 10 || !title || title.length > 200 || !['obs', 'file', 'microphone'].includes(body.source_type)
          || !permissions || typeof permissions !== 'object' || !String(permissions.evidence_reference || '').trim()) {
          throw fail(400, 'Datos de sesión inválidos.');
        }
        const allowed = ['capture', 'transcribe', 'translate', 'cloud', 'publish', 'retain', 'train'];
        const cleanPermissions = Object.fromEntries(allowed.map((key) => [key, permissions[key] === true]));
        cleanPermissions.evidence_reference = String(permissions.evidence_reference).trim().slice(0, 500);
        try {
          const result = db.prepare('INSERT INTO sessions(stage_id, title, source_type, permissions, created_by) VALUES (?, ?, ?, ?, ?)')
            .run(stage, title, body.source_type, JSON.stringify(cleanPermissions), user.id);
          const row = sessionRow(db.prepare('SELECT * FROM sessions WHERE id = ?').get(result.lastInsertRowid));
          for (const lang of ['es', 'en']) broadcast(stage, lang, { type: 'stream_started', session_id: row.id });
          return send(res, 201, row);
        } catch (error) {
          if (String(error).includes('UNIQUE')) throw fail(409, 'La sala ya tiene una sesión activa.');
          throw error;
        }
      }
      const route = sessionIdFrom(path);
      if (route) {
        const row = db.prepare('SELECT * FROM sessions WHERE id = ?').get(route.id);
        if (!row) throw fail(404, 'Sesión no encontrada.');
        if (method === 'POST' && route.action === 'end') {
          protectedWrite(req);
          db.prepare("UPDATE sessions SET ended_at = ? WHERE id = ? AND ended_at IS NULL")
            .run(new Date().toISOString(), route.id);
          pruneExpired(db);
          for (const lang of ['es', 'en']) broadcast(row.stage_id, lang, { type: 'stream_stopped', session_id: row.id });
          return send(res, 200, sessionRow(db.prepare('SELECT * FROM sessions WHERE id = ?').get(route.id)));
        }
        if (method === 'POST' && route.action === 'captions') {
          protectedWrite(req);
          if (row.ended_at) throw fail(409, 'La sesión ya terminó.');
          const body = await readJson(req);
          const lang = body.lang;
          const clause = String(body.clause_id || '').trim();
          const start = Number(body.t0_ms);
          const end = Number(body.t1_ms);
          const text = String(body.text || '').trim();
          if (!['es', 'en'].includes(lang) || !clause || clause.length > 100 || !Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start < 0 || end <= start || !text || text.length > 10000) {
            throw fail(400, 'Subtítulo inválido.');
          }
          const result = db.prepare(`INSERT INTO captions(session_id, clause_id, lang, t0_ms, t1_ms, text, original, provider, revision, tier, emitted_at_ms, audio_end_wall_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(session_id, clause_id, lang) DO NOTHING`)
            .run(row.id, clause, lang, start, end, text, String(body.original || ''), body.provider || null,
              Number.isInteger(body.revision) ? body.revision : 0, Number.isInteger(body.tier) ? body.tier : 0,
              Number.isSafeInteger(body.emitted_at_ms) ? body.emitted_at_ms : Date.now(),
              Number.isSafeInteger(body.audio_end_wall_ms) ? body.audio_end_wall_ms : null);
          if (!result.changes) throw fail(409, 'La cláusula ya fue guardada.');
          const caption = captionRows(db, row.id, lang).find((item) => item.clause_id === clause);
          broadcast(row.stage_id, lang, { type: 'caption', ...caption });
          return send(res, 201, caption);
        }
        if (method === 'GET' && route.action === 'captions') {
          sessionFor(req);
          const lang = url.searchParams.get('lang') === 'en' ? 'en' : 'es';
          return send(res, 200, { session: sessionRow(row), captions: captionRows(db, row.id, lang) });
        }
        if (method === 'GET' && route.action === 'export') {
          sessionFor(req);
          const lang = url.searchParams.get('lang') === 'en' ? 'en' : 'es';
          const format = url.searchParams.get('format');
          if (!['srt', 'vtt', 'txt'].includes(format)) throw fail(400, 'Formato inválido.');
          const content = textExport(captionRows(db, row.id, lang), lang, format);
          const filename = `nerdearla_2026_stage${row.stage_id}_sesion${row.id}.${format}`;
          res.writeHead(200, {
            'content-type': `${format === 'vtt' ? 'text/vtt' : 'text/plain'}; charset=utf-8`,
            'content-disposition': `attachment; filename="${filename}"`,
            'cache-control': 'no-store', 'x-content-type-options': 'nosniff',
          });
          return res.end(content);
        }
      }
      throw fail(404, 'Ruta no encontrada.');
    } catch (error) {
      if (!res.headersSent) send(res, error.status || 500, { detail: error.status ? error.message : 'Error interno.' });
      if (!error.status) console.error(error);
    }
  });

  server.on('upgrade', (req, socket) => {
    try {
      const path = new URL(req.url, 'http://localhost').pathname;
      const match = /^\/ws\/stages\/(10|[1-9])\/(es|en)$/.exec(path);
      const origin = req.headers.origin;
      if (!match || !req.headers['sec-websocket-key'] || (origin && !sameOrigin(req) && !PUBLIC_ORIGINS.includes(origin))) {
        socket.write('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n');
        socket.destroy();
        return;
      }
      const key = createHash('sha1').update(req.headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').digest('base64');
      socket.write(`HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ${key}\r\n\r\n`);
      const [stage, lang] = [Number(match[1]), match[2]];
      const channel = `${stage}:${lang}`;
      if (!sockets.has(channel)) sockets.set(channel, new Set());
      sockets.get(channel).add(socket);
      socket.on('close', () => sockets.get(channel)?.delete(socket));
      socket.on('error', () => sockets.get(channel)?.delete(socket));
      socket.on('data', (data) => { if ((data[0] & 0x0f) === 0x8) socket.end(); });
      const active = db.prepare('SELECT id FROM sessions WHERE stage_id = ? AND ended_at IS NULL').get(stage);
      if (active) socket.write(socketFrame({ type: 'snapshot', session_id: active.id, captions: captionRows(db, active.id, lang, 100) }));
      else socket.write(socketFrame({ type: 'stream_stopped' }));
    } catch { socket.destroy(); }
  });

  // The optional public listener exposes only audience routes. Both listeners
  // share the same websocket subscribers and the same database connection.
  const publicServer = createServer((req, res) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (req.method === 'GET' && ['/healthz', '/api/time', '/api/stages'].includes(path)) {
      server.emit('request', req, res);
    } else if (req.method === 'OPTIONS' && path === '/api/stages') {
      server.emit('request', req, res);
    } else {
      send(res, 404, { detail: 'Ruta no encontrada.' });
    }
  });
  publicServer.on('upgrade', (req, socket, head) => {
    const path = new URL(req.url, 'http://localhost').pathname;
    if (path.startsWith('/ws/stages/')) server.emit('upgrade', req, socket, head);
    else socket.destroy();
  });

  return { server, publicServer, db, close: () => new Promise((resolve, reject) => {
    for (const clients of sockets.values()) for (const socket of clients) socket.destroy();
    const listeners = [server, publicServer].filter((item) => item.listening);
    Promise.all(listeners.map((item) => new Promise((done, bad) => item.close((error) => error ? bad(error) : done()))))
      .then(resolve, reject);
  }) };
}

function validCredentials(email, password) {
  return typeof email === 'string' && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())
    && typeof password === 'string' && password.length >= 12 && password.length <= 1024;
}
