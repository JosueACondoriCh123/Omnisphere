'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { ObsClient } = require('./obs-client.cjs');
const { STAGE_IDS, validStage } = require('../stages.cjs');

const DESTINATIONS = new Set(['youtube', 'rtmp', 'zoom', 'meet']);
const LANGUAGES = new Set(['es', 'en']);

function publicConfig(config) {
  if (!config) return null;
  return {
    destination: config.destination,
    lang: config.lang,
    burn_in: config.burn_in,
    native_captions: config.native_captions,
    obs_port: config.obs_port || null,
    has_stream_key: Boolean(config.stream_key),
    has_zoom_url: Boolean(config.zoom_url),
    has_obs_password: Boolean(config.obs_password),
  };
}

function validateConfig(value) {
  if (!value || !DESTINATIONS.has(value.destination) || !LANGUAGES.has(value.lang)) throw new Error('Destino o idioma inválido.');
  const config = {
    destination: value.destination, lang: value.lang,
    burn_in: value.burn_in !== false,
    native_captions: Boolean(value.native_captions),
    server: String(value.server || '').trim(),
    stream_key: String(value.stream_key || '').trim(),
    zoom_url: String(value.zoom_url || '').trim(),
    obs_port: Number(value.obs_port || 4455),
    obs_password: String(value.obs_password || ''),
  };
  if (['youtube', 'rtmp'].includes(config.destination)) {
    if (!/^rtmps?:\/\/[^\s]+$/i.test(config.server) || !config.stream_key || config.stream_key.length > 1024) throw new Error('Ingresá servidor RTMP y clave de transmisión.');
    if (!Number.isInteger(config.obs_port) || config.obs_port < 1 || config.obs_port > 65535) throw new Error('Puerto OBS inválido.');
  }
  if (config.destination === 'zoom' && config.native_captions) {
    let url;
    try { url = new URL(config.zoom_url); } catch { throw new Error('URL de subtítulos Zoom inválida.'); }
    if (url.protocol !== 'https:' || !url.hostname.endsWith('.zoom.us') || !/\/closedcaption\/?$/.test(url.pathname)) throw new Error('La URL de subtítulos debe venir de Zoom.');
  }
  if (config.destination === 'meet') config.native_captions = false;
  if (config.destination === 'rtmp') config.native_captions = false;
  return config;
}

