'use strict';

const { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } = require('electron');
const fs = require('node:fs');
const path = require('node:path');
const { pathToFileURL } = require('node:url');
const os = require('node:os');
const { spawn, execFile } = require('node:child_process');
const { promisify } = require('node:util');
const { createHash, randomUUID } = require('node:crypto');
const { Transform } = require('node:stream');
const { pipeline } = require('node:stream/promises');
const { createCloudKeyStore } = require('./agent-a-gemini/cloud-key.cjs');
const { createOutputManager } = require('./agent-b-outputs/manager.cjs');
const { validStage } = require('./stages.cjs');
const { createModelDownloader } = require('./model-download.cjs');
const { runLocalSample } = require('./local-model.cjs');
const execFileAsync = promisify(execFile);

const SERVICES = ['mediamtx', 'gemma', 'backend'];
const FIREWALL_RULE = 'OmniStage publico LAN';
const MODEL_FILES = new Set([
  'faster-whisper/model.bin', 'faster-whisper/config.json',
  'faster-whisper/tokenizer.json', 'faster-whisper/vocabulary.txt',
  'gemma-4-e2b-q4.gguf',
]);
const processes = new Map();
const sources = new Map();
const restartTimers = new Map();
let quitting = false;
let shutdownInProgress = false;
let shutdownComplete = false;
let window;
let startupPromise;
const configuredUserData = process.env.OMNISTAGE_USER_DATA;
if (configuredUserData && !path.isAbsolute(configuredUserData)) {
  throw new Error('OMNISTAGE_USER_DATA debe ser una ruta absoluta');
}
const userDataPath = configuredUserData || path.join(app.getPath('appData'), 'OmniStage');
fs.mkdirSync(userDataPath, { recursive: true });
app.setPath('userData', userDataPath);
const cloudKeyStore = createCloudKeyStore({ userData: userDataPath, safeStorage });
const outputManager = createOutputManager({
  userData: userDataPath,
  safeStorage,
  openShare: (stage, lang, burnIn) => shell.openExternal(`http://127.0.0.1:8080/operator/output/${stage}?lang=${lang}&burn=${burnIn ? '1' : '0'}`),
});
const modelDownloader = createModelDownloader({
  userData: userDataPath,
  onProgress: (state) => { if (window && !window.isDestroyed()) window.webContents.send('omni:models-progress', state); },
});

function resources() {
  return app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..');
}
function runtimePath(name) {
  const folder = app.isPackaged ? path.join(resources(), 'runtime') : path.join(__dirname, 'runtime');
  return name.startsWith('omnistage-')
    ? path.join(folder, name, `${name}.exe`)
    : path.join(folder, `${name}.exe`);
}
function binary(name, fallback = name) {
  const candidate = runtimePath(name);
  if (fs.existsSync(candidate)) return candidate;
  if (app.isPackaged) return null;
  const vendor = path.join(__dirname, 'vendor', `${name}.exe`);
  if (fs.existsSync(vendor)) return vendor;
  return fallback;
}
function serviceSpec(name) {
  const root = resources();
  const userData = app.getPath('userData');
  const baseEnv = { ...process.env };
  delete baseEnv.GEMINI_API_KEY;
  delete baseEnv.TUNNEL_TOKEN;
  const runtimeFolder = app.isPackaged ? path.join(root, 'runtime') : path.join(__dirname, 'vendor');
  baseEnv.PATH = `${runtimeFolder}${path.delimiter}${baseEnv.PATH || ''}`;
  const common = { ...baseEnv,
    TRANSPORT_MODE: 'local', DB_PATH: path.join(userData, 'omnistage.db'),
    WEB_DB_PATH: path.join(userData, 'omnistage-web.db'),
    MEDIAMTX_API_URL: 'http://127.0.0.1:9997',
    MEDIAMTX_RTSP_BASE: 'rtsp://127.0.0.1:8554',
    PUBLIC_RTMP_HOST: 'localhost', PUBLIC_RTMP_PORT: '1935',
    INTERNAL_API_BASE: 'http://127.0.0.1:8080',
    INTERNAL_TOKEN: internalToken(),
    OMNISTAGE_WEB_DIST: app.isPackaged ? path.join(root, 'web') : path.join(root, 'web', 'dist'),
    STAGE_CONTEXT_FILE: path.join(root, 'config', 'stages.json'),
    FFMPEG_BIN: binary('ffmpeg') || '',
    GEMMA_API_URL: 'http://127.0.0.1:8092',
    LOCAL_ASR_MODEL_PATH: path.join(userData, 'models', 'faster-whisper'),
    OMNISTAGE_WORKER_BIN: binary('omnistage-worker') || '',
  };
  if (name === 'mediamtx') return { bin: binary('mediamtx'), args: [app.isPackaged ? path.join(root, 'mediamtx.yml') : path.join(root, 'config', 'mediamtx.native.yml')], env: baseEnv };
  if (name === 'gemma') {
    const model = path.join(userData, 'models', 'gemma-4-e2b-q4.gguf');
    if (!fs.existsSync(model)) return null;
    const requestedParallel = Number(process.env.OMNISTAGE_GEMMA_PARALLEL || 3);
    const parallel = Number.isInteger(requestedParallel) && requestedParallel >= 1 && requestedParallel <= 10
      ? requestedParallel : 3;
    const context = 768 * parallel;
    return { bin: binary('llama-server'), args: ['-m', model, '--alias', 'gemma-4-E2B-it', '--host', '127.0.0.1', '--port', '8092', '-ngl', '99', '-c', String(context), '--parallel', String(parallel), '--reasoning', 'off', '--reasoning-budget', '0'], env: baseEnv };
  }
  if (name === 'backend') {
    const packaged = binary('omnistage-api');
    const env = { ...common, GEMINI_API_KEY: cloudKeyStore.current() || '' };
    if (app.isPackaged) return { bin: packaged, args: [], env };
    return { bin: path.join(root, '.venv', 'Scripts', 'python.exe'), args: ['-m', 'app.serve'], env };
  }
  return null;
}

