import { expect, test } from "@playwright/test";

test.use({ serviceWorkers: "block" });

const stages = [
  { stage_id: "1", name: "Sala 1", session_id: 10, session: "Diseño accesible" },
  { stage_id: "3", name: "Sala 3", session_id: 11, session: "Datos abiertos" },
];

test("dashboard, room search and guide form a useful public flow", async ({ page }, testInfo) => {
  await page.route("**/api/stages", (route) => route.fulfill({ json: { items: stages } }));
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: /Todo el evento/ })).toBeVisible();
  await expect(page.getByText("2", { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("dashboard.png"), fullPage: true });
  await page.getByRole("link", { name: "Salas", exact: true }).click();
  await expect(page.locator(".public-stage-card")).toHaveCount(10);
  await page.screenshot({ path: testInfo.outputPath("salas.png"), fullPage: true });
  await page.getByRole("button", { name: "Con sesión" }).click();
  await expect(page.locator(".public-stage-card")).toHaveCount(2);
  await page.getByRole("searchbox", { name: "Buscar sala o charla" }).fill("Datos abiertos");
  await expect(page.locator(".public-stage-card")).toHaveCount(1);
  await page.getByRole("combobox", { name: "Idioma inicial" }).selectOption("en");
  await expect(page.locator(".public-stage-card a")).toHaveAttribute("href", "/app?stage=3&lang=en");
  await page.getByRole("link", { name: "Guía", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tres pasos." })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("guia.png"), fullPage: true });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
});

test("new public pages fit a phone viewport", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 393, height: 851 });
  await page.route("**/api/stages", (route) => route.fulfill({ json: { items: stages } }));
  for (const route of ["/dashboard", "/salas", "/guia"]) {
    await page.goto(route);
    await expect(page.getByRole("navigation", { name: "Principal" })).toBeVisible();
    await page.screenshot({ path: testInfo.outputPath(`${route.slice(1)}-phone.png`), fullPage: true });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    expect(overflow, `${route} overflow`).toBe(false);
  }
});
