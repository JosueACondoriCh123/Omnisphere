'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createOutputManager, validateConfig } = require('./manager.cjs');

const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (value) => Buffer.from(value),
  decryptString: (buffer) => buffer.toString(),
};

test('only Zoom caption hosts and valid RTMP destinations are accepted', () => {
  assert.throws(() => validateConfig({ destination: 'zoom', lang: 'es', native_captions: true,
    zoom_url: 'https://example.com/closedcaption' }), /Zoom/);
  assert.throws(() => validateConfig({ destination: 'rtmp', lang: 'en', server: 'https://example.com',
    stream_key: 'secret' }), /RTMP/);
});

test('ten rooms configure and stream independently without exposing keys', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-outputs-'));
  const calls = [];
  const connectObs = async (port) => ({
    request: async (name, data) => {
      calls.push([port, name, data]);
      if (name === 'GetSceneList') return { scenes: [] };
      if (name === 'GetInputList') return { inputs: [] };
      return {};
    },
    close() {},
  });
  try {
    const manager = createOutputManager({ userData: folder, safeStorage, connectObs });
    for (const stage of Array.from({ length: 10 }, (_, index) => String(index + 1))) {
      await manager.configure(stage, { destination: 'rtmp', lang: 'es',
        server: `rtmps://example.com/live/${stage}`, stream_key: `secret-${stage}`,
        obs_port: 4454 + Number(stage), burn_in: true });
      if (stage === '1') await assert.rejects(manager.configure('2', { destination: 'rtmp', lang: 'es',
        server: 'rtmps://example.com/live/2', stream_key: 'secret-2', obs_port: 4455 }), /puerto.*distinto/);
      const result = await manager.start(stage);
      assert.equal(result.state, 'streaming');
      assert.equal(JSON.stringify(result).includes(`secret-${stage}`), false);
    }
    assert.equal(calls.filter((entry) => entry[1] === 'StartStream').length, 10);
    await manager.stop('2');
    assert.equal(manager.status()['1'].state, 'streaming');
    assert.equal(manager.status()['2'].state, 'configured');
    assert.equal(manager.status()['3'].state, 'streaming');
    assert.equal(manager.status()['10'].state, 'streaming');
    assert.equal(Object.keys(manager.status()).length, 10);
    await manager.close();
  } finally { fs.rmSync(folder, { recursive: true, force: true }); }
});

test('Zoom receives each confirmed clause only once', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-zoom-'));
  const sockets = [];
  const posts = [];
  class FakeSocket {
    constructor(url) { this.url = url; this.handlers = new Map(); sockets.push(this); }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    emit(message) { this.handlers.get('message')?.({ data: JSON.stringify(message) }); }
    close() {}
  }
  const request = async (url, options = {}) => {
    if (options.method === 'POST') { posts.push([url.toString(), options.body]); return { ok: true }; }
    return { ok: true, text: async () => '0' };
  };
  try {
    const manager = createOutputManager({ userData: folder, safeStorage, Socket: FakeSocket, request,
      openShare: () => {} });
    await manager.configure('1', { destination: 'zoom', lang: 'es', burn_in: true,
      native_captions: true, zoom_url: 'https://wmcc.zoom.us/closedcaption?id=1&signature=test' });
    assert.equal((await manager.start('1')).state, 'ready_to_share');
    const socket = sockets[0];
    socket.emit({ type: 'snapshot', captions: [] });
    const caption = { type: 'caption', state: 'committed', session_id: 's1', clause_id: 'c1', text: 'Hola' };
    socket.emit(caption);
    socket.emit(caption);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(posts.length, 1);
    assert.match(posts[0][0], /seq=1/);
    assert.equal(posts[0][1], 'Hola');
    await manager.close();
  } finally { fs.rmSync(folder, { recursive: true, force: true }); }
});

test('Zoom recovers captions committed during startup and a socket outage', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-zoom-reconnect-'));
  const sockets = [];
  const posts = [];
  class FakeSocket {
    constructor() { this.handlers = new Map(); sockets.push(this); }
    addEventListener(name, fn) { this.handlers.set(name, fn); }
    emit(name, message) { this.handlers.get(name)?.(message === undefined ? {} : { data: JSON.stringify(message) }); }
    close() { this.emit('close'); }
  }
  const request = async (_url, options = {}) => {
    if (options.method === 'POST') posts.push(options.body);
    return { ok: true, text: async () => '0' };
  };
  try {
    const manager = createOutputManager({ userData: folder, safeStorage, Socket: FakeSocket,
      request, openShare: () => {} });
    await manager.configure('1', { destination: 'zoom', lang: 'es', native_captions: true,
      zoom_url: 'https://wmcc.zoom.us/closedcaption?id=1&signature=test' });
    await manager.start('1');
    const old = { state: 'committed', session_id: 's1', clause_id: 'old', text: 'Anterior',
      emitted_at_ms: Date.now() - 10_000 };
    const duringStartup = { ...old, clause_id: 'new', text: 'Nueva', emitted_at_ms: Date.now() + 1000 };
    sockets[0].emit('message', { type: 'snapshot', captions: [old, duringStartup] });
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.deepEqual(posts, ['Nueva']);
    sockets[0].close();
    await new Promise((resolve) => setTimeout(resolve, 1050));
    assert.equal(sockets.length, 2);
    const duringOutage = { ...old, clause_id: 'outage', text: 'Recuperada', emitted_at_ms: Date.now() };
    sockets[1].emit('message', { type: 'snapshot', captions: [old, duringStartup, duringOutage] });
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.deepEqual(posts, ['Nueva', 'Recuperada']);
    await manager.close();
  } finally { fs.rmSync(folder, { recursive: true, force: true }); }
});

test('a failed encrypted save does not leave a room configured', async () => {
  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-save-'));
  try {
    const unavailableStorage = { ...safeStorage, isEncryptionAvailable: () => false };
    const manager = createOutputManager({ userData: folder, safeStorage: unavailableStorage });
    await assert.rejects(manager.configure('1', { destination: 'meet', lang: 'es' }), /almacén seguro/);
    assert.equal(manager.status()['1'].state, 'idle');
  } finally { fs.rmSync(folder, { recursive: true, force: true }); }
});
