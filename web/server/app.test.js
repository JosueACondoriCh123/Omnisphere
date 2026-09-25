import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createApp } from './app.js';
import { openDatabase } from './db.js';

function nextMessage(socket) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('WebSocket timeout')), 3000);
    socket.addEventListener('message', (event) => {
      clearTimeout(timer);
      resolve(JSON.parse(event.data));
    }, { once: true });
  });
}

test('SQLite persists operators, sessions and captions; public socket receives committed clauses', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'omnistage-db-'));
  const filename = join(dir, 'test.sqlite');
  const app = createApp({ db: openDatabase(filename) });
  let socket;
  try {
    await new Promise((resolve) => app.server.listen(0, '127.0.0.1', resolve));
    await new Promise((resolve) => app.publicServer.listen(0, '127.0.0.1', resolve));
    const base = `http://127.0.0.1:${app.server.address().port}`;
    const publicBase = `http://127.0.0.1:${app.publicServer.address().port}`;
    const json = async (path, options = {}, external = false) => {
      const response = await fetch(`${external ? publicBase : base}${path}`, options);
      return { status: response.status, body: await response.json(), response };
    };
    assert.deepEqual((await json('/api/operator/bootstrap-status')).body, { needs_setup: true });
    assert.equal((await json('/api/operator/bootstrap', { method: 'POST', body: JSON.stringify({ email: 'first@example.org', password: 'long-password-123' }) })).status, 201);
    assert.equal((await json('/api/operator/bootstrap', { method: 'POST', body: JSON.stringify({ email: 'other@example.org', password: 'long-password-123' }) })).status, 409);
    const login = await json('/api/operator/login', { method: 'POST', body: JSON.stringify({ email: 'first@example.org', password: 'long-password-123' }) });
    assert.equal(login.status, 200);
    const cookie = login.response.headers.get('set-cookie').split(';')[0];
    const headers = { cookie, 'x-csrf-token': login.body.csrf_token };
    assert.equal((await json('/api/operator/me', { headers })).body.email, 'first@example.org');
    assert.equal((await json('/api/operator/sessions', { method: 'POST', headers: { cookie }, body: '{}' })).status, 403);
    const created = await json('/api/operator/sessions', {
      method: 'POST', headers,
      body: JSON.stringify({ stage_id: '1', title: 'Charla SQLite', source_type: 'obs', permissions: { retain: true, evidence_reference: 'contrato-1' } }),
    });
    assert.equal(created.status, 201);
    const id = created.body.id;
    assert.equal((await json('/api/stages', {}, true)).body.items[0].session_id, id);
    assert.equal((await json('/api/operator/me', { headers }, true)).status, 404);
    socket = new WebSocket(`ws://127.0.0.1:${app.publicServer.address().port}/ws/stages/1/es`);
    const snapshot = await nextMessage(socket);
    assert.deepEqual(snapshot, { type: 'snapshot', session_id: id, captions: [] });
    const received = nextMessage(socket);
    const caption = await json(`/api/operator/sessions/${id}/captions`, {
      method: 'POST', headers,
      body: JSON.stringify({ clause_id: 'c-1', lang: 'es', t0_ms: 1000, t1_ms: 2500, text: 'Hola mundo.' }),
    });
    assert.equal(caption.status, 201);
    assert.equal((await received).text, 'Hola mundo.');
    assert.equal((await json(`/api/operator/sessions/${id}/captions?lang=es`, { headers })).body.captions.length, 1);
    const exportResponse = await fetch(`${base}/api/operator/sessions/${id}/export?lang=es&format=srt`, { headers });
    assert.match(await exportResponse.text(), /00:00:01,000 --> 00:00:02,500\nHola mundo/);
    assert.equal((await json(`/api/operator/sessions/${id}/end`, { method: 'POST', headers })).status, 200);
    assert.equal((await json('/api/stages', {}, true)).body.items.length, 0);
    assert.equal((await json(`/api/operator/sessions/${id}/captions?lang=es`, { headers })).body.captions.length, 1);
    const temporary = await json('/api/operator/sessions', {
      method: 'POST', headers,
      body: JSON.stringify({ stage_id: '2', title: 'Sin conservación', source_type: 'obs', permissions: { retain: false, evidence_reference: 'contrato-2' } }),
    });
    assert.equal(temporary.status, 201);
    assert.equal((await json(`/api/operator/sessions/${temporary.body.id}/captions`, {
      method: 'POST', headers,
      body: JSON.stringify({ clause_id: 'c-2', lang: 'es', t0_ms: 0, t1_ms: 1000, text: 'Temporal.' }),
    })).status, 201);
    assert.equal((await json(`/api/operator/sessions/${temporary.body.id}/end`, { method: 'POST', headers })).status, 200);
    assert.equal((await json(`/api/operator/sessions/${temporary.body.id}/captions?lang=es`, { headers })).body.captions.length, 0);
    socket.close();
    await app.close();
    app.db.close();
    const reopened = openDatabase(filename);
    assert.equal(reopened.prepare('SELECT count(*) AS n FROM operators').get().n, 1);
    assert.equal(reopened.prepare('SELECT count(*) AS n FROM captions').get().n, 1);
    reopened.close();
  } finally {
    socket?.close();
    if (app.server.listening || app.publicServer.listening) await app.close();
    if (app.db.isOpen) app.db.close();
    rmSync(dir, { recursive: true, force: true });
  }
});
