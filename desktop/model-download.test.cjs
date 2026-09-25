'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { MODEL_DOWNLOADS, TOTAL_BYTES, createModelDownloader } = require('./model-download.cjs');

const sha = (buffer) => createHash('sha256').update(buffer).digest('hex');
const bodies = { 'a/one.bin': Buffer.from('primer-archivo-de-prueba'), 'two.gguf': Buffer.alloc(4096, 7) };
const files = Object.entries(bodies).map(([name, body]) => ({
  path: name, url: `https://example.test/${name}`, size: body.length, sha256: sha(body),
}));

function server({ corrupt = '', failAfter = Infinity } = {}) {
  const calls = [];
  const request = async (url, options) => {
    const name = url.replace('https://example.test/', '');
    let body = bodies[name];
    if (name === corrupt) body = Buffer.from(body).fill(0);
    const range = options.headers.range?.match(/^bytes=(\d+)-$/);
    calls.push([name, options.headers.range || '']);
    const start = range ? Number(range[1]) : 0;
    const slice = body.subarray(start);
    let offset = 0;
    const stream = new ReadableStream({ async pull(controller) {
      await new Promise((resolve) => setTimeout(resolve, 1));
      if (offset >= slice.length) { controller.close(); return; }
      if (offset >= failAfter) { controller.error(new Error('conexión cortada')); return; }
      const end = Math.min(slice.length, offset + 256);
      controller.enqueue(new Uint8Array(slice.subarray(offset, end)));
      offset = end;
    } });
    return { status: range ? 206 : 200, body: stream };
  };
  return { request, calls };
}

function folder() { return fs.mkdtempSync(path.join(os.tmpdir(), 'omnistage-models-')); }

test('pinned manifest matches the offline model pack contract', () => {
  assert.deepEqual(MODEL_DOWNLOADS.map((entry) => entry.path).sort(), [
    'faster-whisper/config.json', 'faster-whisper/model.bin', 'faster-whisper/tokenizer.json',
    'faster-whisper/vocabulary.txt', 'gemma-4-e2b-q4.gguf',
  ]);
  assert.ok(MODEL_DOWNLOADS.every((entry) => entry.url.startsWith('https://huggingface.co/')
    && /^[a-f0-9]{64}$/.test(entry.sha256) && /\/resolve\/[a-f0-9]{40}\//.test(entry.url)));
  assert.ok(TOTAL_BYTES > 3.8e9);
});

test('downloads, verifies and installs models atomically', async () => {
  const userData = folder();
  try {
    const progress = [];
    const { request } = server();
    const downloader = createModelDownloader({ userData, request, files, onProgress: (value) => progress.push(value) });
    assert.deepEqual(await downloader.start(), { installed: true, files: 2 });
    assert.deepEqual(fs.readFileSync(path.join(userData, 'models', 'a', 'one.bin')), bodies['a/one.bin']);
    assert.equal(fs.existsSync(path.join(userData, '.models-download')), false);
    assert.equal(progress.at(-1).phase, 'installed');
    assert.equal(progress.at(-1).received, progress.at(-1).total);
    await assert.rejects(downloader.start(), /Ya hay modelos instalados/);
  } finally { fs.rmSync(userData, { recursive: true, force: true }); }
});

test('resumes a cut download with an HTTP range request', async () => {
  const userData = folder();
  try {
    const first = server({ failAfter: 1000 });
    await assert.rejects(createModelDownloader({ userData, request: first.request, files }).start(), /conexión cortada/);
    const partial = fs.statSync(path.join(userData, '.models-download', 'two.gguf')).size;
    assert.ok(partial > 0 && partial <= 1024);
    const second = server();
    await createModelDownloader({ userData, request: second.request, files }).start();
    assert.deepEqual(second.calls, [['two.gguf', `bytes=${partial}-`]]);
    assert.deepEqual(fs.readFileSync(path.join(userData, 'models', 'two.gguf')), bodies['two.gguf']);
  } finally { fs.rmSync(userData, { recursive: true, force: true }); }
});

test('rejects a file whose hash does not match and installs nothing', async () => {
  const userData = folder();
  try {
    const { request } = server({ corrupt: 'two.gguf' });
    const downloader = createModelDownloader({ userData, request, files });
    await assert.rejects(downloader.start(), /SHA256 o tamaño incorrecto: two.gguf/);
    assert.equal(fs.existsSync(path.join(userData, 'models')), false);
    assert.equal(fs.existsSync(path.join(userData, '.models-download', 'two.gguf')), false);
    assert.equal(downloader.status().phase, 'error');
  } finally { fs.rmSync(userData, { recursive: true, force: true }); }
});
