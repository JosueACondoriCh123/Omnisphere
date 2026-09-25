'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createCloudKeyStore } = require('./cloud-key.cjs');

const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (value) => Buffer.from(value),
  decryptString: (buffer) => buffer.toString(),
};

test('cloud key requires validation and never returns the secret', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-cloud-'));
  try {
    let rejectedModel = '';
    let offline = false;
    const requests = [];
    const store = createCloudKeyStore({ userData: folder, safeStorage,
      request: async (url, options) => {
        requests.push([url, options.headers['x-goog-api-key']]);
        if (offline) throw new Error('network unavailable');
        const rejected = url.endsWith(rejectedModel) && Boolean(rejectedModel);
        return { ok: !rejected, status: rejected ? 404 : 200 };
      } });
    assert.equal(store.status().state, 'missing');
    assert.equal(store.current(), null);
    const ready = await store.validateAndSave('valid-test-key');
    assert.equal(ready.state, 'ready');
    assert.equal(JSON.stringify(ready).includes('valid-test-key'), false);
    assert.equal(store.current(), 'valid-test-key');
    assert.deepEqual(requests.map(([url]) => url.split('/').at(-1)),
      ['gemini-3.5-transcribe-live', 'gemini-3.5-flash-lite']);
    assert.ok(requests.every(([, key]) => key === 'valid-test-key'));
    rejectedModel = 'gemini-3.5-flash-lite';
    const rejected = await store.validateAndSave('invalid-test-key');
    assert.equal(rejected.state, 'invalid');
    assert.equal(store.current(), 'valid-test-key');
    offline = true;
    const unavailable = await store.validateAndSave('new-test-key');
    assert.equal(unavailable.state, 'offline');
    assert.equal(store.current(), 'valid-test-key');
    const restored = createCloudKeyStore({ userData: folder, safeStorage });
    assert.equal(restored.status().state, 'ready');
    assert.equal(restored.current(), 'valid-test-key');
    assert.equal(store.remove().state, 'missing');
    assert.equal(store.current(), null);
  } finally { fs.rmSync(folder, { recursive: true, force: true }); }
});
