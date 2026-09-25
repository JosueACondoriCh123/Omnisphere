'use strict';

const fs = require('node:fs');
const path = require('node:path');

const API_BASE = 'https://generativelanguage.googleapis.com/v1beta/models/';
const REQUIRED_MODELS = ['gemini-3.5-transcribe-live', 'gemini-3.5-flash-lite'];

function createCloudKeyStore({ userData, safeStorage, request = fetch }) {
  const file = path.join(userData, 'secrets.json');
  let checking = false;
  let lastError = '';
  let lastFailure = null;

  function read() {
    try { return JSON.parse(fs.readFileSync(file, 'utf8')); }
    catch { return {}; }
  }

  function current() {
    if (!safeStorage.isEncryptionAvailable()) return null;
    const saved = read().gemini;
    if (!saved || typeof saved !== 'object' || saved.validated !== true || typeof saved.ciphertext !== 'string') return null;
    try { return safeStorage.decryptString(Buffer.from(saved.ciphertext, 'base64')); }
    catch { return null; }
  }

  function status() {
    const saved = read().gemini;
    const configured = Boolean(current());
    return {
      state: checking ? 'validating' : lastFailure || (configured ? 'ready' : 'missing'),
      configured,
      validated_at: configured ? saved.validated_at : null,
      error: lastError || null,
    };
  }

  function write(data) {
    fs.mkdirSync(userData, { recursive: true });
    const staging = path.join(userData, `secrets-${process.pid}-${Date.now()}.tmp`);
    try {
      fs.writeFileSync(staging, JSON.stringify(data), { mode: 0o600, flag: 'wx' });
      fs.renameSync(staging, file);
    } finally {
      if (fs.existsSync(staging)) fs.unlinkSync(staging);
    }
  }

  async function validateAndSave(key) {
    if (checking) throw new Error('Ya se está validando una clave.');
    if (typeof key !== 'string' || !key.trim() || key.length > 4096) throw new Error('Ingresá una clave válida.');
    if (!safeStorage.isEncryptionAvailable()) throw new Error('El almacén seguro de Windows no está disponible.');
    checking = true;
    lastError = '';
    lastFailure = null;
    try {
      for (const model of REQUIRED_MODELS) {
        let response;
        try {
          response = await request(`${API_BASE}${model}`, {
            headers: { 'x-goog-api-key': key.trim() },
            signal: AbortSignal.timeout(8000),
          });
        } catch {
          lastFailure = 'offline';
          lastError = 'No se pudo contactar con Gemini. Revisá Internet e intentá nuevamente.';
          return { ...status(), state: lastFailure };
        }
        if (!response.ok) {
          lastFailure = [400, 401, 403, 404].includes(response.status) ? 'invalid' : 'offline';
          lastError = lastFailure === 'invalid'
            ? `La clave no tiene acceso a ${model} (HTTP ${response.status}).`
            : `Gemini no está disponible (HTTP ${response.status}).`;
          return { ...status(), state: lastFailure };
        }
      }
      const previous = read();
      previous.gemini = {
        ciphertext: safeStorage.encryptString(key.trim()).toString('base64'),
        validated: true,
        validated_at: new Date().toISOString(),
      };
      write(previous);
      return { ...status(), state: 'ready' };
    } finally {
      checking = false;
    }
  }

  function remove() {
    const previous = read();
    delete previous.gemini;
    write(previous);
    lastError = '';
    lastFailure = null;
    return status();
  }

  return { current, status, validateAndSave, remove };
}

module.exports = { createCloudKeyStore };