async function importModelPack(folder) {
  const manifest = JSON.parse(fs.readFileSync(path.join(folder, 'manifest.json'), 'utf8'));
  if (manifest.format !== 1 || !Array.isArray(manifest.files)
      || manifest.files.length !== MODEL_FILES.size
      || new Set(manifest.files.map((entry) => entry.path)).size !== MODEL_FILES.size
      || manifest.files.some((entry) => !MODEL_FILES.has(entry.path))) {
    throw new Error('El paquete de modelos no tiene el formato esperado');
  }
  const userData = app.getPath('userData');
  const target = path.join(userData, 'models');
  if (fs.existsSync(target)) throw new Error('Ya hay modelos instalados; no se sobrescribieron');
  const staging = path.join(userData, `.models-import-${randomUUID()}`);
  fs.mkdirSync(staging, { recursive: true });
  try {
    const realFolder = fs.realpathSync(folder);
    for (const entry of manifest.files) {
      if (!/^[a-f0-9]{64}$/i.test(entry.sha256) || !Number.isSafeInteger(entry.size) || entry.size <= 0) {
        throw new Error(`Hash o tamaño inválido: ${entry.path}`);
      }
      const source = path.join(folder, ...entry.path.split('/'));
      const realSource = fs.realpathSync(source);
      if (!realSource.startsWith(`${realFolder}${path.sep}`) || fs.lstatSync(source).isSymbolicLink()) {
        throw new Error(`Ruta insegura: ${entry.path}`);
      }
      const destination = path.join(staging, ...entry.path.split('/'));
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      const digest = createHash('sha256');
      const hashStream = new Transform({ transform(chunk, _encoding, callback) {
        digest.update(chunk); callback(null, chunk);
      } });
      await pipeline(fs.createReadStream(source), hashStream,
        fs.createWriteStream(destination, { flags: 'wx' }));
      if (fs.statSync(destination).size !== entry.size || digest.digest('hex') !== entry.sha256.toLowerCase()) {
        throw new Error(`SHA256 o tamaño incorrecto: ${entry.path}`);
      }
    }
    fs.renameSync(staging, target);
    activateModels();
    return { installed: true, files: manifest.files.length };
  } catch (error) {
    fs.rmSync(staging, { recursive: true, force: true });
    throw error;
  }
}

// El backend lee LOCAL_ASR_MODEL_PATH al arrancar; Gemma necesita la GGUF para iniciar.
function activateModels() {
  startService('gemma');
  restartService('backend');
}

