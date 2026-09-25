import { expect, test } from "@playwright/test";

const operator = { id: "visual-operator", email: "operacion@omnistage.local", csrf_token: "visual" };
const rooms = Array.from({ length: 10 }, (_, index) => index + 1).map((stage) => ({
  stage_id: String(stage), stream_up: stage !== 3, audio_up: stage === 1,
  transcriber_up: stage === 1, provider: stage === 1 ? "Gemini Live" : "local",
  latency_ms: stage === 1 ? 847 : null, alarms: [],
}));

async function mockOperator(page) {
  await page.route("**/api/operator/me", (route) => route.fulfill({ json: operator }));
  await page.route("**/api/operator/sessions", (route) => route.fulfill({ json: { items: [] } }));
  await page.route("**/api/operator/provider", (route) => route.fulfill({ json: { mode: "auto", stages: {} } }));
  await page.route("**/api/metrics/stages", (route) => route.fulfill({ json: { items: rooms } }));
  await page.route("**/api/stages", (route) => route.fulfill({ json: { items: rooms.map((room) => ({ stage_id: room.stage_id, name: `Sala ${room.stage_id}`, languages: ["es", "en"] })) } }));
  await page.route("**/api/operator/bootstrap-status", (route) => route.fulfill({ json: { enabled: false } }));
}

async function expectNoHorizontalOverflow(page) {
  const { scrollWidth, innerWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
  }));
  expect(scrollWidth).toBeLessThanOrEqual(innerWidth + 1);
}

for (const [width, height] of [[1440, 900], [980, 650]]) {
  test(`operator layout fits ${width} × ${height}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height });
    await mockOperator(page);
    await page.goto("/operator");
    await expect(page.getByRole("heading", { name: "Resumen del evento" })).toBeVisible();
    await expect(page.locator(".room-status")).toHaveCount(10);
    await expect(page.getByRole("navigation", { name: "Operación" })).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.screenshot({ path: testInfo.outputPath(`operator-${width}.png`), fullPage: true });
  });
}

test("mobile audience keeps controls and captions within the viewport", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await page.goto("/app?stage=1&lang=es&mock=1");
  await expect(page.locator(".cue[data-state='committed']")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("audience-mobile.png"), fullPage: true });
  await page.getByRole("checkbox", { name: "Alto contraste" }).click();
  await expect(page.getByRole("checkbox", { name: "Alto contraste" })).toBeChecked();
  await expect(page.locator(".audience")).toHaveClass(/contrast/);
  await expect(page.locator(".audience")).toHaveCSS("background-color", "rgb(5, 5, 5)");
  await expectNoHorizontalOverflow(page);
});

test("broadcast and archive fit the compact desktop", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 980, height: 650 });
  await mockOperator(page);
  await page.goto("/operator/broadcasts");
  await expect(page.locator(".broadcast-room")).toHaveCount(10);
  await page.locator(".broadcast-room").last().locator("summary").click();
  await expect(page.locator(".broadcast-room").last()).toHaveAttribute("open", "");
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("broadcast-980.png"), fullPage: true });
  await page.goto("/archive/1?mock=1");
  await expect(page.locator(".srt-preview")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("archive-980.png"), fullPage: true });
});

test("room ten can be selected for a session", async ({ page }) => {
  await mockOperator(page);
  await page.goto("/operator/rooms");
  await page.getByRole("combobox", { name: "Sala" }).selectOption("10");
  await expect(page.getByText("stage-10", { exact: true })).toBeVisible();
});

test("desktop entrance balances the live preview and room cards", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.route("**/api/stages", (route) => route.fulfill({ json: { items: Array.from({ length: 10 }, (_, index) => index + 1).map((stage) => ({
    stage_id: String(stage), name: `Escenario ${stage}`, session: `Charla ${stage}`,
    audio_up: stage === 1, provider_ready: stage === 1,
  })) } }));
  await page.goto("/");
  await expect(page.locator(".hero-preview")).toBeVisible();
  await expect(page.locator(".stage-card")).toHaveCount(10);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("entrance-1440.png"), fullPage: true });
});

test("operator access fits the compact desktop", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 980, height: 650 });
  await page.route("**/api/operator/me", (route) => route.fulfill({ status: 401, json: {} }));
  await page.route("**/api/operator/bootstrap-status", (route) => route.fulfill({ json: { needs_setup: false } }));
  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: "Acceso de operadores" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("access-980.png"), fullPage: true });
});

test("remaining operator sections fit the compact desktop", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 980, height: 650 });
  await mockOperator(page);
  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: "Resumen del evento" })).toBeVisible();
  for (const section of ["Salas", "Archivo", "Integraciones", "Sistema y operadores"]) {
    await page.getByRole("link", { name: section, exact: true }).click();
    await expect(page.locator(".operator-intro h1")).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
  await page.screenshot({ path: testInfo.outputPath("system-980.png"), fullPage: true });
});

test("mobile entrance keeps all room cards readable", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await page.route("**/api/stages", (route) => route.fulfill({ json: { items: Array.from({ length: 10 }, (_, index) => index + 1).map((stage) => ({
    stage_id: String(stage), name: `Escenario ${stage}`, session: `Charla ${stage}`,
    audio_up: stage === 1, provider_ready: stage === 1,
  })) } }));
  await page.goto("/");
  await expect(page.locator(".stage-card")).toHaveCount(10);
  await expectNoHorizontalOverflow(page);
  await page.screenshot({ path: testInfo.outputPath("entrance-mobile.png"), fullPage: true });
});
