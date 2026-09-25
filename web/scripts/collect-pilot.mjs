import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

function args(argv) {
  const result = {};
  for (let i = 0; i < argv.length; i += 2) {
    if (!argv[i]?.startsWith("--") || !argv[i + 1]) throw new Error(`Argumento inválido: ${argv[i]}`);
    result[argv[i].slice(2)] = argv[i + 1];
  }
  for (const key of ["base-url", "route", "recordings", "sources", "out"]) {
    if (!result[key]) throw new Error(`Falta --${key}`);
  }
  if (!["cloud", "local"].includes(result.route)) throw new Error("--route debe ser cloud o local");
  result.duration = Number(result["duration-seconds"] || 3600);
  if (!Number.isFinite(result.duration) || result.duration <= 0) throw new Error("Duración inválida");
  return result;
}

function mapping(value) {
  const entries = value.split(",").map((item) => item.split(":"));
  if (entries.length !== 3 || entries.some(([stage, name]) => !["1", "2", "3"].includes(stage) || !name)) {
    throw new Error("Se requieren los pares 1:valor,2:valor,3:valor");
  }
  return Object.fromEntries(entries);
}

async function clockOffset(page, baseUrl) {
  const samples = [];
  for (let i = 0; i < 9; i += 1) {
    const sample = await page.evaluate(async (url) => {
      const before = Date.now();
      const response = await fetch(`${url}/api/time`, { cache: "no-store" });
      if (!response.ok) throw new Error(`Reloj HTTP ${response.status}`);
      const { server_wall_ms: server } = await response.json();
      const after = Date.now();
      return { offset: server - (before + after) / 2, uncertainty: (after - before) / 2 };
    }, baseUrl);
    samples.push(sample);
  }
  samples.sort((a, b) => a.uncertainty - b.uncertainty);
  if (samples[0].uncertainty > 100) throw new Error("Incertidumbre del reloj supera 100 ms");
  return samples[0];
}

const options = args(process.argv.slice(2));
const baseUrl = options["base-url"].replace(/\/$/, "");
const recordingIds = mapping(options.recordings);
const sourceTypes = mapping(options.sources);
if (Object.values(sourceTypes).some((value) => !["obs", "file", "microphone"].includes(value))) {
  throw new Error("Fuentes válidas: obs, file, microphone");
}
const output = path.resolve(options.out);
let started = 0;
const observations = ["1", "2", "3"].map((stage) => ({
  recording_id: recordingIds[stage], route: options.route, stage_id: stage,
  source_type: sourceTypes[stage], started_wall_ms: null,
  ended_wall_ms: null, captions: [], dropped_clauses: null, provider_samples: [],
  cloud_audio_minutes: 0, translation_input_tokens: 0, translation_output_tokens: 0,
  final_clause_count: 0, committed_clause_count: 0, gpu_memory_peak_mib: null,
}));
const byStage = Object.fromEntries(observations.map((item) => [item.stage_id, item]));
const seen = new Set();
let browser;

function checkpoint() {
  fs.mkdirSync(path.dirname(output), { recursive: true });
  const temporary = `${output}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify({ observations }, null, 2)}\n`, "utf8");
  fs.renameSync(temporary, output);
}

