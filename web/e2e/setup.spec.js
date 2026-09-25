import { expect, test } from "@playwright/test";

const operator = { email: "operador@nerdearla.test", csrf_token: "csrf" };
const shots = process.env.SETUP_SHOTS;

async function mockApi(page) {
  await page.route("**/api/operator/me", (route) => route.fulfill({ json: operator }));
  await page.route("**/api/operator/sessions", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/operator/provider", (route) => route.fulfill({ json: { mode: "auto", stages: {} } }));
  await page.route("**/api/metrics/stages", (route) => route.fulfill({ json: { items: [] } }));
}

// Puente de escritorio simulado: modelos ausentes, red pública y descarga que avanza al pulsar.
async function mockDesktop(page) {
  await page.addInitScript(() => {
    const listeners = new Set();
    const state = { models: { asr: false, gemma: false } };
    globalThis.omniDesktop = {
      status: async () => ({
        services: { mediamtx: true, gemma: state.models.gemma, backend: true, public: true },
        models: state.models, lanUrls: ["http://192.168.0.20:8088"], gpu: "", sources: [],
      }),
      cloudKeyStatus: async () => ({ state: "missing", configured: false }),
      setupStatus: async () => ({ firewall: true, networkCategories: ["Public"], modelDownload: { phase: "idle" } }),
      onModelProgress: (callback) => { listeners.add(callback); return () => listeners.delete(callback); },
      downloadModels: () => new Promise((resolve) => {
        const total = 3835728628;
        const emit = (value) => listeners.forEach((callback) => callback(value));
        emit({ phase: "downloading", file: "gemma-4-e2b-q4.gguf", received: total * 0.42, total });
        globalThis.finishDownload = () => {
          state.models = { asr: true, gemma: true };
          emit({ phase: "installed", file: "", received: total, total });
          resolve({ installed: true, files: 5 });
        };
      }),
      cancelModelDownload: async () => true,
      importModels: async () => null,
      openNetworkSettings: async () => { globalThis.networkSettingsOpened = true; },
      listMicrophones: async () => [],
      outputStatus: async () => ({}),
    };
  });
}

test("first run guide downloads models and flags a public network", async ({ page }) => {
  await mockApi(page);
  await mockDesktop(page);
  await page.goto("/admin");
  const guide = page.getByRole("region", { name: "Primeros pasos" });
  await expect(guide).toBeVisible();
  await expect(guide.getByText("1/4")).toBeVisible();
  await expect(guide.getByText(/Windows marcó esta red como/)).toBeVisible();
  await guide.getByRole("button", { name: "Abrir configuración de red" }).click();
  expect(await page.evaluate(() => globalThis.networkSettingsOpened)).toBe(true);

  await guide.getByRole("button", { name: "Descargar modelos" }).click();
  await expect(guide.getByRole("progressbar", { name: "Descarga de modelos" })).toBeVisible();
  await expect(guide.getByText(/42 %/)).toBeVisible();
  await expect(guide.getByRole("button", { name: "Pausar descarga" })).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/setup-downloading-${test.info().project.name}.png`, fullPage: true });

  await page.evaluate(() => globalThis.finishDownload());
  await expect(guide.getByText("faster-whisper y Gemma 4 E2B instalados y verificados.")).toBeVisible();
  await expect(guide.getByText("3/4")).toBeVisible();
});

test("guide stays reachable from the sidebar once setup is done", async ({ page }) => {
  await mockApi(page);
  await mockDesktop(page);
  await page.addInitScript(() => { globalThis.omniDesktop.status = async () => ({
    services: { mediamtx: true, gemma: true, backend: true, public: true },
    models: { asr: true, gemma: true }, lanUrls: [], gpu: "", sources: [] }); });
  await page.goto("/admin");
  await expect(page.getByRole("region", { name: "Primeros pasos" })).toHaveCount(0);
  await page.getByRole("link", { name: /Primeros pasos/ }).click();
  await expect(page.getByRole("region", { name: "Primeros pasos" })).toBeVisible();
});

test("initial account screen announces the guided setup", async ({ page }) => {
  await page.route("**/api/operator/me", (route) => route.fulfill({ status: 401, json: {} }));
  await page.route("**/api/operator/bootstrap-status", (route) => route.fulfill({ json: { needs_setup: true } }));
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Crear operador inicial" })).toBeVisible();
  await expect(page.getByText(/Paso 1 de la instalación/)).toBeVisible();
  if (shots) await page.screenshot({ path: `${shots}/setup-account-${test.info().project.name}.png` });
});
