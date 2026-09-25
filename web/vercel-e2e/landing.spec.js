import { expect, test } from "@playwright/test";

test("landing stays useful before the live backend is connected", async ({ page }, testInfo) => {
  const apiRequests = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) apiRequests.push(request.url());
  });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Cada palabra nos encuentra/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Los escenarios se publicarán aquí" })).toBeVisible();
  await expect(page.getByRole("link", { name: /Ver una muestra/ })).toBeVisible();
  expect(apiRequests).toEqual([]);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
  expect(overflow).toBe(false);
  await page.screenshot({ path: testInfo.outputPath("landing.png"), fullPage: true });
  await page.getByRole("link", { name: /Ver una muestra/ }).click();
  await expect(page).toHaveURL(/\/app\?mock=1/);
  await expect(page.locator(".audience")).toBeVisible();
  await expect(page.locator(".status")).toContainText("demo");
});

test("public build has no operator screen", async ({ page }) => {
  await page.goto("/operator");
  await expect(page.getByRole("heading", { name: /Nos vemos en el escenario/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Acceso de operadores" })).toHaveCount(0);
});

test("dashboard and new pages work before a backend is connected", async ({ page }) => {
  const apiRequests = [];
  page.on("request", (request) => { if (request.url().includes("/api/")) apiRequests.push(request.url()); });
  await page.goto("/dashboard");
  await expect(page.getByRole("heading", { name: /Todo el evento/ })).toBeVisible();
  await expect(page.getByText("Estado no disponible").first()).toBeVisible();
  await page.getByRole("link", { name: "Salas", exact: true }).click();
  await expect(page.locator(".public-stage-card")).toHaveCount(10);
  await page.getByRole("link", { name: "Guía", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tres pasos." })).toBeVisible();
  expect(apiRequests).toEqual([]);
});