try {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const pages = [];
  for (const stage of ["1", "2", "3"]) {
    for (const lang of ["es", "en"]) {
      const page = await context.newPage();
      let offset = { offset: 0, uncertainty: Infinity };
      await page.exposeBinding("__omniPilotPaint", (_, caption) => {
        const key = `${caption.session_id}:${caption.clause_id}:${lang}`;
        const visible = Math.round(caption.visible_browser_ms + offset.offset);
        if (!started || !caption.audio_end_wall_ms || caption.audio_end_wall_ms < started || visible < started) return;
        if (seen.has(key)) return;
        seen.add(key);
        byStage[stage].captions.push({
          ...caption, stage_id: stage, lang, state: "committed", visible_wall_ms: visible,
          clock_uncertainty_ms: offset.uncertainty,
        });
      });
      await page.addInitScript(() => {
        const noticed = new Set();
        const scan = () => {
          for (const node of document.querySelectorAll('.cue[data-state="committed"][data-clause-id]')) {
            const key = `${node.dataset.sessionId}:${node.dataset.clauseId}:${node.dataset.lang}`;
            if (noticed.has(key)) continue;
            noticed.add(key);
            requestAnimationFrame(() => requestAnimationFrame(() => {
              if (!node.isConnected) return;
              const rect = node.getBoundingClientRect();
              if (rect.width <= 0 || rect.height <= 0) return;
              window.__omniPilotPaint({
                session_id: node.dataset.sessionId, clause_id: node.dataset.clauseId,
                provider: node.dataset.provider, text: node.textContent,
                t0_ms: Number(node.dataset.t0), t1_ms: Number(node.dataset.t1),
                audio_end_wall_ms: Number(node.dataset.audioEndWallMs),
                visible_browser_ms: Date.now(),
              });
            }));
          }
        };
        new MutationObserver(scan).observe(document, { childList: true, subtree: true, attributes: true });
        document.addEventListener("DOMContentLoaded", scan);
      });
      await page.goto(`${baseUrl}/app?stage=${stage}&lang=${lang}`, { waitUntil: "domcontentloaded" });
      offset = await clockOffset(page, baseUrl);
      pages.push({ page, updateClock: async () => { offset = await clockOffset(page, baseUrl); } });
    }
  }
  console.log(`Observando seis vistas reales en ${baseUrl} por ${options.duration} segundos`);
  const pollStatus = async () => {
    const response = await fetch(`${baseUrl}/api/stages`, { cache: "no-store" });
    if (!response.ok) throw new Error(`Estado LAN HTTP ${response.status}`);
    const status = await response.json();
    for (const row of status.items || []) {
      const observation = byStage[String(row.stage_id)];
      if (!observation) continue;
      const dropped = Number(row.dropped_clauses);
      if (Number.isFinite(dropped)) {
        observation.dropped_clauses = Math.max(observation.dropped_clauses ?? 0, dropped);
      }
      for (const key of ["cloud_audio_minutes", "translation_input_tokens", "translation_output_tokens"]) {
        const value = Number(row[key]);
        if (Number.isFinite(value)) observation[key] = Math.max(observation[key], value);
      }
      if (started) observation.provider_samples.push({ at_wall_ms: Date.now(), provider: row.provider,
        ready: row.provider_ready, stream_up: row.stream_up, audio_up: row.audio_up,
        session_id: row.active_session_id, source_type: row.source_type });
    }
    return status.items || [];
  };
  const readyDeadline = Date.now() + 300_000;
  let readyRows;
  while (true) {
    const rows = await pollStatus();
    if (["1", "2", "3"].every((stage) => rows.some((row) =>
      String(row.stage_id) === stage && row.audio_up && row.provider_ready
      && row.provider === options.route))) { readyRows = rows; break; }
    if (Date.now() >= readyDeadline) throw new Error("Tres salas y proveedor no estuvieron listos en cinco minutos");
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  started = Date.now();
  const baselines = Object.fromEntries(readyRows.map((row) => [String(row.stage_id), {
    final: Number(row.final_clause_count || 0), committed: Number(row.committed_clause_count || 0),
  }]));
  for (const item of observations) {
    item.started_wall_ms = started;
    item.provider_samples = [];
    item.dropped_clauses = 0;
  }
  console.log("Tres salas listas; comienza la medición");
  const statusTimer = setInterval(() => {
    pollStatus().then(() => {
      try {
        const used = Number(execFileSync("nvidia-smi", ["--query-gpu=memory.used", "--format=csv,noheader,nounits"],
          { encoding: "utf8", timeout: 3000 }).trim().split(/\r?\n/)[0]);
        if (Number.isFinite(used)) for (const item of observations) {
          item.gpu_memory_peak_mib = Math.max(item.gpu_memory_peak_mib || 0, used);
        }
      } catch { /* The demo PC may have no NVIDIA tooling. */ }
    }).catch((error) => console.error(error.message));
  }, 5000);
  const clockTimer = setInterval(() => {
    Promise.all(pages.map((item) => item.updateClock())).catch((error) => console.error(error.message));
  }, 300_000);
  const checkpointTimer = setInterval(checkpoint, 30_000);
  try {
    await new Promise((resolve) => setTimeout(resolve, options.duration * 1000));
    await new Promise((resolve) => setTimeout(resolve, 10_000));
    const rows = await pollStatus();
    for (const row of rows) {
      const stage = String(row.stage_id);
      const item = byStage[stage];
      if (!item || !baselines[stage]) continue;
      item.final_clause_count = Number(row.final_clause_count || 0) - baselines[stage].final;
      item.committed_clause_count = Number(row.committed_clause_count || 0) - baselines[stage].committed;
    }
  } finally {
    clearInterval(clockTimer);
    clearInterval(statusTimer);
    clearInterval(checkpointTimer);
  }
} finally {
  const ended = Date.now();
  for (const item of observations) item.ended_wall_ms = ended;
  checkpoint();
  if (browser) await browser.close();
}
