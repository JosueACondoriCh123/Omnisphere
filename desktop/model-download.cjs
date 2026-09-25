'use strict';

// Descarga en línea de los mismos modelos que arma prepare_model_pack.py.
// Revisiones, tamaños y SHA256 fijados: si Hugging Face sirve otra cosa, no se instala.
const fs = require('node:fs');
const path = require('node:path');
const { createHash } = require('node:crypto');
const { Readable, Transform } = require('node:stream');
const { pipeline } = require('node:stream/promises');

const HF = 'https://huggingface.co';
const WHISPER = `${HF}/Systran/faster-whisper-small/resolve/536b0662742c02347bc0e980a01041f333bce120`;
const GEMMA = `${HF}/google/gemma-4-E2B-it-qat-q4_0-gguf/resolve/675cff42a74c774d6cb76f76d8eacb49b48c9b93`;

const MODEL_DOWNLOADS = Object.freeze([
  { path: 'faster-whisper/config.json', url: `${WHISPER}/config.json`, size: 2370,
    sha256: 'b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828' },
  { path: 'faster-whisper/tokenizer.json', url: `${WHISPER}/tokenizer.json`, size: 2203239,
    sha256: 'fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab' },
  { path: 'faster-whisper/vocabulary.txt', url: `${WHISPER}/vocabulary.txt`, size: 459861,
    sha256: '34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913' },
  { path: 'faster-whisper/model.bin', url: `${WHISPER}/model.bin`, size: 483546902,
    sha256: '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671' },
  { path: 'gemma-4-e2b-q4.gguf', url: `${GEMMA}/gemma-4-E2B_q4_0-it.gguf`, size: 3349516256,
    sha256: 'fa401b55b07ee70a54c6dae3903c783a6e65064312529ea57175cb5f8dec6634' },
]);
const TOTAL_BYTES = MODEL_DOWNLOADS.reduce((sum, entry) => sum + entry.size, 0);
const DISK_MARGIN = 256 * 1024 * 1024;

async function hashFile(file) {
  const digest = createHash('sha256');
  for await (const chunk of fs.createReadStream(file, { highWaterMark: 4 * 1024 * 1024 })) digest.update(chunk);
  return digest.digest('hex');
}

// La carpeta de trabajo sobrevive a un corte: el siguiente intento pide solo lo que falta.
function createModelDownloader({ userData, request = fetch, onProgress = () => {}, files = MODEL_DOWNLOADS }) {
  const target = path.join(userData, 'models');
  const staging = path.join(userData, '.models-download');
  const total = files.reduce((sum, entry) => sum + entry.size, 0);
  let running = null;
  let controller = null;
  let state = { phase: 'idle', received: 0, total, file: '', error: '' };
  let lastEmit = 0;

  function emit(patch, force = false) {
    state = { ...state, ...patch };
    const now = Date.now();
    if (force || now - lastEmit > 250) { lastEmit = now; onProgress({ ...state }); }
  }

  async function fetchInto(entry, destination, done) {
    let have = fs.existsSync(destination) ? fs.statSync(destination).size : 0;
    if (have > entry.size) { fs.rmSync(destination); have = 0; }
    if (have === entry.size) return;
    const response = await request(entry.url, {
      headers: have ? { range: `bytes=${have}-` } : {}, redirect: 'follow', signal: controller.signal,
    });
    if (response.status === 200) have = 0;
    else if (response.status !== 206) throw new Error(`Hugging Face respondió ${response.status} para ${entry.path}`);
    let received = have;
    const counter = new Transform({ transform(chunk, _encoding, callback) {
      received += chunk.length;
      emit({ received: done + received });
      callback(null, chunk);
    } });
    await pipeline(Readable.fromWeb(response.body), counter,
      fs.createWriteStream(destination, { flags: have ? 'a' : 'w' }), { signal: controller.signal });
  }

  async function run() {
    if (fs.existsSync(target)) throw new Error('Ya hay modelos instalados; no se sobrescribieron');
    fs.mkdirSync(staging, { recursive: true });
    const pending = files.reduce((sum, entry) => {
      const file = path.join(staging, ...entry.path.split('/'));
      return sum + entry.size - (fs.existsSync(file) ? Math.min(fs.statSync(file).size, entry.size) : 0);
    }, 0);
    const disk = await fs.promises.statfs(userData).catch(() => null);
    if (disk && disk.bavail * disk.bsize < pending + DISK_MARGIN) {
      const needed = ((pending + DISK_MARGIN) / 1024 ** 3).toFixed(1);
      throw new Error(`Falta espacio en disco: se necesitan ${needed} GB libres`);
    }
    let done = 0;
    for (const entry of files) {
      const destination = path.join(staging, ...entry.path.split('/'));
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      emit({ phase: 'downloading', file: entry.path, received: done }, true);
      await fetchInto(entry, destination, done);
      emit({ phase: 'verifying', file: entry.path, received: done + entry.size }, true);
      if (fs.statSync(destination).size !== entry.size || await hashFile(destination) !== entry.sha256) {
        fs.rmSync(destination, { force: true });
        throw new Error(`SHA256 o tamaño incorrecto: ${entry.path}. Volvé a intentar.`);
      }
      done += entry.size;
    }
    fs.renameSync(staging, target);
    emit({ phase: 'installed', received: total, file: '' }, true);
    return { installed: true, files: files.length };
  }

  return {
    status: () => ({ ...state }),
    start() {
      if (running) return running;
      controller = new AbortController();
      state = { phase: 'downloading', received: 0, total, file: '', error: '' };
      running = run().catch((error) => {
        const cancelled = controller.signal.aborted;
        emit({ phase: cancelled ? 'cancelled' : 'error', error: cancelled ? '' : error.message }, true);
        if (!cancelled) throw error;
        return null;
      }).finally(() => { running = null; });
      return running;
    },
    cancel() { controller?.abort(); return true; },
  };
}

module.exports = { MODEL_DOWNLOADS, TOTAL_BYTES, createModelDownloader, hashFile };