async function setupStatus() {
  const run = (bin, args) => execFileAsync(bin, args, { windowsHide: true, timeout: 10000 });
  const [firewall, network] = await Promise.all([
    run('netsh', ['advfirewall', 'firewall', 'show', 'rule', `name=${FIREWALL_RULE}`])
      .then(() => true, () => false),
    run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      '(Get-NetConnectionProfile | ForEach-Object { $_.NetworkCategory.ToString() }) -join ","'])
      .then(({ stdout }) => stdout.trim().split(',').filter(Boolean), () => []),
  ]);
  return { firewall, networkCategories: network, modelDownload: modelDownloader.status() };
}

async function healthy(url) {
  try { return (await fetch(url, { signal: AbortSignal.timeout(1500) })).ok; }
  catch { return false; }
}
function internalToken() {
  const file = path.join(app.getPath('userData'), 'internal-token');
  if (!fs.existsSync(file)) {
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, require('node:crypto').randomBytes(32).toString('hex'));
  }
  return fs.readFileSync(file, 'utf8').trim();
}
function startService(name) {
  if (quitting || processes.has(name)) return;
  const spec = serviceSpec(name);
  if (!spec?.bin || (path.isAbsolute(spec.bin) && !fs.existsSync(spec.bin))) return;
  const child = spawn(spec.bin, spec.args, { env: spec.env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'], cwd: resources() });
  processes.set(name, child);
  const drain = (stream) => stream?.on('data', (chunk) => console.log(`${name}: ${String(chunk).slice(0, 1000)}`));
  drain(child.stdout); drain(child.stderr);
  child.on('error', (error) => console.error(`${name}: ${error.message}`));
  child.on('close', () => {
    if (processes.get(name) === child) processes.delete(name);
    if (!quitting) restartTimers.set(name, setTimeout(() => { restartTimers.delete(name); startService(name); }, 2000));
  });
}
function restartService(name) {
  const timer = restartTimers.get(name);
  if (timer) clearTimeout(timer);
  restartTimers.delete(name);
  const child = processes.get(name);
  if (child) { processes.delete(name); child.kill(); }
  startService(name);
}
async function startSource(stage, input, recordingPath = null, sourceKind = 'file') {
  stage = validStage(stage);
  const ffmpeg = binary('ffmpeg');
  if (!ffmpeg) throw new Error('FFmpeg no está instalado');
  const old = sources.get(stage);
  if (old) old.kill();
  const microphone = sourceKind === 'microphone';
  const audioOnlyFile = sourceKind === 'file' && ['.wav', '.mp3', '.flac'].includes(path.extname(input.at(-1) || '').toLowerCase());
  const syntheticVideo = microphone || audioOnlyFile;
  const args = ['-nostdin', '-y', ...input,
    ...(syntheticVideo ? ['-f', 'lavfi', '-i', 'color=c=0x111332:s=1280x720:r=24'] : []),
    '-map', syntheticVideo ? '1:v:0' : '0:v:0?', '-map', '0:a:0',
    '-c:v', 'libopenh264', '-b:v', '1600k', '-g', '24', '-pix_fmt', 'yuv420p',
    '-c:a', 'aac', '-ac', '2', '-ar', '48000', '-b:a', '128k',
    ...(audioOnlyFile ? ['-shortest'] : []),
    '-f', 'flv', `rtmp://127.0.0.1:1935/live/stage-${stage}`];
  if (recordingPath) args.push('-vn', '-map', '0:a:0', '-ac', '1', '-ar', '16000',
    '-c:a', 'pcm_s16le', '-f', 'wav', recordingPath);
  const child = spawn(ffmpeg, args, { windowsHide: true, stdio: 'ignore' });
  sources.set(stage, child);
  let failure;
  child.on('error', (error) => { failure = error; });
  child.on('close', () => { if (sources.get(stage) === child) sources.delete(stage); });
  await new Promise((resolve) => setTimeout(resolve, 750));
  if (failure || child.exitCode !== null || !child.pid) {
    sources.delete(stage);
    throw new Error(`La fuente no pudo iniciarse: ${failure?.message || child.exitCode}`);
  }
  return { stage_id: stage, pid: child.pid, recording_path: recordingPath };
}
async function requireOperator(event) {
  if (!window || event.sender.id !== window.webContents.id ||
      !event.senderFrame?.url.startsWith('http://127.0.0.1:8080/')) {
    throw new Error('Ventana de operación no autorizada');
  }
  const cookies = await event.sender.session.cookies.get({
    url: 'http://127.0.0.1:8080/api/operator/me', name: 'omnistage_operator',
  });
  const token = cookies[0]?.value;
  if (!token) throw new Error('Iniciá sesión como operador');
  const response = await fetch('http://127.0.0.1:8080/api/operator/me', {
    headers: { cookie: `omnistage_operator=${token}` },
  });
  if (!response.ok) throw new Error('Sesión de operador vencida');
}
function privileged(channel, handler) {
  ipcMain.handle(channel, async (event, ...args) => {
    await requireOperator(event);
    return handler(event, ...args);
  });
}
function installIpc() {
  privileged('omni:status', async () => {
    let gpu = '';
    try { gpu = (await execFileAsync('nvidia-smi', ['--query-gpu=name,memory.used,memory.total', '--format=csv,noheader'], { windowsHide: true, timeout: 2000 })).stdout.trim(); } catch { /* no NVIDIA driver */ }
    const lanUrls = Object.values(os.networkInterfaces()).flat()
      .filter((item) => item && item.family === 'IPv4' && !item.internal)
      .map((item) => `http://${item.address}:8088`);
    const checks = await Promise.all([
      healthy('http://127.0.0.1:9997/v3/paths/list'),
      healthy('http://127.0.0.1:8092/health'),
      healthy('http://127.0.0.1:8080/healthz'),
      healthy('http://127.0.0.1:8088/healthz'),
    ]);
    const obsPaths = [
      path.join(process.env.ProgramFiles || 'C:\\Program Files', 'obs-studio', 'bin', '64bit', 'obs64.exe'),
      path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'obs-studio', 'bin', '64bit', 'obs64.exe'),
    ];
    return { services: { mediamtx: checks[0], gemma: checks[1], backend: checks[2], public: checks[3] },
      gpu, lanUrls, obsInstalled: obsPaths.some((candidate) => fs.existsSync(candidate)), sources: [...sources.keys()], models: {
        asr: fs.existsSync(path.join(app.getPath('userData'), 'models', 'faster-whisper', 'model.bin')),
        gemma: fs.existsSync(path.join(app.getPath('userData'), 'models', 'gemma-4-e2b-q4.gguf')),
      } };
  });
  privileged('omni:cloud-key-status', () => cloudKeyStore.status());
  privileged('omni:cloud-key-save', async (_event, value) => {
    const result = await cloudKeyStore.validateAndSave(value);
    if (result.state === 'ready') restartService('backend');
    return result;
  });
  privileged('omni:cloud-key-remove', () => {
    const result = cloudKeyStore.remove();
    restartService('backend');
    return result;
  });
  privileged('omni:outputs-status', () => outputManager.status());
  privileged('omni:outputs-configure', (_event, stage, config) => outputManager.configure(stage, config));
  privileged('omni:outputs-start', (_event, stage) => outputManager.start(stage));
  privileged('omni:outputs-stop', (_event, stage) => outputManager.stop(stage));
  privileged('omni:outputs-open-share', (_event, stage) => {
    const entry = outputManager.status()[validStage(stage)];
    if (!entry?.share_url) throw new Error('Esta sala no tiene una salida para reuniones.');
    return shell.openExternal(entry.share_url);
  });
  privileged('omni:setup-status', () => setupStatus());
  privileged('omni:download-models', async () => {
    const result = await modelDownloader.start();
    if (result?.installed) activateModels();
    return result;
  });
  privileged('omni:cancel-model-download', () => modelDownloader.cancel());
  privileged('omni:start-local-models', () => {
    const model = path.join(app.getPath('userData'), 'models', 'gemma-4-e2b-q4.gguf');
    if (!fs.existsSync(model)) throw new Error('Instalá Gemma antes de iniciar el motor local.');
    if (processes.has('gemma')) restartService('gemma');
    else startService('gemma');
    return { starting: true };
  });
  privileged('omni:test-local-model', (_event, input, target) => runLocalSample(input, target));
  privileged('omni:open-network-settings', () => shell.openExternal('ms-settings:network-status'));
  privileged('omni:import-models', async () => {
    const result = await dialog.showOpenDialog(window, { properties: ['openDirectory'],
      title: 'Elegí la carpeta del paquete de modelos' });
    if (result.canceled || !result.filePaths.length) return null;
    return importModelPack(result.filePaths[0]);
  });
  privileged('omni:start-file', async (_event, stage) => {
    const result = await dialog.showOpenDialog(window, { properties: ['openFile'], filters: [{ name: 'Audio y video', extensions: ['wav', 'mp3', 'mp4', 'mkv', 'mov', 'flac'] }] });
    if (result.canceled || !result.filePaths.length) return null;
    return startSource(stage, ['-re', '-i', result.filePaths[0]]);
  });
  privileged('omni:microphones', async () => {
    const ffmpeg = binary('ffmpeg');
    if (!ffmpeg) return [];
    try { await execFileAsync(ffmpeg, ['-hide_banner', '-list_devices', 'true', '-f', 'dshow', '-i', 'dummy'], { windowsHide: true, timeout: 4000 }); return []; }
    catch (error) {
      const lines = String(error.stderr || '').split(/\r?\n/);
      const names = [];
      let audio = false;
      for (const line of lines) {
        if (line.includes('DirectShow audio devices')) { audio = true; continue; }
        if (line.includes('DirectShow video devices')) audio = false;
        if (audio && !line.includes('Alternative name')) {
          const match = line.match(/"([^"]+)"/);
          if (match) names.push(match[1]);
        }
      }
      return [...new Set(names)];
    }
  });
  privileged('omni:start-microphone', async (_event, stage, name) => {
    if (typeof name !== 'string' || !name.trim()) throw new Error('Elegí un micrófono');
    const selected = await dialog.showSaveDialog(window, { title: 'Guardar grabación original del micrófono',
      defaultPath: `omnistage-sala-${validStage(stage)}-${Date.now()}.wav`,
      filters: [{ name: 'WAV sin compresión', extensions: ['wav'] }] });
    if (selected.canceled || !selected.filePath) return null;
    return startSource(stage, ['-f', 'dshow', '-i', `audio=${name}`], selected.filePath, 'microphone');
  });
  privileged('omni:stop-source', (_event, stage) => {
    stage = validStage(stage);
    sources.get(stage)?.kill(); sources.delete(stage); return true;
  });
  ipcMain.handle('omni:retry-startup', async (event) => {
    if (!window || event.sender.id !== window.webContents.id ||
        event.senderFrame?.url !== pathToFileURL(path.join(__dirname, 'splash.html')).href) {
      throw new Error('Pantalla de inicio no autorizada');
    }
    for (const name of SERVICES) startService(name);
    return openOperator();
  });
}
async function openOperator() {
  if (startupPromise) return startupPromise;
  startupPromise = (async () => {
    window.webContents.send('omni:startup-state', { phase: 'starting' });
    const started = Date.now();
    for (let attempt = 0; attempt < 60; attempt++) {
      if (window.isDestroyed()) return false;
      if (await healthy('http://127.0.0.1:8080/healthz')) {
        window.webContents.send('omni:startup-state', { phase: 'ready' });
        await new Promise((resolve) => setTimeout(resolve, Math.max(0, 1200 - (Date.now() - started))));
        await window.loadURL('http://127.0.0.1:8080/admin');
        return true;
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    window.webContents.send('omni:startup-state', { phase: 'error' });
    return false;
  })().catch(() => {
    if (window && !window.isDestroyed()) window.webContents.send('omni:startup-state', { phase: 'error' });
    return false;
  }).finally(() => { startupPromise = null; });
  return startupPromise;
}
app.whenReady().then(async () => {
  if (!app.requestSingleInstanceLock()) { app.quit(); return; }
  installIpc();
  for (const name of SERVICES) startService(name);
  window = new BrowserWindow({ width: 1440, height: 900, minWidth: 980, minHeight: 650,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true } });
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https:\/\//.test(url)) shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith('http://127.0.0.1:8080/')) event.preventDefault();
  });
  await window.loadFile(path.join(__dirname, 'splash.html'));
  await openOperator();
});
app.on('before-quit', (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownInProgress) return;
  shutdownInProgress = true;
  quitting = true;
  Promise.race([outputManager.close().catch(() => {}),
    new Promise((resolve) => setTimeout(resolve, 7000))]).finally(() => {
    for (const timer of restartTimers.values()) clearTimeout(timer);
    for (const child of sources.values()) child.kill();
    for (const child of processes.values()) child.kill();
    shutdownComplete = true;
    app.quit();
  });
});