function createOutputManager({ userData, safeStorage, openShare, request = fetch, connectObs = ObsClient.connect, Socket = WebSocket }) {
  const file = path.join(userData, 'outputs.json');
  const active = new Map();
  let saved = {};
  let loaded = false;
  function loadSaved() {
    if (loaded) return;
    loaded = true;
    try {
      const raw = JSON.parse(fs.readFileSync(file, 'utf8'));
      if (safeStorage.isEncryptionAvailable()) {
        for (const [stage, ciphertext] of Object.entries(raw)) {
          if (STAGE_IDS.includes(stage)) saved[stage] = JSON.parse(safeStorage.decryptString(Buffer.from(ciphertext, 'base64')));
        }
      }
    } catch { saved = {}; }
  }

  function persist() {
    loadSaved();
    if (!safeStorage.isEncryptionAvailable()) throw new Error('El almacén seguro de Windows no está disponible.');
    const encoded = Object.fromEntries(Object.entries(saved).map(([stage, config]) =>
      [stage, safeStorage.encryptString(JSON.stringify(config)).toString('base64')]));
    fs.mkdirSync(userData, { recursive: true });
    const temp = `${file}.${process.pid}.tmp`;
    try { fs.writeFileSync(temp, JSON.stringify(encoded), { flag: 'wx', mode: 0o600 }); fs.renameSync(temp, file); }
    finally { if (fs.existsSync(temp)) fs.unlinkSync(temp); }
  }

  function status() {
    loadSaved();
    return Object.fromEntries(STAGE_IDS.map((stage) => {
      const item = active.get(stage);
      return [stage, {
        state: item?.state || (saved[stage] ? 'configured' : 'idle'),
        config: publicConfig(saved[stage]),
        error: item?.error || null,
        share_url: saved[stage] && ['zoom', 'meet'].includes(saved[stage].destination)
          ? `http://127.0.0.1:8080/operator/output/${stage}?lang=${saved[stage].lang}&burn=${saved[stage].burn_in ? '1' : '0'}` : null,
      }];
    }));
  }

  async function configure(stage, value) {
    loadSaved();
    stage = validStage(stage);
    if (active.has(stage)) throw new Error('Detené la salida antes de cambiarla.');
    const previous = saved[stage];
    const merged = { ...value };
    if (previous?.destination === value?.destination) {
      for (const field of ['server', 'stream_key', 'zoom_url', 'obs_password']) {
        if (!merged[field]) merged[field] = previous[field];
      }
    }
    const config = validateConfig(merged);
    if (['youtube', 'rtmp'].includes(config.destination) && Object.entries(saved).some(([otherStage, other]) =>
      otherStage !== stage && ['youtube', 'rtmp'].includes(other.destination) && other.obs_port === config.obs_port)) {
      throw new Error('Cada sala RTMP necesita un puerto WebSocket de OBS distinto.');
    }
    saved[stage] = config;
    try { persist(); }
    catch (error) {
      if (previous) saved[stage] = previous;
      else delete saved[stage];
      throw error;
    }
    return status()[stage];
  }

  function captionFeed(stage, item, config) {
    let socket;
    let stopped = false;
    let first = true;
    const seen = new Set();
    const pending = new Set();
    let queue = Promise.resolve();
    const connect = () => {
      if (stopped) return;
      socket = new Socket(`ws://127.0.0.1:8080/ws/stages/${stage}/${config.lang}`);
      socket.addEventListener('message', (event) => {
        let message;
        try { message = JSON.parse(String(event.data)); } catch { return; }
        const captions = message.type === 'snapshot' ? message.captions || [] : [message];
        if (message.type === 'snapshot' && first) {
          for (const caption of captions) {
            if (caption.session_id && caption.clause_id && Number(caption.emitted_at_ms) < item.startedAt) {
              seen.add(`${caption.session_id}:${caption.clause_id}:${config.lang}`);
            }
          }
          first = false;
        }
        for (const caption of captions) {
          if (caption.state !== 'committed' || !caption.text || !caption.session_id || !caption.clause_id) continue;
          const key = `${caption.session_id}:${caption.clause_id}:${config.lang}`;
          if (seen.has(key) || pending.has(key)) continue;
          pending.add(key);
          queue = queue.then(async () => {
            if (stopped) return;
            if (config.destination === 'youtube' && config.native_captions) {
              await item.obs.request('SendStreamCaption', { captionText: caption.text });
            } else if (config.destination === 'zoom' && config.native_captions) {
              const url = new URL(config.zoom_url);
              url.searchParams.set('seq', String(item.seq));
              for (let retry = 0; retry < 6; retry++) {
                try {
                  const result = await request(url, { method: 'POST', headers: { 'content-type': 'text/plain; charset=utf-8' }, body: caption.text, signal: AbortSignal.timeout(2000) });
                  if (result.ok) { item.seq++; return; }
                } catch { /* retry briefly */ }
                await new Promise((resolve) => setTimeout(resolve, Math.min(100 * 2 ** retry, 2000)));
              }
              throw new Error('Zoom no recibió los subtítulos.');
            }
          }).then(() => {
            pending.delete(key); seen.add(key);
            if (config.destination === 'zoom' && item.state === 'error') {
              item.state = 'ready_to_share'; item.error = null;
            }
          }).catch((error) => {
            pending.delete(key);
            item.state = 'error'; item.error = error.message;
            socket?.close();
          });
        }
      });
      socket.addEventListener('close', () => { if (!stopped) setTimeout(connect, 1000); });
    };
    connect();
    return () => { stopped = true; socket?.close(); };
  }

  async function prepareObs(stage, config, obs) {
    const sceneName = `OmniStage Sala ${stage}`;
    const scenes = await obs.request('GetSceneList');
    if (!scenes.scenes?.some((scene) => scene.sceneName === sceneName)) await obs.request('CreateScene', { sceneName });
    const inputs = await obs.request('GetInputList');
    const existing = new Set((inputs.inputs || []).map((input) => input.inputName));
    const media = `OmniStage media ${stage}`;
    const overlay = `OmniStage subtítulos ${stage}`;
    const definitions = [
      [media, 'ffmpeg_source', { input: `rtsp://127.0.0.1:8554/live/stage-${stage}`, is_local_file: false, restart_on_activate: false }, true],
      [overlay, 'browser_source', { url: `http://127.0.0.1:8080/overlay/${stage}?theme=obs&lang=${config.lang}`, width: 1920, height: 1080, fps: 30 }, config.burn_in],
    ];
    for (const [inputName, inputKind, inputSettings, enabled] of definitions) {
      if (!existing.has(inputName)) await obs.request('CreateInput', { sceneName, inputName, inputKind, inputSettings, sceneItemEnabled: enabled });
      else {
        await obs.request('SetInputSettings', { inputName, inputSettings, overlay: true });
        try {
          const item = await obs.request('GetSceneItemId', { sceneName, sourceName: inputName });
          await obs.request('SetSceneItemEnabled', { sceneName, sceneItemId: item.sceneItemId, sceneItemEnabled: enabled });
        } catch { await obs.request('CreateSceneItem', { sceneName, sourceName: inputName, sceneItemEnabled: enabled }); }
      }
    }
    await obs.request('SetCurrentProgramScene', { sceneName });
  }

  async function start(stage) {
    loadSaved();
    stage = validStage(stage);
    const config = saved[stage];
    if (!config) throw new Error('Configurá primero el destino.');
    if (active.has(stage)) return status()[stage];
    const item = { state: 'preparing', error: null, seq: 1, obs: null, stopFeed: null,
      monitor: null, streamStarted: false, startedAt: Date.now() };
    active.set(stage, item);
    try {
      if (['youtube', 'rtmp'].includes(config.destination)) {
        item.obs = await connectObs(config.obs_port, config.obs_password);
        item.obs.onClose?.(() => {
          if (active.get(stage) === item && item.state === 'streaming') {
            item.state = 'error'; item.error = 'Se perdió la conexión con OBS.';
          }
        });
        await prepareObs(stage, config, item.obs);
        await item.obs.request('SetStreamServiceSettings', { streamServiceType: 'rtmp_custom', streamServiceSettings: { server: config.server, key: config.stream_key } });
        await item.obs.request('StartStream');
        item.streamStarted = true;
        const stream = await item.obs.request('GetStreamStatus');
        if (stream.outputActive === false) throw new Error('OBS no inició la transmisión.');
        item.state = 'streaming';
        item.monitor = setInterval(async () => {
          try {
            const next = await item.obs.request('GetStreamStatus');
            item.state = next.outputActive === false ? 'error' : 'streaming';
            item.error = next.outputActive === false ? 'OBS perdió la salida de transmisión.' : null;
          } catch {
            item.state = 'error'; item.error = 'No se pudo comprobar la salida de OBS.';
          }
        }, 5000);
      } else {
        item.state = 'ready_to_share';
        if (openShare) openShare(stage, config.lang, config.burn_in);
      }
      if (config.destination === 'zoom' && config.native_captions) {
        try {
          const sequenceUrl = new URL(config.zoom_url);
          sequenceUrl.pathname = sequenceUrl.pathname.replace(/\/closedcaption\/?$/, '/closedcaption/seq');
          sequenceUrl.searchParams.delete('seq');
          const response = await request(sequenceUrl, { signal: AbortSignal.timeout(2000) });
          if (response.ok) {
            const previous = Number((await response.text()).trim());
            if (Number.isSafeInteger(previous) && previous >= 0) item.seq = previous + 1;
          }
        } catch { /* Zoom may omit sequence lookup; first POST reports any error */ }
      }
      if ((config.destination === 'zoom' || config.destination === 'youtube') && config.native_captions) item.stopFeed = captionFeed(stage, item, config);
    } catch (error) {
      item.state = 'error';
      item.error = 'No se pudo iniciar la salida. Revisá OBS y la configuración.';
      if (item.monitor) clearInterval(item.monitor);
      item.stopFeed?.();
      if (item.obs) {
        if (item.streamStarted) {
          try { await item.obs.request('StopStream'); } catch { /* OBS may be unreachable */ }
        }
        item.obs.close();
        item.obs = null;
      }
    }
    return status()[stage];
  }

  async function stop(stage) {
    stage = validStage(stage);
    const item = active.get(stage);
    if (!item) return status()[stage];
    item.state = 'stopping';
    if (item.monitor) clearInterval(item.monitor);
    item.stopFeed?.();
    if (item.obs) {
      try { await item.obs.request('StopStream'); } catch { /* OBS may have stopped already */ }
      item.obs.close();
    }
    active.delete(stage);
    return status()[stage];
  }

  async function close() { for (const stage of [...active.keys()]) await stop(stage); }
  return { configure, start, stop, status, close };
}

module.exports = { createOutputManager, validateConfig };
