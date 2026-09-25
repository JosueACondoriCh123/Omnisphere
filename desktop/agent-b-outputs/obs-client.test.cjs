'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { ObsClient } = require('./obs-client.cjs');

function sha(value) { return createHash('sha256').update(value).digest('base64'); }

test('OBS v5 authenticates locally and resolves request responses', async () => {
  const packets = [];
  class FakeSocket {
    constructor(url) {
      assert.equal(url, 'ws://127.0.0.1:4455');
      this.handlers = new Map();
      queueMicrotask(() => this.emit('message', { op: 0, d: {
        rpcVersion: 1, authentication: { salt: 'salt', challenge: 'challenge' },
      } }));
    }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    emit(name, packet) { this.handlers.get(name)?.({ data: JSON.stringify(packet) }); }
    send(raw) {
      const packet = JSON.parse(raw);
      packets.push(packet);
      if (packet.op === 1) queueMicrotask(() => this.emit('message', { op: 2, d: { negotiatedRpcVersion: 1 } }));
      if (packet.op === 6) queueMicrotask(() => this.emit('message', { op: 7, d: {
        requestId: packet.d.requestId, requestType: packet.d.requestType,
        requestStatus: { result: true }, responseData: { obsVersion: 'test' },
      } }));
    }
    close() { this.emit('close'); }
  }

  const client = await ObsClient.connect(4455, 'password', FakeSocket);
  assert.equal(packets[0].d.authentication, sha(sha('passwordsalt') + 'challenge'));
  assert.deepEqual(await client.request('GetVersion'), { obsVersion: 'test' });
  client.close();
});

test('OBS v5 refuses an authenticated server without a password', async () => {
  class FakeSocket {
    constructor() {
      this.handlers = new Map();
      queueMicrotask(() => this.handlers.get('message')?.({ data: JSON.stringify({ op: 0, d: {
        authentication: { salt: 'salt', challenge: 'challenge' },
      } }) }));
    }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    close() {}
  }
  await assert.rejects(ObsClient.connect(4455, '', FakeSocket), /contraseña/);
});
