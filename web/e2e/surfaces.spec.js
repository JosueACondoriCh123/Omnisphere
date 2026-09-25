import { expect, test } from "@playwright/test";
import fs from "node:fs";

test("event home lists three rooms and opens the chosen one", async ({ page }) => {
  await page.route("**/api/stages", (route) => route.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ items: [1, 2, 3].map((number) => ({
      stage_id: String(number), name: `Escenario ${number}`,
      session: `Charla ${number}`, stream_up: number === 2,
      audio_up: number === 2, provider_ready: number === 2,
    })) }),
  }));
  await page.goto("/");
  await expect(page.locator(".stage-card")).toHaveCount(3);
  await expect(page.getByText("EN VIVO", { exact: true })).toBeVisible();
  await page.getByRole("link", { name: /Escenario 2/ }).click();
  await expect(page).toHaveURL(/stage=2/);
});

test("app mock shows a draft and then the same commit", async ({ page }) => {
  await page.goto("/app?mock=1");
  const cue = page.locator(".cue");
  await expect(cue).toHaveAttribute("data-state", "draft");
  await expect(cue).toHaveAttribute("data-state", "committed");
  await expect(cue).toContainText("orador abra la boca");
});

test("overlay stays transparent inside broadcast safe margins", async ({ page }) => {
  await page.goto("/overlay/1?theme=obs&lang=es&size=md&mock=1");
  const background = await page.evaluate(
    () => getComputedStyle(document.documentElement).backgroundColor,
  );
  expect(["transparent", "rgba(0, 0, 0, 0)"]).toContain(background);
  const pad = await page.locator(".lower-third").evaluate((el) => {
    const rect = el.getBoundingClientRect();
    return Math.min(
      rect.left / window.innerWidth,
      rect.top / window.innerHeight,
      (window.innerWidth - rect.right) / window.innerWidth,
      (window.innerHeight - rect.bottom) / window.innerHeight,
    );
  });
  expect(pad).toBeGreaterThanOrEqual(0.05);
});

test("clean projector has no controls and no scrolling caption pane", async ({ page }) => {
  await page.goto("/captions/clean?stage=1&lang=es&mock=1");
  await expect(page.locator("nav, button, select")).toHaveCount(0);
  const box = await page.locator(".clean-stack").evaluate((el) => ({
    overflow: getComputedStyle(el).overflow,
    scrollHeight: el.scrollHeight,
    clientHeight: el.clientHeight,
  }));
  expect(box.overflow).toBe("hidden");
  expect(box.scrollHeight).toBeLessThanOrEqual(box.clientHeight + 1);
});

test("archive downloads a timed srt", async ({ page }) => {
  await page.goto("/archive/1?lang=es&session=3&mock=1");
  await expect(page.locator(".srt-preview")).toContainText("00:14:02,300 --> 00:14:03,100");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("button", { name: "Descargar SRT" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("nerdearla_2026_stage1_sesion3.srt");
  const contents = fs.readFileSync(await download.path(), "utf8");
  expect(contents).toContain("00:14:02,300 --> 00:14:03,100");
  expect(contents).toContain("orador abra la boca");
});

test("admin shows an alarm from metrics", async ({ page }) => {
  await page.route("**/api/operator/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ id: "operator-test", email: "op@example.com", csrf_token: "test" }) }),
  );
  await page.route("**/api/operator/sessions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"items":[]}' }),
  );
  await page.route("**/api/operator/provider", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"mode":"auto","stages":{}}' }),
  );
  await page.route("**/api/metrics/stages", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          {
            stage_id: "sala-e2e",
            stream_up: true,
            audio_up: false,
            worker_state: "degraded",
            hop_latencies: [],
            alarms: [{ code: "latency_over_1500ms", severity: "critical" }],
          },
        ],
      }),
    }),
  );
  await page.goto("/admin");
  await expect(page.getByText("sala-e2e", { exact: true })).toBeVisible();
  await expect(page.locator("[data-alarm='latency_over_1500ms']")).toBeVisible();
});

test("operator navigation separates rooms, broadcasts, archive and integrations", async ({ page }) => {
  await page.route("**/api/operator/me", (route) =>
    route.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify({ id: "operator-test", email: "op@example.com", csrf_token: "test" }) }));
  await page.route("**/api/operator/sessions", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"items":[]}' }));
  await page.route("**/api/operator/provider", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"mode":"auto","stages":{}}' }));
  await page.route("**/api/metrics/stages", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: '{"items":[]}' }));
  await page.goto("/operator");
  await page.getByRole("link", { name: "Salas", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Nueva sesión" })).toBeVisible();
  await page.getByRole("link", { name: "Transmisiones" }).click();
  await expect(page.getByRole("heading", { name: "Destinos por sala" })).toBeVisible();
  await page.getByRole("link", { name: "Archivo", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sesiones y archivo" })).toBeVisible();
  await page.getByRole("link", { name: "Integraciones" }).click();
  await expect(page.getByRole("heading", { name: "Clave de nube" })).toBeVisible();
});

test("meeting output requires operator login", async ({ page }) => {
  await page.route("**/api/operator/me", (route) =>
    route.fulfill({ status: 401, contentType: "application/json", body: '{"detail":"unauthorized"}' }));
  await page.goto("/operator/output/1?lang=es");
  await expect(page.getByRole("heading", { name: "Salida protegida" })).toBeVisible();
  await expect(page.locator("iframe")).toHaveCount(0);
});

test("app controls are reachable from the keyboard", async ({ page }) => {
  await page.goto("/app?mock=1");
  await page.keyboard.press("Tab");
  await expect(page.locator("#stage-select")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#lang-select")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#size-select")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.locator("#contrast-toggle")).toBeFocused();
  const outlineWidth = await page.locator("#contrast-toggle").evaluate((el) =>
    Number.parseFloat(getComputedStyle(el).outlineWidth),
  );
  expect(outlineWidth).toBeGreaterThan(0);
});
